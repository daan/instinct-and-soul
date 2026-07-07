"""
test_thermal/main.py — M5 Thermal2 unit (MLX90640) probe for the M5StickS3.

Flash with:
    flash test/STICKS3/test_thermal

Wiring: Thermal2 unit on the Grove port -> hardware I2C bus 0, sda=Pin(9),
scl=Pin(10) — same bus/pins as the puppyc ToF (bus 1 is reserved by the
internal IMU, see creatures/puppyc/main.py).

The Thermal2 is NOT a bare MLX90640: an onboard MCU reads the sensor and
exposes a register map at I2C addr 0x32. Protocol cribbed from
m5stack/M5Unit-Thermal2 (Arduino) and uiflow-micropython unit/thermal2.py:

    0x04..0x05  device id, expect 0x90 0x64
    0x0B        refresh rate 0..7 = 0.5,1,2,4,8,16,32,64 Hz (per subpage)
    0x6E        refresh ctrl: bit0 = new data ready; write 0 to re-arm
    0x6F        subpage (0/1) of the data currently in the buffer
    0x70..0x7F  overview: median u16, avg u16, most-diff u16 + x,y,
                lowest u16 + x,y, highest u16 + x,y   (all raw, LE)
    0x80..      384 x u16 LE raw pixels = ONE subpage (half the 32x24 frame,
                chessboard interleave):
                    y = idx >> 4
                    x = ((idx & 15) << 1) + ((y & 1) != subpage)

    temp in C = raw / 128 - 64

What it does:
- Renders the 32x24 image at 4x (128x96) with an ironbow-ish palette,
  autoscaled to a smoothed frame min/max. Each arriving subpage repaints its
  half of the chessboard; the other half persists (cheap interlacing).
- White box marks the hottest pixel (position comes free from the overview
  registers — handy for a future robot-dog "warmest thing = friend" instinct).
- min/avg/max + fps on screen, one summary line to serial per second.

Next step: fold this into a driver in creatures/puppyc/lib/ and expose
"warmest direction / warmth amount" to instincts like read_distance_mm().
"""

import M5
import time
import struct
from machine import Pin, I2C

M5.begin()

W = M5.Widgets
F = W.FONTS
D = M5.Display

ADDR = 0x32
SCALE = 4
IMG_X = 3
IMG_Y = 40

W.fillScreen(0x000000)
W.Label("test_thermal", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu18)
lbl_status = W.Label("probing 0x32...", 4, 24, 1.0, 0x66ff66, 0x000000, F.DejaVu12)

i2c = I2C(0, sda=Pin(9), scl=Pin(10), freq=400000)

found = i2c.scan()
print("test_thermal: i2c scan:", [hex(a) for a in found])
if ADDR not in found:
    lbl_status.setText("no 0x32!")
    W.Label("scan: " + (",".join(hex(a) for a in found) or "empty"),
            4, 44, 1.0, 0xff4444, 0x000000, F.DejaVu12)
    while True:
        M5.update()
        time.sleep_ms(200)

dev = i2c.readfrom_mem(ADDR, 0x04, 2)
print("test_thermal: device id {:02x} {:02x} (expect 90 64)".format(dev[0], dev[1]))

# 8 Hz refresh (value 4). One refresh = one subpage -> full frames at ~4 Hz,
# which is about what the fillRect repaint below can keep up with anyway.
i2c.writeto_mem(ADDR, 0x0B, b"\x04")
i2c.writeto_mem(ADDR, 0x6E, b"\x00")  # arm data-ready

lbl_status.setText("id {:02x}{:02x}  8Hz  addr 0x32".format(dev[0], dev[1]))

# Readout text under the image (image spans y 40..136)
lbl_max = W.Label("", 4, 144, 1.0, 0xff8844, 0x000000, F.DejaVu12)
lbl_avg = W.Label("", 4, 160, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_min = W.Label("", 4, 176, 1.0, 0x44aaff, 0x000000, F.DejaVu12)
lbl_fps = W.Label("", 4, 196, 1.0, 0xaaaaaa, 0x000000, F.DejaVu12)


def build_palette(n=64):
    """Ironbow-ish gradient: black -> purple -> red -> orange -> yellow -> white."""
    stops = [
        (0x00, 0x00, 0x00),
        (0x30, 0x00, 0x70),
        (0x90, 0x10, 0x90),
        (0xD0, 0x30, 0x00),
        (0xFF, 0xA0, 0x00),
        (0xFF, 0xFF, 0x40),
        (0xFF, 0xFF, 0xFF),
    ]
    segs = len(stops) - 1
    pal = []
    for i in range(n):
        f = i * segs / (n - 1)
        s = min(segs - 1, int(f))
        t = f - s
        r0, g0, b0 = stops[s]
        r1, g1, b1 = stops[s + 1]
        pal.append((int(r0 + (r1 - r0) * t) << 16)
                   | (int(g0 + (g1 - g0) * t) << 8)
                   | int(b0 + (b1 - b0) * t))
    return pal


PAL = build_palette()
TOP = len(PAL) - 1


def celsius(raw):
    return raw / 128 - 64


disp_lo = None   # smoothed autoscale bounds (raw units)
disp_hi = None
subpages = 0
last_stat = time.ticks_ms()

while True:
    M5.update()

    ctrl = i2c.readfrom_mem(ADDR, 0x6E, 2)   # [refresh ctrl, subpage]
    if not (ctrl[0] & 0x01):
        time.sleep_ms(5)
        continue
    subpage = ctrl[1] & 1

    ov = struct.unpack("<HHHBBHBBHBB", i2c.readfrom_mem(ADDR, 0x70, 16))
    med, avg = ov[0], ov[1]
    lo_raw, hi_raw = ov[5], ov[8]
    hot_x, hot_y = ov[9], ov[10]

    buf = i2c.readfrom_mem(ADDR, 0x80, 768)
    i2c.writeto_mem(ADDR, 0x6E, b"\x00")     # re-arm for the next subpage

    # Smooth the autoscale so the palette doesn't flicker frame to frame.
    if disp_lo is None:
        disp_lo, disp_hi = lo_raw, hi_raw
    else:
        disp_lo += (lo_raw - disp_lo) * 0.2
        disp_hi += (hi_raw - disp_hi) * 0.2
    span = disp_hi - disp_lo
    if span < 256:          # clamp to >= 2C so a flat scene doesn't amplify noise
        span = 256

    vals = struct.unpack("<384H", buf)
    k = TOP / span
    lo = disp_lo
    fill = D.fillRect
    for i in range(384):
        y = i >> 4
        x = ((i & 15) << 1) + ((y & 1) != subpage)
        lvl = int((vals[i] - lo) * k)
        if lvl < 0:
            lvl = 0
        elif lvl > TOP:
            lvl = TOP
        fill(IMG_X + x * SCALE, IMG_Y + y * SCALE, SCALE, SCALE, PAL[lvl])

    # Hottest pixel marker (redrawn every subpage; next repaint erases it).
    D.drawRect(IMG_X + hot_x * SCALE, IMG_Y + hot_y * SCALE, SCALE, SCALE, 0xFFFFFF)

    subpages += 1
    now = time.ticks_ms()
    dt = time.ticks_diff(now, last_stat)
    if dt >= 1000:
        fps = subpages * 500.0 / dt          # 2 subpages = 1 full frame
        lbl_max.setText("max {:5.1f} C".format(celsius(hi_raw)))
        lbl_avg.setText("avg {:5.1f} C".format(celsius(avg)))
        lbl_min.setText("min {:5.1f} C".format(celsius(lo_raw)))
        lbl_fps.setText("{:.1f} fps  hot {},{}".format(fps, hot_x, hot_y))
        print("test_thermal: min={:.1f} med={:.1f} avg={:.1f} max={:.1f} hot=({},{}) fps={:.1f}".format(
            celsius(lo_raw), celsius(med), celsius(avg), celsius(hi_raw), hot_x, hot_y, fps))
        subpages = 0
        last_stat = now
