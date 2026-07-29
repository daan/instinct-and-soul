"""
main.py — M5StickS3 + PuppyC HAT runtime (robot_dog stage 1_action).

Forked verbatim from creatures/puppyc/main.py with one repair: the WS
handshake over-read fix from kata_master (byte-at-a-time handshake read —
see the comment at the recv site).

Boots M5 hardware, brings up WiFi, opens a WebSocket to the spine, and
hot-swaps instinct coroutines without rebooting. Forked from sticks3/main.py;
key differences:

  - GPIO0 is I²C SCL to the PuppyC HAT, NOT a vibration motor. The sticks3
    PWM cleanup on GPIO0 is removed.
  - A SoftI2C bus to the hat is established at boot and exposed to instincts
    as `i2c_hat`.
  - Per-leg trim (direction + offset) lives here, in the runtime, so soul-
    generated instincts cannot accidentally invert the calibration.
  - `set_leg`, `set_all`, `center_all`, FL/FR/BL/BR are pre-imported into
    instinct scope. Instincts should use these instead of writing raw I²C.
  - On session cleanup, all legs are centred (rather than the sticks3 vibe
    motor being killed).
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
import ubinascii
import uos
import struct
import math
from machine import Pin, I2C, PWM, SoftI2C

# ── PuppyC bus + helpers ────────────────────────────────────────────────────

PUPPYC_ADDR = 0x38
FL, FR, BL, BR = 0, 1, 2, 3
CENTER = 90

# Per-leg trim: (direction, offset). direction +1 normal, -1 flipped.
# Calibrated so set_leg(leg, target>90) swings the leg toward the nose.
# Direction is a wiring fact and stays in source. Offsets are per-puppy
# physical calibration and are overlaid from /flash/calibration.json (written
# by the autotrim recipe).
TRIM = {
    FL: (-1, 0),
    FR: (+1, 0),
    BL: (-1, 0),
    BR: (+1, 0),
}

try:
    import json as _json
    with open("/flash/calibration.json") as _f:
        _cal = _json.load(_f)
    for _name, _leg in (("FL", FL), ("FR", FR), ("BL", BL), ("BR", BR)):
        if _name in _cal:
            _dir, _ = TRIM[_leg]
            TRIM[_leg] = (_dir, int(_cal[_name]))
    print("calibration: loaded", _cal)
except OSError:
    print("calibration: no calibration.json (using defaults)")
except Exception as _e:
    print("calibration: load failed:", _e)

i2c_hat = SoftI2C(scl=Pin(0), sda=Pin(8), freq=100000)


def _write_servo(channel, angle):
    angle = max(0, min(180, int(angle)))
    try:
        i2c_hat.writeto_mem(PUPPYC_ADDR, channel, bytes([angle]))
    except Exception as e:
        print("puppyc: i2c write error ch={} ang={} err={}".format(channel, angle, e))


def set_leg(leg, target):
    direction, offset = TRIM[leg]
    _write_servo(leg, CENTER + direction * (target - CENTER) + offset)


def set_all(fl, fr, bl, br):
    set_leg(FL, fl)
    set_leg(FR, fr)
    set_leg(BL, bl)
    set_leg(BR, br)


def center_all():
    set_all(CENTER, CENTER, CENTER, CENTER)


# Centre the legs early — covers power-on hold + post-flash junk.
center_all()

# ── ToF (VL53L0X on hardware I²C bus 0, Grove pins) ────────────────────────
# NOTE: bus 1 is reserved by the M5 internal IMU. Sharing it (e.g. I2C(1) on
# Grove pins 9/10) lets ToF init and the first read succeed, but Imu.getAccel()
# leaves the peripheral in a state that makes the next ToF transaction raise
# OSError(261,). Keep ToF on bus 0.

# UIFlow firmware doesn't put /flash/lib on sys.path by default. Our flashed
# creature drivers land there (creatures/puppyc/lib/*.py → /lib/ via mpremote,
# which is /flash/lib/ at runtime), so we insert it manually before importing.
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

try:
    from vl53l0x_nb import VL53L0X
    _tof_i2c = I2C(0, sda=Pin(9), scl=Pin(10), freq=400000)
    _tof = VL53L0X(_tof_i2c, io_timeout_s=1)
    print("tof: VL53L0X ready on I2C(0) sda=9 scl=10")
except Exception as e:
    _tof = None
    print("tof: init failed:", e)


def read_distance_mm():
    """Latest ToF reading in millimetres, or None if the sensor isn't available.
    Typical range ~30 (very close) to ~2000 (out of range). 0 from the sensor
    means "no echo / blocked"; we pass that through as 0."""
    if _tof is None:
        return None
    try:
        return _tof.range
    except Exception:
        return None


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
    AP_SSID, AP_PASS, AP_CHANNEL = "puppy", "puppy123", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

HEARTBEAT_INTERVAL = 5

# ── Display helper ─────────────────────────────────────────────────────────

def show(lines):
    Widgets.fillScreen(0x000000)
    y = 10
    for line in lines:
        Widgets.Label(line, 5, y, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu18)
        y += 24

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
    def connect(host, port, path="/"):
        ai = socket.getaddrinfo(host, port)[0]
        sock = socket.socket(ai[0], socket.SOCK_STREAM)
        sock.connect(ai[-1])

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
        sock.send(request.encode())

        # Read the handshake response ONE byte at a time: a bulk recv can
        # swallow the start of the first WebSocket frame when the server
        # sends immediately (the tuner does) and it coalesces with the
        # response in one TCP segment — after that every frame header is
        # misparsed and the payload text execs as shredded "instincts"
        # (diagnosed 2026-07-13: CRASH storms of 32/110/116-byte shards —
        # ASCII codes of payload characters read as frame lengths).
        response = b""
        sock.setblocking(True)
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(1)
            if not chunk:
                raise OSError("ws: handshake failed (closed)")
            response += chunk
        if b"101" not in response.split(b"\r\n")[0]:
            raise OSError("ws: handshake failed: " + response[:80].decode())
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

# ── The typed journal ──────────────────────────────────────────────────────
# One stream, every entry naming its own kind, so the soul can tell its own
# acts from the body's reports. LOG:/REFLECTION:/CRASH: are written here;
# UPDATE:/NO UPDATE:/FAILED REFLECTION:/OPERATOR: are written by the spine.
_MARKERS = ("LOG:", "REFLECTION:", "CRASH:", "UPDATE:", "NO UPDATE:",
            "FAILED REFLECTION:", "OPERATOR:", "BOOT:", "MEM:", "IV:")


def _typed(msg):
    """Tag an entry LOG: unless it already declares its type."""
    msg = str(msg)
    for m in _MARKERS:
        if msg.startswith(m):
            return msg
    return "LOG: " + msg


def send(msg):
    try:
        if ws:
            ws.send(_typed(msg))
    except Exception as e:
        print("send: error:", e)

def reflect(reason):
    """Ask the soul to think, and say WHY. Journalling never does this —
    send() only writes to the record; this is the one call that summons a
    reflection. Say what changed or what you cannot resolve."""
    send("REFLECTION: " + str(reason))


INSTINCT_ENV = {
    "send": send,
    "reflect": reflect,
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
    # puppyc body API
    "i2c_hat": i2c_hat,
    "set_leg": set_leg,
    "set_all": set_all,
    "center_all": center_all,
    "FL": FL,
    "FR": FR,
    "BL": BL,
    "BR": BR,
    "PUPPYC_ADDR": PUPPYC_ADDR,
    "TRIM": TRIM,
    # ToF sensor (None until first successful init; returns None on failure)
    "read_distance_mm": read_distance_mm,
    "tof": _tof,
}

DEFAULT_INSTINCT = """
async def run():
    center_all()
    while True:
        send("state=idle")
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
    # Always start a fresh instinct from a known leg pose.
    center_all()
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
    Widgets.fillScreen(0x000000)
    center_all()
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
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
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
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        print("ws: reconnect in 3s")
        await asyncio.sleep(3)


# ── Entry point ────────────────────────────────────────────────────────────

if MODE == "ap":
    SPINE_HOST = SPINE_HOST_AP
    show(["mode: AP", "ssid: " + AP_SSID, "starting..."])
    try:
        ip = start_ap(AP_SSID, AP_PASS, AP_CHANNEL)
    except Exception as e:
        show(["AP failed:", str(e)])
        raise
    show(["AP: " + AP_SSID, "ip: " + ip, "spine: " + SPINE_HOST])
elif MODE == "sta":
    SPINE_HOST = SPINE_HOST_STA
    show(["mode: STA", "ssid: " + STA_SSID, "connecting..."])
    try:
        ip = connect_sta(STA_SSID, STA_PASS)
    except Exception as e:
        show(["STA failed:", str(e)])
        raise
    show(["STA: " + STA_SSID, "ip: " + ip, "spine: " + SPINE_HOST])
else:
    show(["bad MODE: " + str(MODE)])
    raise ValueError("MODE must be 'ap' or 'sta'")

asyncio.run(main())
