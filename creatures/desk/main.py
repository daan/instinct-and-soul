"""
main.py — M5Stack CoreS3 "desk" runtime: a sit-stand desk with a mind.

The body sits ON the desk surface, always on USB, always connected — the
live runtime (creatures/robot-rover/2_perception lineage: journal replay,
IV/TIME handshake, mem), not the batch one. Three senses and one actuator:

  Imu           the BMI270, read by the INSTINCT — surface vibration is what
                typing and mousing look like from here (tilt condition_4's
                pattern: the sense lives in the seed, retunable by a push)
  Range         M5 Unit Ultrasonic I2C (RCWL-9620 @0x57) on Grove Port A,
                pointed at where the person's body is — owned by the pump,
                because it needs a 120 ms trigger→read wait nobody should
                have to remember
  Touch         the screen, latched here as the one explicit channel (the
                CoreS3 has no physical BtnA; its "buttons" are touch zones)
  Desk          the Linak DPG over BLE (lib/idasen.py) — or a VIRTUAL desk
                of the same shape until DESK_MAC is set below

THE ONE BODY RULE: MOVE_WHILE_PRESENT. A desk rising into a lap is the one
thing this creature must never be able to do by accident, so move_to() is
refused while Range reads someone within SAFE_MM, and a move in progress is
stopped the moment someone appears. It is a policy constant, not a law: flip
it for the "nudge" experiments the experience file sketches — knowingly.

THEIR HAND is not a separate sensor: the desk reports its height whether we
moved it or they did, and Desk.commanded() is the bit that tells the two
apart. The instinct reads height changing with commanded() False as the
paddle — the person speaking.

Runtime provides to instinct code:
  send(msg)        write a journal line (costs nothing, does NOT summon)
  reflect(reason)  ask the soul to think, and say why (the only summons)
  Range            .mm() / .age_ms() / .ok()
  Desk             .height_mm() / .speed_mms() / .moving() / .commanded()
                   / .target_mm() / .connected() / .kind() / .age_ms()
                   / .move_to(mm) / .stop() / .result()
  Touch            .pressed() / .last_s()
  mem              one dict that survives a rewrite and dies with the power
  IV               this instinct's version
  Calc             OneEuro / Running / Onset / Ring / Gate / Ema
  asyncio, time, struct, math, M5, Imu, Speaker, Widgets

Device-side libraries flashed to /lib (creatures/desk/lib/*.py):
  calc.py        -> Calc
  ultrasonic.py  -> the RCWL-9620 driver (pump only)
  idasen.py      -> BleDesk / VirtualDesk (runtime only)
"""

import M5
from M5 import *
import time
import machine

_RESET_CAUSES = {machine.PWRON_RESET: "PWRON", machine.HARD_RESET: "HARD",
                 machine.WDT_RESET: "WDT", machine.DEEPSLEEP_RESET: "DEEPSLEEP",
                 machine.SOFT_RESET: "SOFT"}
_rc = machine.reset_cause()
print("reset cause:", _RESET_CAUSES.get(_rc, _rc))

M5.begin()

# UIFlow firmware doesn't put /flash/lib on sys.path; our flashed libs land
# there (see robot-rover/2_perception/main.py for the story).
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

# Bail-out: tap the screen during the first 3 s after boot to drop to REPL.
Widgets.fillScreen(0x000000)
Widgets.Label("tap screen for REPL", 8, 10, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu24)
for _ in range(30):
    M5.update()
    if M5.Touch.getCount() > 0:
        Widgets.fillScreen(0x000000)
        Widgets.Label("REPL", 8, 10, 1.0, 0xFFFF00, 0x000000, Widgets.FONTS.DejaVu24)
        _sys.exit()
    time.sleep(0.1)

import network
import uasyncio as asyncio
import usocket as socket
import ubinascii
import uos
import struct
import math
from machine import Pin, I2C

from calc import Calc
import ultrasonic
import idasen

# ── Policy (edit HERE) ──────────────────────────────────────────────────────

DESK_MAC = None         # "EE:4D:xx:xx:xx:xx" binds the real Linak desk over
                        # BLE (find it with a BLE scanner app, or the tuner's
                        # `blescan`). None = a VIRTUAL desk: same interface,
                        # travels at 32 mm/s in software, so the seed and the
                        # tuner run with no desk in the room.
DESK_START_MM = 720     # where the virtual desk begins

MOVE_WHILE_PRESENT = False   # THE BODY RULE. False: move_to() is refused
                             # while Range reads someone nearer than SAFE_MM,
                             # and a move in progress stops when someone
                             # appears. True: the instinct decides — for
                             # nudge experiments, with a person who knows.
SAFE_MM = 1000               # "someone is at the desk" for the rule above —
                             # deliberately generous; the instinct's own
                             # PRESENT judgment is its own, and tighter

DISPLAY_MODE = "debug"  # "debug": link / height / range / act on the panel,
                        # refreshed once a second — a desk has a screen and
                        # nobody minds. "off": dark; a touch wakes a 10 s peek.

HEARTBEAT_INTERVAL = 5
RANGE_EVERY_MS = 200    # one ping every 200 ms (5 Hz) — presence is patient

# ── mem: what an instinct carries across its own rewrites ───────────────────
# ONE plain dict, module scope: it outlives every hot-swap and dies with the
# power. Item assignment writes into it; only copying a value into a local
# loses it. Declare defaults with mem.setdefault(...) at the top of run().
# On a desk that is plugged in permanently this can span weeks — which is
# exactly why the seed keeps a DAY ledger inside it and closes the day.
MEM = {}
_mem_shape = None


def _announce_mem_shape():
    global _mem_shape
    keys = sorted(MEM.keys())
    if _mem_shape is not None:
        gained = [k for k in keys if k not in _mem_shape]
        if gained:
            send("LOG: my memory changed shape — gained {}".format(gained))
    _mem_shape = keys


# ── Grove Port A: find the ultrasonic unit ──────────────────────────────────
# CoreS3 Port A is G1/G2. The docs disagree with each other about which is
# SCL, and test/CORES3/API.md was written from a PWM motor that never cared —
# so try both orders and keep the one where the sensor answers. The tuner's
# `scan` recipe shows the same picture live.

_RANGE_ADDR = ultrasonic.ADDR
i2c_a = None
_range_present = False
for _scl, _sda in ((1, 2), (2, 1)):
    try:
        _bus = I2C(0, scl=Pin(_scl), sda=Pin(_sda), freq=100000)
        _found = _bus.scan()
        print("port a (scl={} sda={}): i2c scan: {}".format(
            _scl, _sda, [hex(a) for a in _found]))
        if i2c_a is None or _found:
            i2c_a = _bus
        if _RANGE_ADDR in _found:
            _range_present = True
            print("range: RCWL-9620 found at 0x57 (scl={} sda={})".format(_scl, _sda))
            break
    except Exception as _e:
        print("port a (scl={} sda={}): {}".format(_scl, _sda, _e))
if not _range_present:
    print("range: NO ultrasonic unit on Port A — Range.mm() will be None")

# ── The senses and the actuator, in the shape of M5's own modules ───────────
# Module-level state the pump/tasks write and instincts only read.

_range = {"mm": None, "t_ms": 0, "ok": _range_present, "errors": 0}


class _Range:
    """The presence beam: millimetres to the nearest thing in front of the
    unit. 0 = no echo (nothing within ~4.5 m, or a surface the ping slid
    off); None = no sensor."""

    def mm(self):
        return _range["mm"] if _range["ok"] else None

    def age_ms(self):
        return time.ticks_diff(time.ticks_ms(), _range["t_ms"])

    def ok(self):
        return _range["ok"]


_desk = idasen.BleDesk(DESK_MAC) if DESK_MAC else idasen.VirtualDesk(DESK_START_MM)
_desk._log = print


def _someone_near():
    mm = _range["mm"]
    return _range["ok"] and mm is not None and 0 < mm < SAFE_MM


class _Desk:
    """The instinct's handle on the desk: everything idasen offers to read,
    plus move_to()/stop() filtered through the body rule."""

    def height_mm(self):
        return _desk.height_mm()

    def speed_mms(self):
        return _desk.speed_mms()

    def moving(self):
        return _desk.moving()

    def commanded(self):
        return _desk.commanded()

    def target_mm(self):
        return _desk.target_mm()

    def connected(self):
        return _desk.connected()

    def kind(self):
        return _desk.kind()

    def age_ms(self):
        return _desk.age_ms()

    def move_to(self, mm):
        """Begin travelling to mm. Returns True if the move was accepted,
        False if the desk is not connected — or, with MOVE_WHILE_PRESENT
        False, if someone is at the desk right now (the refusal is also
        journalled, so a refused move is never silent)."""
        if not MOVE_WHILE_PRESENT and _someone_near():
            send("LOG: refused to move the desk — someone is {:.0f} mm away".format(
                _range["mm"]))
            return False
        return _desk.move_to(mm)

    def stop(self):
        _desk.stop()

    def result(self):
        """The outcome of the LAST commanded move, consumed on read:
        (how, from_mm, at_mm, seconds) with how in arrived / interrupted /
        timeout / lost, or None if nothing has finished since you last
        asked."""
        r = _desk.last_result
        _desk.last_result = None
        return r


Range = _Range()
Desk = _Desk()

# ── Touch: the one explicit channel ────────────────────────────────────────
# Latched here at update()'s cadence, so a tap cannot fall between two of
# the instinct's polls and never survives a rewrite as a stale callback.
_touch_flag = False
_touch_last = None
_touch_down = False


class _Touch:
    def pressed(self):
        """True once per tap, consumed on read."""
        global _touch_flag
        f = _touch_flag
        _touch_flag = False
        return f

    def last_s(self):
        """Seconds since the last tap, or None if none since power-on.
        Not consumed."""
        if _touch_last is None:
            return None
        return max(0.0, time.ticks_diff(time.ticks_ms(), _touch_last) / 1000.0)


Touch = _Touch()


def _poll_touch():
    global _touch_flag, _touch_last, _touch_down
    try:
        down = M5.Touch.getCount() > 0
    except Exception:
        return
    if down and not _touch_down:
        _touch_flag = True
        _touch_last = time.ticks_ms()
    _touch_down = down


# ── The perception pump: the ultrasonic unit, and the body rule ────────────

async def range_pump():
    global _range
    if not _range["ok"]:
        return
    fails = 0
    while True:
        try:
            ultrasonic.trigger(i2c_a)
            await asyncio.sleep_ms(ultrasonic.WAIT_MS)
            mm = ultrasonic.read(i2c_a)
            _range["mm"] = mm
            _range["t_ms"] = time.ticks_ms()
            fails = 0
        except Exception as e:
            fails += 1
            _range["errors"] += 1
            if fails == 5:
                print("range: 5 errors in a row ({}) — is the unit still on Port A?".format(e))
            await asyncio.sleep_ms(1000)
            continue
        # THE BODY RULE, the acting half: a commanded move under a person
        # who just appeared is stopped here, not left to the instinct.
        if not MOVE_WHILE_PRESENT and _desk.commanded() and _someone_near():
            _desk.stop()
            send("LOG: stopped the desk at {:.0f} mm — someone came within {:.0f} mm".format(
                _desk.height_mm() or 0, _range["mm"]))
        await asyncio.sleep_ms(max(0, RANGE_EVERY_MS - ultrasonic.WAIT_MS))


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
    AP_SSID, AP_PASS, AP_CHANNEL = "desk", "desk1234", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

# ── Display helper ─────────────────────────────────────────────────────────

def show(lines):
    Widgets.fillScreen(0x000000)
    y = 10
    for line in lines:
        Widgets.Label(line, 8, y, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu24)
        y += 32

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

        # ONE byte at a time: a bulk recv can swallow the start of the first
        # frame when the server sends immediately (diagnosed 2026-07-13).
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
            self._send_frame(0x8, b"", mask=True)
        except:
            pass
        try:
            self._sock.close()
        except:
            pass

# ── Instinct runtime ───────────────────────────────────────────────────────

ws = None
current_task = None

instinct_version = 0
_pending_iv = None
_clock_set = False
_connects = 0
_link_down_ms = None

JOURNAL = []            # (t_ms, line) — UNSYNCED lines only
JOURNAL_MAX = 400

_MARKERS = ("LOG:", "REFLECTION:", "CRASH:", "UPDATE:", "NO UPDATE:",
            "FAILED REFLECTION:", "OPERATOR:", "BOOT:", "MEM:", "IV:")


def _typed(msg):
    msg = str(msg)
    for m in _MARKERS:
        if msg.startswith(m):
            return msg
    return "LOG: " + msg


def send(msg, urgent=False):
    """Write one line to the journal. Does NOT summon the soul."""
    msg = _typed(msg)
    JOURNAL.append((time.ticks_ms(), msg))
    if len(JOURNAL) > JOURNAL_MAX:
        del JOURNAL[:JOURNAL_MAX // 4]
    try:
        if ws:
            ws.send(msg)
            JOURNAL.pop()
    except Exception as e:
        print("send: error:", e)


def reflect(reason):
    """Ask the soul to think, and say WHY — the only summons."""
    send("REFLECTION: " + str(reason), urgent=True)


async def _flush_journal(sock):
    """Replay unsynced lines with their ORIGINAL timestamps. No FLUSH-END
    (that token drives the batch handshake and would earn a NAP)."""
    n = asks = 0
    while JOURNAL:
        t_ms, line = JOURNAL[0]
        sock.send("J:{}:{}".format(t_ms, line))
        JOURNAL.pop(0)
        n += 1
        if line.startswith("REFLECTION:"):
            asks += 1
        if n % 20 == 0:
            await asyncio.sleep_ms(50)
    if n:
        print("flushed {} journal lines ({} asks)".format(n, asks))
    if asks:
        reflect("the link was down: {} lines replayed, {} earlier request(s) "
                "to think folded into this one".format(n, asks))


INSTINCT_ENV = {
    "send": send,
    "reflect": reflect,
    "asyncio": asyncio,
    "time": time,
    "struct": struct,
    "math": math,
    "M5": M5,
    "Imu": Imu,
    "Speaker": Speaker,
    "Widgets": Widgets,
    "mem": MEM,
    "Range": Range,
    "Desk": Desk,
    "Touch": Touch,
    # Calc, narrowed to what a desk can use: Gate (the seed's presence sense
    # keeps its edge in one), Running/Ema (levels and learned heights), Ring
    # (bounded windows), OneEuro/Onset (invitations, not dependencies).
    "Calc": type("Calc", (), {"OneEuro": Calc.OneEuro,
                              "Running": Calc.Running,
                              "Onset": Calc.Onset,
                              "Ring": Calc.Ring,
                              "Gate": Calc.Gate,
                              "Ema": Calc.Ema}),
}

DEFAULT_INSTINCT = """
async def run():
    while True:
        send("state=idle")
        await asyncio.sleep(5)
"""

async def run_instinct(code):
    env = dict(INSTINCT_ENV)
    env["IV"] = instinct_version
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
    # A cancelled instinct may have a move open. The desk keeps travelling
    # only while the reference input is refreshed (BLE) — and the virtual
    # desk would happily finish it — so: a fresh instinct starts from a
    # stopped desk, and the outcome is journalled by whoever asks next.
    _desk.stop()
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
    _desk.stop()
    Widgets.fillScreen(0x000000)
    try:
        Speaker.stop()
    except Exception:
        pass
    print("session: cleaned up")


DISPLAY_OFF_AFTER_S = 30

async def heartbeat():
    display_on_until = time.ticks_ms() + DISPLAY_OFF_AFTER_S * 1000
    display_lit = True
    stat_lbls = None
    last_stat = 0
    last_hb = 0
    while True:
        M5.update()
        _poll_touch()
        if DISPLAY_MODE == "debug":
            if not display_lit:
                try:
                    M5.Display.setBrightness(80)
                except Exception:
                    pass
                display_lit = True
            if time.ticks_diff(time.ticks_ms(), last_stat) > 1000:
                if stat_lbls is None:
                    Widgets.fillScreen(0x000000)
                    stat_lbls = [Widgets.Label("", 8, 10 + 32 * i, 1.0, 0xFFFFFF,
                                               0x000000, Widgets.FONTS.DejaVu24)
                                 for i in range(6)]
                    stat_lbls[0].setText("desk  v{}".format(instinct_version))
                stat_lbls[0].setText("desk  v{}  {}".format(
                    instinct_version, "ws up" if ws else "ws DOWN"))
                h = _desk.height_mm()
                stat_lbls[1].setText("height {}  {}".format(
                    "?" if h is None else "{:.0f}mm".format(h),
                    ("-> {:.0f}".format(_desk.target_mm()) if _desk.commanded()
                     else ("moving" if _desk.moving() else ""))))
                stat_lbls[2].setText("desk {} {}".format(
                    _desk.kind(), "linked" if _desk.connected() else "NO LINK"))
                mm = _range["mm"]
                stat_lbls[3].setText("range {}".format(
                    "absent" if not _range["ok"] else
                    "no echo" if mm == 0 else
                    "?" if mm is None else "{:.0f}mm".format(mm)))
                stat_lbls[4].setText("{}".format(
                    "{:02d}:{:02d}".format(*time.localtime()[3:5]) if _clock_set
                    else "up {}s".format(time.ticks_ms() // 1000)))
                last_stat = time.ticks_ms()
        else:
            stat_lbls = None
            if _touch_flag and not display_lit:
                # peek, without consuming the tap — that is the instinct's
                try:
                    M5.Display.setBrightness(80)
                except Exception:
                    pass
                h = _desk.height_mm()
                show(["desk", "height {}".format("?" if h is None else "{:.0f}mm".format(h)),
                      "ws " + ("up" if ws else "down")])
                display_on_until = time.ticks_ms() + 10 * 1000
                display_lit = True
            if display_lit and time.ticks_ms() > display_on_until:
                Widgets.fillScreen(0x000000)
                try:
                    M5.Display.setBrightness(0)
                except Exception:
                    pass
                display_lit = False
        await asyncio.sleep(0.05)
        if time.ticks_diff(time.ticks_ms(), last_hb) > HEARTBEAT_INTERVAL * 1000:
            last_hb = time.ticks_ms()
            try:
                if ws:
                    ws.send("HEARTBEAT")
            except:
                pass


def _set_clock(msg):
    """TIME:<unix_s>:<gmtoff_s> — the laptop's clock, via the spine. The
    desk lives by the hour (day close, quiet hours), so this matters more
    here than on any wearable."""
    global _clock_set
    try:
        u, off = msg[5:].split(":")
        epoch_off = 946684800 if time.gmtime(0)[0] == 2000 else 0
        local = int(u) + int(off) - epoch_off
        tm = time.gmtime(local)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        _clock_set = True
        print("clock: {:02d}:{:02d}".format(tm[3], tm[4]))
    except Exception as e:
        print("clock: set failed:", e)


def _boot_line(reason, down_s=None):
    clock = (" clock={:02d}:{:02d}".format(*time.localtime()[3:5])
             if _clock_set else "")
    try:
        vbat = M5.Power.getBatteryVoltage()
        vbus = M5.Power.getVBUSVoltage()
    except Exception:
        vbat, vbus = 0, 0
    h = _desk.height_mm()
    return ("BOOT: cause={} uptime={}s vbat={}mV vbus={}mV mode={} keepalive={} "
            "iv={} desk={}:{}:{} range={} wake={}".format(
                _RESET_CAUSES.get(_rc, _rc), time.ticks_ms() // 1000, vbat, vbus,
                "live", HEARTBEAT_INTERVAL, instinct_version,
                _desk.kind(), "linked" if _desk.connected() else "unlinked",
                "?" if h is None else "{:.0f}mm".format(h),
                "ok" if _range["ok"] else "absent", reason)
            + ("" if down_s is None else " down={}s".format(down_s))
            + clock)


async def _handle_msg(msg):
    global last_session_id, instinct_version, _pending_iv
    if msg == "NAP":
        print("ignoring NAP (live runtime)")
        return
    if msg.startswith("SESSION:"):
        sid = msg[len("SESSION:"):]
        if last_session_id is not None and last_session_id != sid:
            await session_start_cleanup()
            instinct_version = 0
        last_session_id = sid
        print("session: {}".format(sid))
        return
    if msg.startswith("IV:"):
        _pending_iv = int(msg[3:])
        return
    if msg.startswith("TIME:"):
        _set_clock(msg)
        return
    if msg.startswith("DESK:"):
        # The pretend paddle: DESK:<mm> moves the VIRTUAL desk as a hand
        # would (the tuner's `hand` command). Recognised before the exec
        # fallback, or it would run as instinct code. On a real desk there
        # is a real paddle; say so rather than pretend.
        try:
            mm = float(msg[5:])
        except ValueError:
            print("desk: bad DESK payload", msg)
            return
        if _desk.kind() == "virtual":
            _desk.hand(mm)
        else:
            send("LOG: a pretend hand was offered ({:.0f} mm) but this desk is real".format(mm))
        return
    if _pending_iv is not None:
        instinct_version = _pending_iv
        _pending_iv = None
    await swap_instinct(msg)


async def ws_listener():
    global ws, _connects
    print("ws: connecting to {}:{}".format(SPINE_HOST, SPINE_PORT))
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    if _connects == 0:
        ws.send(_boot_line("poweron"))
    else:
        down = (0 if _link_down_ms is None
                else max(0, time.ticks_diff(time.ticks_ms(), _link_down_ms) // 1000))
        ws.send(_boot_line("reconnect", down_s=down))
    _connects += 1
    await _flush_journal(ws)
    while True:
        try:
            msg = await ws.recv()
        except Exception as e:
            print("ws: recv error:", e)
            break
        if msg is None:
            print("ws: closed by server")
            break
        await _handle_msg(msg)


async def main():
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    # Senses and the desk link run regardless of WiFi/spine state.
    asyncio.create_task(range_pump())
    asyncio.create_task(_desk.task())
    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        globals()["_link_down_ms"] = time.ticks_ms()
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
    # Retry forever rather than raise: a crash here makes UIFlow reboot the
    # board in a loop whenever the network is down. A desk is unattended.
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

asyncio.run(main())
