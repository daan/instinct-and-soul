"""
main.py — M5StickS3 "kata_master" runtime (IMU + Grove SAM2695 GM synth).

Same spine as the midi_dancer runtime — boots M5 hardware, brings up WiFi,
opens a WebSocket to the spine, and runs an asyncio loop with heartbeat +
instinct-hotswap tasks. No organ layer: sensing lives with the instinct.
KataSense (lib/kata_sense.py, validated by test_kata_parity.py) is handed
into the instinct scope and constructed THERE, with the seed's own judgment
numbers — mechanism in the library, judgment in the instinct. Detection
happens at the sensor, at full rate: WiFi stalls cannot swallow a strike.
The voice is the Unit-Synth (SAM2695) on the Grove port — MIDI over a wire,
no network in the sound path.

Runtime provides to instinct code:
  send(msg), reflect(reason), asyncio, time, struct, math, M5, Imu, Synth,
  mem (ONE plain dict, survives hot-swaps), Calc, KataSense

Device-side libraries flashed to /lib (creatures/kata_master/condition_1/lib/*.py):
  synth.py         -> Sam2695Synth  (the `Synth` voice, + pitch_bend)
  calc.py          -> Calc          (streaming signal toolkit)
  kata_sense.py    -> KataSense     (the kata sense; judgment via constructor)
  stethoscope.py   -> the bench organ stream (detached; see STETHO_HOST)
"""

import M5
from M5 import *
import time
import machine

# Why did we boot? Decisive when hunting spontaneous resets: watchdog vs
# brownout vs power-on look identical from outside (diagnosed 2026-07-13,
# board dying ~every minute of uptime).
_RESET_CAUSES = {machine.PWRON_RESET: "PWRON", machine.HARD_RESET: "HARD",
                 machine.WDT_RESET: "WDT", machine.DEEPSLEEP_RESET: "DEEPSLEEP",
                 machine.SOFT_RESET: "SOFT"}
_rc = machine.reset_cause()
print("reset cause:", _RESET_CAUSES.get(_rc, _rc))

M5.begin()
# We do NOT use the built-in Speaker here — the voice is the Grove synth.

# UIFlow firmware doesn't put /flash/lib on sys.path by default. Our flashed
# creature drivers land there (creatures/kata_master/lib/*.py -> /lib/ via
# mpremote, which is /flash/lib/ at runtime), so insert it before importing.
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

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
from machine import Pin, I2C, PWM

# ── The voice + toolkits + the kata sense ───────────────────────────────────
from synth import Sam2695Synth
from calc import Calc
from kata_sense import KataSense

try:
    # On battery some M5 boards keep the Grove 5V rail off until asked —
    # and the Unit-Synth lives on that rail.
    M5.Power.setExtOutput(True)
except Exception as e:
    print("synth: setExtOutput failed (fine on USB):", e)

SYNTH_VOLUME = 75   # GM master volume 0..127. 25 (the first office pick)
                    # proved barely audible in practice ("should be 3x as
                    # loud", 2026-07-13); 75 is the corrected room level —
                    # battery sag stayed negligible through the sweeps.
                    # Seeds' per-channel CC7 scales under this cap.

try:
    Synth = Sam2695Synth()
    Synth.master_volume(SYNTH_VOLUME)
    print("synth: SAM2695 ready on Grove UART, master vol", SYNTH_VOLUME)
except Exception as e:
    Synth = None
    print("synth: init failed:", e)

# ── mem: what an instinct carries across its own rewrites ───────────────────
#
# ONE plain dict, module scope: it outlives every hot-swap and dies with the
# power. The instinct holds the very dict this name holds, so a mutation is
# persisted the instant it happens — there is nothing to flush and nothing to
# restore, and because item assignment writes INTO the dict, even
# mem["h_moves"] = [] persists. Keys are never deleted: a rewrite that merely
# forgot one must not be able to destroy hours of accumulated history over a
# typo. Instincts declare defaults with mem.setdefault(...) at the top of
# run() — never in a loop, since the default is constructed on every call
# and discarded when the key exists.
MEM = {}
_mem_shape = None      # sorted key list at the last swap, for the diff below


def _announce_mem_shape():
    """Journal it when the set of carried keys grew since the last swap, so
    a later reflection can see WHEN its memory changed shape. Additive only:
    nothing here (or anywhere) deletes keys."""
    global _mem_shape
    keys = sorted(MEM.keys())
    if _mem_shape is not None:
        gained = [k for k in keys if k not in _mem_shape]
        if gained:
            send("LOG: my memory changed shape — gained {}".format(gained))
    _mem_shape = keys

# ── Config ──────────────────────────────────────────────────────────────────
# Prefer wifi.py if flashed alongside main.py; otherwise use defaults below.

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
    AP_SSID, AP_PASS, AP_CHANNEL = "kata", "kata1234", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

HEARTBEAT_INTERVAL = 5  # seconds

STETHO_HOST = None      # the organ stream (UDP-OSC :9001 — advisory and
                        # lossy; bench insight, never a data pipeline).
                        # "spine": arm toward SPINE_HOST at boot; an
                        # "x.x.x.x" string: toward that host; None: stay
                        # detached until the tuner's `stetho` command arms
                        # it by hand. Leave None for battery deployments —
                        # on tilt the armed probes were the largest single
                        # radio load on the body.

# ── Display helper ─────────────────────────────────────────────────────────

def show(lines):
    Widgets.fillScreen(0x000000)
    y = 10
    for line in lines:
        Widgets.Label(line, 5, y, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu18)
        y += 24

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
    "time": time,
    "struct": struct,
    "math": math,
    "M5": M5,
    "Imu": Imu,
    "Synth": Synth,
    "mem": MEM,
    "Calc": Calc,
    "KataSense": KataSense,
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
    _announce_mem_shape()
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
    # A cancelled instinct can leave notes ringing on the synth — silence them
    # before the next one starts.
    if Synth:
        try:
            Synth.all_off()
        except Exception:
            pass
    current_task = asyncio.create_task(run_instinct(code))
    print("instinct: swapped ({} bytes)".format(len(code)))


last_session_id = None

async def session_start_cleanup():
    """Called when spine reports a new session. Stop the running instinct and
    reset visible/audible hardware so the next swap_instinct starts clean."""
    global current_task
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
        current_task = None
    Widgets.fillScreen(0x000000)
    if Synth:
        try:
            Synth.all_off()
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
    # Self-report how this boot began + uptime and power state: makes
    # spontaneous PWRON resets diagnosable over wifi alone (battery
    # sessions have no serial to print to).
    try:
        ws.send("BOOT: cause={} uptime={}s vbat={}mV charging={}".format(
            _RESET_CAUSES.get(_rc, _rc), time.ticks_ms() // 1000,
            M5.Power.getBatteryVoltage(), M5.Power.isCharging()))
    except Exception:
        pass
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


def _arm_stetho():
    """Arm the organ stream at boot, per the STETHO_HOST policy. Attach
    state is RAM-only; the stethoscope module heals its own socket if the
    WLAN bounces beneath it."""
    if not STETHO_HOST:
        return
    try:
        import stethoscope
        stethoscope.attach(SPINE_HOST if STETHO_HOST == "spine" else STETHO_HOST)
    except Exception as e:
        print("stetho: arm failed:", e)


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
    # Retry forever rather than raise: a crash here makes UIFlow reboot the
    # board in a loop (re-clicking the synth every ~12 s) whenever the
    # network is down or misnamed. Patience is cheaper.
    while True:
        try:
            ip = connect_sta(STA_SSID, STA_PASS)
            break
        except Exception as e:
            show(["STA failed:", str(e)[-24:], "retrying..."])
            time.sleep(5)
    show(["STA: " + STA_SSID, "ip: " + ip, "spine: " + SPINE_HOST])
else:
    show(["bad MODE: " + str(MODE)])
    raise ValueError("MODE must be 'ap' or 'sta'")

_arm_stetho()
asyncio.run(main())
