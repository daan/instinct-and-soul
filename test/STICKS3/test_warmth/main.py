"""
test_warmth/main.py — warm-blob extraction probe for the M5StickS3 + Thermal2.

Flash with:
    flash test/STICKS3/test_warmth

The step between test_thermal (raw image works) and the puppy's Warmth organ
(sim_creatures/puppy/README.md): run the actual firmware-side blob extraction
on-device and judge its quality on the display before anything streams.

What it computes, per frame (the future /warm packet contract):
    ambient    frame median C (from the unit's overview regs — robust as long
               as the warm shape fills < half the view)
    blob       largest 4-connected component above ambient + delta:
               area px, centroid (excess-weighted, camera frame),
               mean C above ambient, bounding box
What it shows:
    - the 32x24 image (same interlaced repaint as test_thermal)
    - white box = blob bounds, cyan dot = centroid
    - ambient / delta / area / +C / centroid / fps as text
    - BtnA cycles delta (1.5 / 2.5 / 4.0 / 6.0 C) to probe the detection
      margin: person vs radiator vs coffee cup, near vs across the room
    - serial: one summary line per second (greppable for later tuning)

Judging notes for the session: a person at 3 m should be a few px yet still
separate cleanly from ambient at d=2.5; a hand at 30 cm should near-fill the
view; blob area flicker at a fixed pose is the noise floor the Warmth organ's
presence() smoothing will have to absorb.

Register protocol notes: see test/STICKS3/test_thermal/main.py.
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

DELTAS = (1.5, 2.5, 4.0, 6.0)   # C above ambient; BtnA cycles
MIN_AREA = 2                     # px; reject single-pixel noise blobs

W.fillScreen(0x000000)
W.Label("test_warmth", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu18)
lbl_status = W.Label("probing 0x32...", 4, 24, 1.0, 0x66ff66, 0x000000, F.DejaVu12)

i2c = I2C(0, sda=Pin(9), scl=Pin(10), freq=400000)

found = i2c.scan()
print("test_warmth: i2c scan:", [hex(a) for a in found])
if ADDR not in found:
    lbl_status.setText("no 0x32!")
    W.Label("scan: " + (",".join(hex(a) for a in found) or "empty"),
            4, 44, 1.0, 0xff4444, 0x000000, F.DejaVu12)
    while True:
        M5.update()
        time.sleep_ms(200)

i2c.writeto_mem(ADDR, 0x0B, b"\x04")   # 8 Hz subpages -> ~4 full fps
i2c.writeto_mem(ADDR, 0x6E, b"\x00")   # arm data-ready

# Text: ambient+delta / blob / centroid / fps  (image spans y 40..136)
lbl_amb  = W.Label("", 4, 144, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_blob = W.Label("", 4, 160, 1.0, 0xff8844, 0x000000, F.DejaVu12)
lbl_cen  = W.Label("", 4, 176, 1.0, 0x44ffff, 0x000000, F.DejaVu12)
lbl_fps  = W.Label("", 4, 196, 1.0, 0xaaaaaa, 0x000000, F.DejaVu12)


def build_palette(n=64):
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


def largest_blob(frame, thr_raw, amb_raw):
    """Largest 4-connected component of frame pixels > thr_raw.

    frame: 768 raw u16 values, row-major 32x24.
    Returns (area, cx, cy, mean_excess_c, x0, y0, x1, y1) or None.
    Centroid is weighted by excess over *ambient* so the hot core dominates;
    mean excess is also over ambient (the /warm contract), not the threshold.
    """
    visited = bytearray(768)
    best = None
    for start in range(768):
        if visited[start] or frame[start] <= thr_raw:
            continue
        stack = [start]
        visited[start] = 1
        area = 0
        wsum = 0
        wx = 0
        wy = 0
        x0, y0, x1, y1 = 31, 23, 0, 0
        while stack:
            i = stack.pop()
            x = i & 31
            y = i >> 5
            w = frame[i] - amb_raw          # excess over ambient, raw units
            area += 1
            wsum += w
            wx += w * x
            wy += w * y
            if x < x0: x0 = x
            if x > x1: x1 = x
            if y < y0: y0 = y
            if y > y1: y1 = y
            if x > 0 and not visited[i - 1] and frame[i - 1] > thr_raw:
                visited[i - 1] = 1
                stack.append(i - 1)
            if x < 31 and not visited[i + 1] and frame[i + 1] > thr_raw:
                visited[i + 1] = 1
                stack.append(i + 1)
            if y > 0 and not visited[i - 32] and frame[i - 32] > thr_raw:
                visited[i - 32] = 1
                stack.append(i - 32)
            if y < 23 and not visited[i + 32] and frame[i + 32] > thr_raw:
                visited[i + 32] = 1
                stack.append(i + 32)
        if area >= MIN_AREA and wsum > 0 and (best is None or area > best[0]):
            best = (area, wx / wsum, wy / wsum, (wsum / area) / 128, x0, y0, x1, y1)
    return best


frame = [0] * 768        # persistent full frame, half refreshed per subpage
have = [False, False]    # which subpages have arrived at least once
delta_i = 1              # start at 2.5 C
disp_lo = None
disp_hi = None
subpages = 0
last_stat = time.ticks_ms()
blob = None

while True:
    M5.update()

    if M5.BtnA.wasPressed():
        delta_i = (delta_i + 1) % len(DELTAS)

    ctrl = i2c.readfrom_mem(ADDR, 0x6E, 2)
    if not (ctrl[0] & 0x01):
        time.sleep_ms(5)
        continue
    subpage = ctrl[1] & 1

    ov = struct.unpack("<HHHBBHBBHBB", i2c.readfrom_mem(ADDR, 0x70, 16))
    med, lo_raw, hi_raw = ov[0], ov[5], ov[8]

    buf = i2c.readfrom_mem(ADDR, 0x80, 768)
    i2c.writeto_mem(ADDR, 0x6E, b"\x00")

    vals = struct.unpack("<384H", buf)
    for i in range(384):
        y = i >> 4
        frame[(y << 5) + ((i & 15) << 1) + ((y & 1) != subpage)] = vals[i]
    have[subpage] = True

    # ── image (autoscaled, same as test_thermal) ────────────────────────
    if disp_lo is None:
        disp_lo, disp_hi = lo_raw, hi_raw
    else:
        disp_lo += (lo_raw - disp_lo) * 0.2
        disp_hi += (hi_raw - disp_hi) * 0.2
    span = disp_hi - disp_lo
    if span < 256:
        span = 256
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

    # ── blob extraction (needs both subpages at least once) ────────────
    if have[0] and have[1]:
        amb_raw = med
        thr_raw = med + int(DELTAS[delta_i] * 128)
        blob = largest_blob(frame, thr_raw, amb_raw)

    if blob:
        area, cx, cy, mexc, x0, y0, x1, y1 = blob
        D.drawRect(IMG_X + x0 * SCALE, IMG_Y + y0 * SCALE,
                   (x1 - x0 + 1) * SCALE, (y1 - y0 + 1) * SCALE, 0xFFFFFF)
        D.fillRect(IMG_X + int(cx * SCALE) + SCALE // 2 - 1,
                   IMG_Y + int(cy * SCALE) + SCALE // 2 - 1, 3, 3, 0x00FFFF)

    subpages += 1
    now = time.ticks_ms()
    dt = time.ticks_diff(now, last_stat)
    if dt >= 1000:
        fps = subpages * 500.0 / dt
        lbl_amb.setText("amb {:4.1f}C  d {:.1f}".format(celsius(med), DELTAS[delta_i]))
        if blob:
            area, cx, cy, mexc, x0, y0, x1, y1 = blob
            lbl_blob.setText("blob {:3d}px  +{:.1f}C".format(area, mexc))
            lbl_cen.setText("at {:4.1f},{:4.1f}".format(cx, cy))
            print("test_warmth: amb={:.1f} d={:.1f} area={} exc={:.1f} cen=({:.1f},{:.1f}) bbox=({},{},{},{}) max={:.1f} fps={:.1f}".format(
                celsius(med), DELTAS[delta_i], area, mexc, cx, cy, x0, y0, x1, y1, celsius(hi_raw), fps))
        else:
            lbl_blob.setText("no warm shape")
            lbl_cen.setText("")
            print("test_warmth: amb={:.1f} d={:.1f} no-blob max={:.1f} fps={:.1f}".format(
                celsius(med), DELTAS[delta_i], celsius(hi_raw), fps))
        lbl_fps.setText("{:.1f} fps".format(fps))
        subpages = 0
        last_stat = now
