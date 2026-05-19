"""
boot.py — fixed runtime for the pebble.

Connects to WiFi, opens a WebSocket to the spine, and runs
an asyncio loop with three tasks:
  1. Heartbeat: sends HEARTBEAT every 5 seconds
  2. WebSocket listener: receives new instinct code and hot-swaps
  3. Instinct: the soul's async def run() coroutine

The spine sends plain strings — the full instinct code, no prefix.
The code must define an async def run() coroutine.

The runtime provides the following in the instinct's exec scope:
  send(msg), asyncio, Pin, I2C, PWM, time, struct, math
"""

import network
import uasyncio as asyncio
import usocket as socket
import ubinascii
import uos
import time
import struct
import math
from machine import Pin, I2C, PWM

# ── Config ──────────────────────────────────────────────────────────────────
# Prefer wifi.py if flashed alongside main.py; otherwise use defaults below.
# The pebble only does STA, so AP_* fields in wifi.py are ignored here.

try:
    import wifi as _w
    WIFI_SSID, WIFI_PASS = _w.STA_SSID, _w.STA_PASS
    SPINE_HOST = _w.SPINE_HOST_STA
    SPINE_PORT = _w.SPINE_PORT
    CONFIG_SOURCE = "wifi.py"
except ImportError:
    WIFI_SSID = "아저씨"
    WIFI_PASS = "d3im-raqfeo-usd12"
    SPINE_HOST = "10.0.0.100"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

HEARTBEAT_INTERVAL = 5  # seconds

# ── Kill motors immediately ─────────────────────────────────────────────────

Pin(9, Pin.OUT, value=0)
Pin(10, Pin.OUT, value=0)

# ── Minimal WebSocket client (text frames only, no TLS) ────────────────────

class WebSocket:
    """Bare-bones WebSocket client for MicroPython.
    Supports text send/recv and close. No fragmentation, no TLS."""

    def __init__(self, sock):
        self._sock = sock
        self._sock.setblocking(False)
        self._reader = asyncio.StreamReader(self._sock)

    @staticmethod
    def connect(host, port, path="/"):
        """Perform HTTP upgrade handshake, return WebSocket instance."""
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
            chunk = sock.recv(256)
            if not chunk:
                raise OSError("WebSocket handshake failed: connection closed")
            response += chunk

        if b"101" not in response.split(b"\r\n")[0]:
            raise OSError("WebSocket handshake failed: " + response[:80].decode())

        return WebSocket(sock)

    async def recv(self):
        """Read one text frame. Returns string or None on close."""
        header = await self._reader.readexactly(2)
        opcode = header[0] & 0x0F
        if opcode == 0x8:
            return None
        length = header[1] & 0x7F

        if length == 126:
            ext = await self._reader.readexactly(2)
            length = int.from_bytes(ext, "big")
        elif length == 127:
            ext = await self._reader.readexactly(8)
            length = int.from_bytes(ext, "big")

        payload = await self._reader.readexactly(length)

        if opcode == 0x1:
            return payload.decode()
        if opcode == 0x9:
            self._send_frame(0xA, payload, mask=True)
            return await self.recv()
        return payload

    def send(self, text):
        """Send a masked text frame."""
        data = text.encode() if isinstance(text, str) else text
        self._send_frame(0x1, data, mask=True)

    def _send_frame(self, opcode, data, mask=False):
        """Build and send a WebSocket frame."""
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


# ── WiFi ────────────────────────────────────────────────────────────────────

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("wifi: connecting to", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(100):
            if wlan.isconnected():
                break
            time.sleep(0.1)
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("wifi: connected, ip =", ip)
        return ip
    else:
        raise OSError("wifi: failed to connect")


# ── Send ────────────────────────────────────────────────────────────────────

def send(msg):
    """Send a string to the spine. Available to instinct code."""
    try:
        if ws:
            ws.send(str(msg))
    except Exception as e:
        print("send: error:", e)


# ── Instinct management ────────────────────────────────────────────────────

current_task = None
ws = None

# The exec environment for instinct code
INSTINCT_ENV = {
    "send": send,
    "asyncio": asyncio,
    "Pin": Pin,
    "I2C": I2C,
    "PWM": PWM,
    "time": time,
    "struct": struct,
    "math": math,
}


async def run_instinct(code):
    """Exec instinct code and run its run() coroutine, catching crashes."""
    env = dict(INSTINCT_ENV)
    try:
        exec(code, env)
    except Exception as e:
        send("CRASH:exec:{}".format(e))
        print("instinct: exec error:", e)
        return

    if "run" not in env:
        send("CRASH:no run() defined")
        print("instinct: code must define async def run()")
        return

    try:
        await env["run"]()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        send("CRASH:{}".format(e))
        print("instinct: crash:", e)


async def swap_instinct(code):
    """Cancel current instinct and start new one."""
    global current_task

    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass

    current_task = asyncio.create_task(run_instinct(code))
    print("instinct: swapped ({} bytes)".format(len(code)))


# ── Default instinct: idle, waiting for soul ────────────────────────────────

DEFAULT_INSTINCT = """
async def run():
    while True:
        send("state=idle")
        await asyncio.sleep(5)
"""


# ── Heartbeat ───────────────────────────────────────────────────────────────

async def heartbeat():
    """Send periodic heartbeat to spine."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            if ws:
                ws.send("HEARTBEAT")
        except:
            pass


# ── WebSocket listener ──────────────────────────────────────────────────────

async def ws_listener():
    """Listen for instinct code from spine, hot-swap on arrival."""
    global ws

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
            print("ws: connection closed by server")
            break

        # All incoming messages are instinct code
        await swap_instinct(msg)


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())

    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        print("ws: reconnecting in 3s...")
        await asyncio.sleep(3)


# ── Entry point ─────────────────────────────────────────────────────────────

connect_wifi()
asyncio.run(main())