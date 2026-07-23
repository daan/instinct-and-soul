"""
main.py — M5StickS3 perception runtime (robot_dog stage 2_perception).

The dog's senses, alone: a VL53L0X time-of-flight ranger (0x29) and the
M5 Thermal2 unit (MLX90640 behind an MCU, 0x32) SHARING the Grove hardware
I²C bus (I2C(0), sda=9, scl=10). No legs — the PuppyC HAT is absent in this
stage; 1_action has the motion half, 3_combined will merge them.

The runtime owns a PERCEPTION PUMP task that runs regardless of WiFi/spine
state, so the display is the iteration instrument (flash → look):

  - the 32x24 thermal image, autoscaled, interlaced repaint per subpage
  - white box = largest warm blob bounds, cyan dot = its centroid
    (extraction ported from test/STICKS3/test_warmth — the /warm contract:
    ambient = frame median; blob = largest 4-connected component above
    ambient + delta; centroid excess-weighted)
  - ambient / delta / blob area / +C / centroid / ToF mm / fps as text
  - BtnA cycles delta (1.5 / 2.5 / 4.0 / 6.0 C) to probe detection margin
  - serial: one greppable "perc:" summary line per second

Instincts don't touch the sensors; they read percepts the pump maintains:

  warm()             → dict: present, area, cx, cy, excess_c, ambient_c,
                       age_ms (stale-aware; camera frame, never "a person")
  read_distance_mm() → latest ToF mm (0 = no echo), or None if absent
  set_warm_delta(c)  → detection threshold, C above ambient
  set_thermal_draw(on) → give the screen to the instinct (False) or the
                       pump (True; also redraws the layout)

WiFi failure is non-fatal here: perception iteration must not need a
network. The WS reconnect loop keeps retrying in the background.

Register protocol notes for the Thermal2: see test/STICKS3/test_thermal.
"""

import M5
from M5 import *
import time

M5.begin()

# Bail-out: hold BtnA during the first 3s after boot to drop to REPL.
Widgets.fillScreen(0x000000)
Widgets.Label("hold BtnA for REPL", 5, 10, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu18)
for _ in range(30):
    M5.update()
    if M5.BtnA.isPressed():
        Widgets.fillScreen(0x000000)
        Widgets.Label("REPL", 5, 10, 1.0, 0xFFFF00, 0x000000, Widgets.FONTS.DejaVu18)
        import sys
        sys.exit()
    time.sleep(0.1)

import network
import uasyncio as asyncio
import usocket as socket
import uselect
import uerrno
import ubinascii
import uos
import struct
import math
from machine import Pin, I2C, PWM, SoftI2C

# UIFlow firmware doesn't put /flash/lib on sys.path by default. Our flashed
# creature drivers land there (lib/*.py -> /lib/ via mpremote, which is
# /flash/lib/ at runtime), so insert it before importing.
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

# ── The Grove bus and its two tenants ───────────────────────────────────────
# NOTE: bus 1 is reserved by the M5 internal IMU (see puppyc main.py for the
# OSError(261) story). Both sensors live on bus 0; addresses don't collide.

THERMAL_ADDR = 0x32
TOF_ADDR = 0x29

i2c_grove = I2C(0, sda=Pin(9), scl=Pin(10), freq=400000)

_found = i2c_grove.scan()
print("grove: i2c scan:", [hex(a) for a in _found])

_thermal_ok = THERMAL_ADDR in _found
if _thermal_ok:
    i2c_grove.writeto_mem(THERMAL_ADDR, 0x0B, b"\x04")   # 8 Hz subpages -> ~4 full fps
    i2c_grove.writeto_mem(THERMAL_ADDR, 0x6E, b"\x00")   # arm data-ready
    print("thermal: MLX90640 unit ready at 0x32")
else:
    print("thermal: no 0x32 on grove bus!")

_tof = None
if TOF_ADDR in _found:
    try:
        from vl53l0x_nb import VL53L0X
        _tof = VL53L0X(i2c_grove, io_timeout_s=1)
        print("tof: VL53L0X ready at 0x29")
    except Exception as e:
        print("tof: init failed:", e)
else:
    print("tof: no 0x29 on grove bus!")

# ── The /warm percept state (pump writes, instincts read) ──────────────────

DELTAS = (1.5, 2.5, 4.0, 6.0)   # C above ambient; BtnA cycles
MIN_AREA = 2                     # px; reject single-pixel noise blobs

_warm = {"present": False, "area": 0, "cx": 0.0, "cy": 0.0,
         "excess_c": 0.0, "ambient_c": 0.0, "t_ms": 0}
_delta_c = DELTAS[1]
_dist_mm = None
_dist_t = 0
_draw = True


def warm():
    """Latest warm-blob percept. A warm SHAPE in MY camera frame — never a
    person, never a gaze. age_ms tells you how stale it is (thermal runs at
    ~8 subpages/s, so <300ms is fresh)."""
    d = dict(_warm)
    d["age_ms"] = time.ticks_diff(time.ticks_ms(), d.pop("t_ms"))
    return d


def read_distance_mm():
    """Latest ToF reading in millimetres, or None if the sensor isn't
    available. ~30 (very close) to ~2000 (out of range); 0 = no echo."""
    return _dist_mm


def set_warm_delta(c):
    global _delta_c
    _delta_c = float(c)


def set_thermal_draw(on):
    global _draw
    _draw = bool(on)
    if _draw:
        _layout()


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


# ── Display: pump-owned layout ─────────────────────────────────────────────

SCALE = 4
IMG_X = 3
IMG_Y = 40


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

W = M5.Widgets
F = W.FONTS
D = M5.Display

lbl_head = None
lbl_amb = None
lbl_blob = None
lbl_cen = None
lbl_tof = None
lbl_fps = None
_head_text = "booting"


def _layout():
    global lbl_head, lbl_amb, lbl_blob, lbl_cen, lbl_tof, lbl_fps
    W.fillScreen(0x000000)
    W.Label("robot_dog 2_perc", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu12)
    lbl_head = W.Label(_head_text, 4, 20, 1.0, 0x66ff66, 0x000000, F.DejaVu12)
    lbl_amb  = W.Label("", 4, 144, 1.0, 0xffffff, 0x000000, F.DejaVu12)
    lbl_blob = W.Label("", 4, 160, 1.0, 0xff8844, 0x000000, F.DejaVu12)
    lbl_cen  = W.Label("", 4, 176, 1.0, 0x44ffff, 0x000000, F.DejaVu12)
    lbl_tof  = W.Label("", 4, 192, 1.0, 0x8888ff, 0x000000, F.DejaVu12)
    lbl_fps  = W.Label("", 4, 210, 1.0, 0xaaaaaa, 0x000000, F.DejaVu12)


def _head(text):
    global _head_text
    _head_text = text
    if _draw and lbl_head:
        lbl_head.setText(text)


# ── The perception pump ────────────────────────────────────────────────────

async def perception_pump():
    global _warm, _delta_c, _dist_mm, _dist_t

    _layout()
    if not _thermal_ok:
        if lbl_amb:
            lbl_amb.setText("no thermal 0x32!")

    frame = [0] * 768        # persistent full frame, half refreshed per subpage
    have = [False, False]    # which subpages have arrived at least once
    disp_lo = None
    disp_hi = None
    subpages = 0
    last_stat = time.ticks_ms()
    blob = None
    med = 0

    while True:
        now = time.ticks_ms()

        if M5.BtnA.wasPressed():
            # cycle to the next delta above the current one (instincts may
            # have set an off-menu value; this snaps back onto the menu)
            for d in DELTAS:
                if d > _delta_c + 0.01:
                    set_warm_delta(d)
                    break
            else:
                set_warm_delta(DELTAS[0])

        # ── ToF: non-blocking single-shot cycle, throttled to ~10 Hz ──────
        if _tof:
            try:
                if _tof.range_started:
                    if _tof.reading_available():
                        _dist_mm = _tof.get_range_value()
                        _dist_t = now
                elif time.ticks_diff(now, _dist_t) > 100:
                    _tof.start_range_request()
            except Exception as e:
                print("tof: cycle error:", e)

        if not _thermal_ok:
            await asyncio.sleep_ms(100)
            continue

        try:
            ctrl = i2c_grove.readfrom_mem(THERMAL_ADDR, 0x6E, 2)
            if not (ctrl[0] & 0x01):
                await asyncio.sleep_ms(5)
                continue
            subpage = ctrl[1] & 1

            ov = struct.unpack("<HHHBBHBBHBB",
                               i2c_grove.readfrom_mem(THERMAL_ADDR, 0x70, 16))
            med, lo_raw, hi_raw = ov[0], ov[5], ov[8]

            buf = i2c_grove.readfrom_mem(THERMAL_ADDR, 0x80, 768)
            i2c_grove.writeto_mem(THERMAL_ADDR, 0x6E, b"\x00")
        except Exception as e:
            print("thermal: read error:", e)
            await asyncio.sleep_ms(200)
            continue

        vals = struct.unpack("<384H", buf)
        for i in range(384):
            y = i >> 4
            frame[(y << 5) + ((i & 15) << 1) + ((y & 1) != subpage)] = vals[i]
        have[subpage] = True

        # ── image (autoscaled, same as test_warmth) ────────────────────────
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
        if _draw:
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

        # give the ws/heartbeat tasks a slice after the draw burst
        await asyncio.sleep_ms(0)

        # ── blob extraction (needs both subpages at least once) ────────────
        if have[0] and have[1]:
            thr_raw = med + int(_delta_c * 128)
            blob = largest_blob(frame, thr_raw, med)

        if blob:
            area, cx, cy, mexc, x0, y0, x1, y1 = blob
            _warm = {"present": True, "area": area, "cx": cx, "cy": cy,
                     "excess_c": mexc, "ambient_c": celsius(med), "t_ms": now}
            if _draw:
                D.drawRect(IMG_X + x0 * SCALE, IMG_Y + y0 * SCALE,
                           (x1 - x0 + 1) * SCALE, (y1 - y0 + 1) * SCALE, 0xFFFFFF)
                D.fillRect(IMG_X + int(cx * SCALE) + SCALE // 2 - 1,
                           IMG_Y + int(cy * SCALE) + SCALE // 2 - 1, 3, 3, 0x00FFFF)
        elif have[0] and have[1]:
            _warm = {"present": False, "area": 0, "cx": 0.0, "cy": 0.0,
                     "excess_c": 0.0, "ambient_c": celsius(med), "t_ms": now}

        subpages += 1
        dt = time.ticks_diff(now, last_stat)
        if dt >= 1000:
            fps = subpages * 500.0 / dt
            mm = _dist_mm if _dist_mm is not None else -1
            if _draw:
                lbl_amb.setText("amb {:4.1f}C  d {:.1f}".format(celsius(med), _delta_c))
                if blob:
                    lbl_blob.setText("blob {:3d}px  +{:.1f}C".format(blob[0], blob[3]))
                    lbl_cen.setText("at {:4.1f},{:4.1f}".format(blob[1], blob[2]))
                else:
                    lbl_blob.setText("no warm shape")
                    lbl_cen.setText("")
                lbl_tof.setText("tof {} mm".format(mm) if mm >= 0 else "tof --")
                lbl_fps.setText("{:.1f} fps".format(fps))
            if blob:
                print("perc: amb={:.1f} d={:.1f} area={} exc={:.1f} cen=({:.1f},{:.1f}) tof={} fps={:.1f}".format(
                    celsius(med), _delta_c, blob[0], blob[3], blob[1], blob[2], mm, fps))
            else:
                print("perc: amb={:.1f} d={:.1f} no-blob tof={} fps={:.1f}".format(
                    celsius(med), _delta_c, mm, fps))
            subpages = 0
            last_stat = now

# ── Config ─────────────────────────────────────────────────────────────────

try:
    import wifi as _w
    MODE = _w.MODE
    AP_SSID, AP_PASS, AP_CHANNEL = _w.AP_SSID, _w.AP_PASS, _w.AP_CHANNEL
    STA_SSID, STA_PASS = _w.STA_SSID, _w.STA_PASS
    SPINE_HOST_AP, SPINE_HOST_STA = _w.SPINE_HOST_AP, _w.SPINE_HOST_STA
    SPINE_PORT = _w.SPINE_PORT
    CONFIG_SOURCE = "wifi.py"
except ImportError:
    MODE = "sta"
    AP_SSID, AP_PASS, AP_CHANNEL = "robot_dog", "puppy123", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

HEARTBEAT_INTERVAL = 5

# ── WiFi ───────────────────────────────────────────────────────────────────

def start_ap(ssid, password, channel=6, timeout_s=5):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    if password:
        ap.config(essid=ssid, password=password, channel=channel)
    else:
        ap.config(essid=ssid, channel=channel)
    for _ in range(timeout_s * 10):
        if ap.active():
            break
        time.sleep(0.1)
    if not ap.active():
        raise OSError("ap: failed to start")
    ip = ap.ifconfig()[0]
    print("ap: ssid={} ip={}".format(ssid, ip))
    return ip


def connect_sta(ssid, password, timeout_s=10):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("sta: connecting to", ssid)
        wlan.connect(ssid, password)
        for _ in range(timeout_s * 10):
            if wlan.isconnected():
                break
            time.sleep(0.1)
    if not wlan.isconnected():
        raise OSError("sta: failed to connect to {}".format(ssid))
    ip = wlan.ifconfig()[0]
    print("sta: connected, ip =", ip)
    return ip

# ── Minimal WebSocket client ───────────────────────────────────────────────

class WebSocket:
    def __init__(self, sock):
        self._sock = sock
        self._sock.setblocking(False)
        self._reader = asyncio.StreamReader(self._sock)

    @staticmethod
    async def connect(host, port, path="/", timeout_ms=5000):
        # ASYNC connect: the blocking sock.connect() of the parent runtimes
        # stalls the WHOLE asyncio loop for seconds per attempt when the
        # spine is unreachable — in this stage that freezes the perception
        # pump every reconnect cycle (diagnosed 2026-07-18: display frozen
        # for seconds, alive only during the 3s between-retries sleep).
        # Non-blocking connect + poll keeps the pump breathing.
        ai = socket.getaddrinfo(host, port)[0]   # blocking, but SPINE_HOST
        sock = socket.socket(ai[0], socket.SOCK_STREAM)   # is an IP literal
        sock.setblocking(False)
        try:
            sock.connect(ai[-1])
        except OSError as e:
            if e.args and e.args[0] != uerrno.EINPROGRESS:
                sock.close()
                raise
        poller = uselect.poll()
        poller.register(sock, uselect.POLLOUT)
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        try:
            while True:
                ev = poller.poll(0)
                if ev:
                    if ev[0][1] & (uselect.POLLERR | uselect.POLLHUP):
                        raise OSError("ws: connect refused")
                    break   # writable = connected
                if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                    raise OSError("ws: connect timeout")
                await asyncio.sleep_ms(50)
        except BaseException:
            poller.unregister(sock)
            sock.close()
            raise
        poller.unregister(sock)

        key = ubinascii.b2a_base64(uos.urandom(16)).strip()
        request = (
            "GET {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).format(path, host, port, key.decode())

        try:
            req = request.encode()
            sent = 0
            while sent < len(req):
                try:
                    n = sock.send(req[sent:])
                    sent += n if n else 0
                except OSError as e:
                    if e.args and e.args[0] != uerrno.EAGAIN:
                        raise
                    await asyncio.sleep_ms(10)

            # Read the handshake response ONE byte at a time: a bulk recv can
            # swallow the start of the first WebSocket frame when the server
            # sends immediately (the tuner does) and it coalesces with the
            # response in one TCP segment — after that every frame header is
            # misparsed and the payload text execs as shredded "instincts"
            # (diagnosed 2026-07-13: CRASH storms of 32/110/116-byte shards —
            # ASCII codes of payload characters read as frame lengths).
            # Non-blocking here too: EAGAIN = no byte yet, yield and retry.
            response = b""
            while b"\r\n\r\n" not in response:
                if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                    raise OSError("ws: handshake timeout")
                try:
                    chunk = sock.recv(1)
                except OSError as e:
                    if e.args and e.args[0] != uerrno.EAGAIN:
                        raise
                    await asyncio.sleep_ms(20)
                    continue
                if not chunk:
                    raise OSError("ws: handshake failed (closed)")
                response += chunk
            if b"101" not in response.split(b"\r\n")[0]:
                raise OSError("ws: handshake failed: " + response[:80].decode())
        except BaseException:
            sock.close()
            raise
        return WebSocket(sock)

    async def recv(self):
        header = await self._reader.readexactly(2)
        opcode = header[0] & 0x0F
        if opcode == 0x8:
            return None
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await self._reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self._reader.readexactly(8), "big")
        payload = await self._reader.readexactly(length)
        if opcode == 0x1:
            return payload.decode()
        if opcode == 0x9:
            self._send_frame(0xA, payload, mask=True)
            return await self.recv()
        return payload

    def send(self, text):
        data = text.encode() if isinstance(text, str) else text
        self._send_frame(0x1, data, mask=True)

    def _send_frame(self, opcode, data, mask=False):
        frame = bytearray()
        frame.append(0x80 | opcode)
        length = len(data)
        mask_bit = 0x80 if mask else 0
        if length < 126:
            frame.append(mask_bit | length)
        elif length < 65536:
            frame.append(mask_bit | 126)
            frame += length.to_bytes(2, "big")
        else:
            frame.append(mask_bit | 127)
            frame += length.to_bytes(8, "big")
        if mask:
            mask_key = uos.urandom(4)
            frame += mask_key
            masked = bytearray(len(data))
            for i in range(len(data)):
                masked[i] = data[i] ^ mask_key[i % 4]
            frame += masked
        else:
            frame += data
        self._sock.setblocking(True)
        self._sock.send(frame)
        self._sock.setblocking(False)

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except:
            pass
        try:
            self._sock.close()
        except:
            pass

# ── Instinct runtime ───────────────────────────────────────────────────────

ws = None
current_task = None

def send(msg):
    try:
        if ws:
            ws.send(str(msg))
    except Exception as e:
        print("send: error:", e)

INSTINCT_ENV = {
    "send": send,
    "asyncio": asyncio,
    "Pin": Pin,
    "I2C": I2C,
    "PWM": PWM,
    "SoftI2C": SoftI2C,
    "time": time,
    "struct": struct,
    "math": math,
    "M5": M5,
    "Imu": Imu,
    "Speaker": Speaker,
    "Widgets": Widgets,
    # perception body API (pump-maintained percepts; don't touch the bus)
    "warm": warm,
    "read_distance_mm": read_distance_mm,
    "set_warm_delta": set_warm_delta,
    "set_thermal_draw": set_thermal_draw,
    "i2c_grove": i2c_grove,
    "THERMAL_ADDR": THERMAL_ADDR,
}

DEFAULT_INSTINCT = """
async def run():
    while True:
        w = warm()
        send("idle warm_present={} tof={}".format(w["present"], read_distance_mm()))
        await asyncio.sleep(5)
"""

async def run_instinct(code):
    env = dict(INSTINCT_ENV)
    try:
        exec(code, env)
    except Exception as e:
        send("CRASH:exec:{}".format(e))
        print("instinct: exec error:", e)
        return
    if "run" not in env:
        send("CRASH:no run() defined")
        return
    try:
        await env["run"]()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        send("CRASH:{}".format(e))
        print("instinct: crash:", e)


async def swap_instinct(code):
    global current_task
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
    current_task = asyncio.create_task(run_instinct(code))
    print("instinct: swapped ({} bytes)".format(len(code)))


last_session_id = None

async def session_start_cleanup():
    global current_task
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
        current_task = None
    # Reclaim the display for the pump — an instinct may have taken it.
    set_thermal_draw(True)
    try:
        Speaker.end()
    except Exception:
        pass
    print("session: cleaned up")


async def heartbeat():
    while True:
        M5.update()
        await asyncio.sleep(0.05)
        if (time.ticks_ms() // 1000) % HEARTBEAT_INTERVAL == 0:
            try:
                if ws:
                    ws.send("HEARTBEAT")
            except:
                pass


async def ws_listener():
    global ws, last_session_id
    print("ws: connecting to {}:{}".format(SPINE_HOST, SPINE_PORT))
    ws = await WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    _head("spine ok  " + SPINE_HOST)
    while True:
        try:
            msg = await ws.recv()
        except Exception as e:
            print("ws: recv error:", e)
            break
        if msg is None:
            print("ws: closed by server")
            break
        if msg.startswith("SESSION:"):
            sid = msg[len("SESSION:"):]
            if last_session_id is not None and last_session_id != sid:
                await session_start_cleanup()
            last_session_id = sid
            print("session: {}".format(sid))
            continue
        await swap_instinct(msg)


async def main():
    asyncio.create_task(perception_pump())
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        _head("no spine")
        await asyncio.sleep(3)


# ── Entry point ────────────────────────────────────────────────────────────
# WiFi failure is NON-FATAL: this stage exists to iterate on perception, and
# the display must come up with or without a network. The ws reconnect loop
# keeps retrying in the background (STA stays active, so a late-arriving
# network still gets picked up).

if MODE == "ap":
    SPINE_HOST = SPINE_HOST_AP
    try:
        start_ap(AP_SSID, AP_PASS, AP_CHANNEL)
        _head("ap " + AP_SSID)
    except Exception as e:
        print("ap: failed:", e)
        _head("ap failed")
elif MODE == "sta":
    SPINE_HOST = SPINE_HOST_STA
    try:
        connect_sta(STA_SSID, STA_PASS)
        _head("sta " + STA_SSID)
    except Exception as e:
        print("sta: failed (continuing offline):", e)
        _head("offline")
else:
    raise ValueError("MODE must be 'ap' or 'sta'")

asyncio.run(main())
