"""
main.py — M5Stack CORES3 runtime.

Boots M5 hardware, brings up WiFi (AP or STA), opens a WebSocket to
the spine, and runs an asyncio loop with three tasks:
  1. Heartbeat: M5.update() tick + periodic HEARTBEAT to spine
  2. WebSocket listener: receives instinct code and hot-swaps it
  3. Instinct: the soul's async def run() coroutine

Incoming WS messages are treated as instinct code to exec.
The code must define an async def run() coroutine.

Runtime provides to instinct code:
  send(msg), asyncio, Pin, I2C, PWM, time, struct, math,
  M5, Imu, Speaker, Widgets, Als, Hr

Hr is a BLE heart-rate sensor. Set HR_MAC below to your sensor's MAC.
"""

import M5
from M5 import *
import time

M5.begin()

# Make sure Grove Port A vibration pin (GPIO1) isn't carrying over from a prior run.
from machine import Pin, PWM
_p = PWM(Pin(1), freq=5000, duty=0)
_p.deinit()
Pin(1, Pin.OUT, value=0)

# Bail-out: tap the touchscreen during the first 3s after boot to drop to REPL.
# Lets us recover when main.py would otherwise grab the asyncio loop.
Widgets.fillScreen(0x000000)
Widgets.Label("tap screen for REPL", 8, 10, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu24)
for _ in range(30):
    M5.update()
    if M5.Touch.getCount() > 0:
        Widgets.fillScreen(0x000000)
        Widgets.Label("REPL", 8, 10, 1.0, 0xFFFF00, 0x000000, Widgets.FONTS.DejaVu24)
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
import aioble
import bluetooth as _bt

# ── Config ──────────────────────────────────────────────────────────────────
# Prefer wifi.py if flashed alongside main.py; otherwise use defaults below.
# SPINE_HOST_* is the laptop's IP (manual on AP, static on STA).

CREATURE_NAME = "ble-example"

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
    AP_SSID, AP_PASS, AP_CHANNEL = "cores3", "cores3123", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

HEARTBEAT_INTERVAL = 5  # seconds

# ── Display helper ─────────────────────────────────────────────────────────

def show(lines):
    Widgets.fillScreen(0x000000)
    y = 10
    for line in lines:
        Widgets.Label(line, 8, y, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu24)
        y += 32

# ── WiFi ────────────────────────────────────────────────────────────────────

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

# ── Minimal WebSocket client (text frames, no TLS) ─────────────────────────

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

def send(msg):
    try:
        if ws:
            ws.send(str(msg))
    except Exception as e:
        print("send: error:", e)

# ── BLE heart-rate sensor ──────────────────────────────────────────────────
# Set HR_MAC to your sensor's BLE MAC address. Standard Bluetooth heart-rate
# profile (service 0x180D, measurement characteristic 0x2A37).
HR_MAC = "00:00:00:00:00:00"
HR_SERVICE_UUID = _bt.UUID(0x180D)
HR_MEASUREMENT_UUID = _bt.UUID(0x2A37)


class Hr:
    bpm = None
    connected = False

    @staticmethod
    def get():
        return Hr.bpm if Hr.connected else None


INSTINCT_ENV = {
    "send": send,
    "asyncio": asyncio,
    "Pin": Pin,
    "I2C": __import__("machine").I2C,
    "PWM": PWM,
    "time": time,
    "struct": struct,
    "math": math,
    "M5": M5,
    "Imu": Imu,
    "Speaker": Speaker,
    "Widgets": Widgets,
    "Als": Als,
    "Hr": Hr,
}

DEFAULT_INSTINCT = """
async def run():
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
    current_task = asyncio.create_task(run_instinct(code))
    print("instinct: swapped ({} bytes)".format(len(code)))


last_session_id = None

async def session_start_cleanup():
    """Called when spine reports a new session. Stop the running instinct
    and reset visible/audible hardware so the next swap_instinct starts clean."""
    global current_task
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
        current_task = None
    Widgets.fillScreen(0x000000)
    _p = PWM(Pin(1), freq=5000, duty=0)
    _p.deinit()
    Pin(1, Pin.OUT, value=0)
    try:
        Speaker.stop()
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


async def hr_loop():
    target = bytes(int(b, 16) for b in HR_MAC.split(":"))
    while True:
        Hr.connected = False
        Hr.bpm = None
        try:
            print("hr: scanning for", HR_MAC)
            dev = None
            async with aioble.scan(duration_ms=10_000, interval_us=30_000, window_us=30_000, active=True) as scanner:
                async for r in scanner:
                    if bytes(r.device.addr) == target:
                        dev = r.device
                        break
            if not dev:
                await asyncio.sleep(5)
                continue
            print("hr: connecting")
            conn = await dev.connect(timeout_ms=10_000)
            try:
                svc = await conn.service(HR_SERVICE_UUID)
                ch = await svc.characteristic(HR_MEASUREMENT_UUID)
                await ch.subscribe(notify=True)
                Hr.connected = True
                print("hr: connected")
                while True:
                    data = await ch.notified()
                    flags = data[0]
                    if flags & 0x01:
                        Hr.bpm = int.from_bytes(data[1:3], "little")
                    else:
                        Hr.bpm = data[1]
            finally:
                Hr.connected = False
                Hr.bpm = None
                try:
                    await conn.disconnect()
                except Exception:
                    pass
                print("hr: disconnected")
        except Exception as e:
            print("hr: error:", e)
            await asyncio.sleep(5)


async def ws_listener():
    global ws, last_session_id
    print("ws: connecting to {}:{}".format(SPINE_HOST, SPINE_PORT))
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    ws.send("HELLO:" + CREATURE_NAME)
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
    asyncio.create_task(hr_loop())
    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        print("ws: reconnect in 3s")
        await asyncio.sleep(3)


# ── Entry point ─────────────────────────────────────────────────────────────

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
