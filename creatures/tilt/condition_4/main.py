"""
main.py — M5StickS3 "tilt" runtime: a PLAIN StickS3 — internal speaker and
IMU, nothing attached.

Same spine as the midi_dancer runtime — boots M5 hardware, brings up WiFi,
opens a WebSocket to the spine, and runs an asyncio loop with heartbeat +
instinct-hotswap tasks. The voice is the INTERNAL speaker only.

NO POSTURE ORGAN IN THIS ARM (2026-07-31). condition_1/training/condition_2
attach one that interposes on the instinct's Imu reads; condition_3 kept it
but had the instinct feed it explicitly. Here it is gone. What survived the
removal of the ref capture, the verb machine and the flavour words was about
fourteen lines of arithmetic — a gravity low-pass, a gyro-magnitude EMA, a
stillness timestamp and two atan2s — and ORGANS.md admits a capability to the
body only when souls repeatedly almost build it and fail on the mechanics.
Two atan2s are not that. So the sense lives in seed_instinct.py, where the
soul can read it, retune it, and be wrong about it on purpose.

What that buys: a change to what "still" means is a spine push instead of a
reflash. What it costs: the sense's state is now the instinct's to carry —
and mem is what it carries it in.

NO Mem IN THIS ARM either (2026-07-31). Mem bundled two unrelated jobs —
"this survives my rewrites" and "this is a bounded ring buffer" — and split
apart, both get simpler. `mem` does the first: one plain dict, injected by
reference, so a mutation persists the instant it happens — no push, no
flush, no restore, and no named-slot registry either. (A keep(name, default)
registry was tried between the two, 2026-07-31, and dropped the same day:
handing out MANY objects re-created the scalar/rebinding traps one dict does
not have.) Calc.Ring does the second, with maxlen as a constructor argument
so a window cannot exist without stating its size. The arbitrary
MAX_SLOTS = 8 and its silent drop go with the registry that needed them.
Mem is untouched everywhere else — the other creatures use it and the
earlier arms are frozen.

This file therefore reads no IMU at all and holds no body state.

Runtime provides to instinct code:
  send(msg)        write a journal line (costs nothing, does NOT summon)
  reflect(reason)  ask the soul to think, and say why (the only summons)
  Button           the explicit channel: Button.pressed() / .last_s()
  IV               this instinct's version number: a fresh spine session
                   always starts at v1, every rewrite after that is v2, v3...
  mem              ONE plain dict, the same dict for every instinct: it
                   outlives every hot-swap and dies with the power. Item
                   assignment writes into it, so mem["n"] += 1 and
                   mem["h_moves"] = [] both persist; only copying a value
                   into a local loses it. Declare defaults with
                   mem.setdefault(...) at the top of run().
  Calc             NARROWED to OneEuro / Running / Onset / Ring
  asyncio, time, struct, math, M5, Imu, Speaker

Device-side libraries flashed to /lib (creatures/tilt/<condition>/lib/*.py):
  calc.py          -> Calc          (signal toolkit; Ring lives here now)
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

# ── The voice + toolkits + body senses ──────────────────────────────────────
from calc import Calc

# The voice is the INTERNAL speaker. Two sticks3 speaker rules
# (test/STICKS3/API.md + legacy runtime): do NOT Speaker.begin() at boot —
# the amp idles audibly; instincts call begin()/setVolume() around each
# chirp and end() after. And a tone only plays while M5.update() ticks
# (the heartbeat ticks it every 50 ms).
Speaker = M5.Speaker

# ── mem: what an instinct carries across its own rewrites ───────────────────
#
# ONE plain dict, module scope: it outlives every hot-swap and dies with the
# power. The instinct holds the very dict this name holds, so a mutation is
# persisted the instant it happens — there is nothing to flush and nothing to
# restore, and because item assignment writes INTO the dict, even
# mem["h_moves"] = [] persists. The scalar trap that keep() had (a kept float
# could only be rebound, never changed) does not exist here: mem["n"] += 1
# writes back through the dict every time. The one way left to lose state is
# to copy a value into a local and update the local — which at least LOOKS
# wrong when written.
#
# Keys are never deleted: a rewrite that merely forgot one must not be able
# to destroy hours of accumulated history over a typo. A few stale bytes for
# one wearing is the cheaper mistake. Instincts declare defaults with
# mem.setdefault(...) at the top of run() — never in a loop, since the
# default is constructed on every call and discarded when the key exists.
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


def usb_present():
    # M5.Power.isCharging() is untrustworthy on this PMIC — it flips
    # True/False every 1-2 s while VBUS holds a steady 5.25 V (measured
    # 2026-07-18 with the tuner's `power` recipe). VBUS itself is the
    # reliable "plugged in" signal; keep isCharging() for reporting only.
    try:
        return M5.Power.getVBUSVoltage() > 4000
    except Exception:
        return M5.Power.isCharging()
ALWAYS_ON = True       # True: never nap even on battery — journal lines
                       # stream live (debug insight, battery cost). While
                       # CHARGING this is automatic: plugged in = live.
                       # !! Workbench setting (tuner sessions need it — the
                       # tuner is not batch-aware and a napping device reads
                       # as "disconnected"). Set back to False + reflash
                       # before any worn/battery study deployment.
HEARTBEAT_INTERVAL = 5  # seconds between HEARTBEATs while connected; announced
                        # to the spine in BOOT so its timeout adapts
STETHO_HOST = None      # WORN (set 2026-07-30): DETACHED. The organ stream
                        # is bench insight, never a data pipeline, and left
                        # armed it was the LARGEST radio load on this body —
                        # the organ probes posture_deg / rot_ema / still_s
                        # every 0.5 s as three separate UDP packets, so 6/s,
                        # ~24,000 over the 67-minute wearing that ended in a
                        # brownout loop. (The 20x heartbeat bug fixed the
                        # same day was 4/s, i.e. smaller than this.) With the
                        # host unset, stethoscope.tap()/probe() see no target
                        # and return without opening a socket, so the organ's
                        # own _tap/_probe calls cost a None check.
                        #
                        # the organ stream (UDP-OSC :9001 — movement 3,
                        # advisory and lossy). "spine": arm toward SPINE_HOST
                        # at every radio-up; an "x.x.x.x" string: toward that
                        # host; None: stay detached until the tuner's `stetho`
                        # command arms it by hand. Attach state is RAM-only
                        # and batch naps kill the socket, hence re-arm on
                        # radio-up.

# ── Display policy (edit HERE, like WIFI_MODE) ──────────────────────────────
DISPLAY_MODE = "off"    # WORN (set 2026-07-30): the panel was lit at
                        # brightness 80 and redrawn 1/s against a back where
                        # nobody could see it, all session. BtnB still wakes a
                        # 10 s peek. Set "debug" for bench work.
                        # "debug": bench dashboard — while generously powered
                        # (ALWAYS_ON or USB) the panel stays lit with link /
                        # battery / vbus / reset-cause once a second.
                        # "off": worn — backlight dark; BtnA wakes a 10 s
                        # status peek; boot status still shows ~30 s.

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
            self._send_frame(0x8, b"", mask=True)   # client frames must mask
        except:
            pass
        try:
            self._sock.close()
        except:
            pass

# ── Instinct runtime ───────────────────────────────────────────────────────

ws = None
current_task = None

# The journal: every send() lands here with the creature clock; whatever is
# unsynced gets replayed to the spine (as J:<t_ms>:<line>) at the next wake.
JOURNAL = []            # (t_ms, line)
JOURNAL_MAX = 400
_wake_now = None        # asyncio.Event, created in main
instinct_version = 0    # spine's version of the instinct we run (0 = seed)
_connects = 0           # websocket connects this boot: 0 = the first
_link_down_ms = None    # when the link dropped, to report how long it was out


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


def send(msg, urgent=False):
    msg = _typed(msg)
    JOURNAL.append((time.ticks_ms(), msg))
    if len(JOURNAL) > JOURNAL_MAX:
        del JOURNAL[:JOURNAL_MAX // 4]
    if WIFI_MODE == "live":
        try:
            if ws:
                ws.send(msg)
                # Delivered — drop it, so JOURNAL holds only UNSYNCED lines
                # (what its docstring above always claimed). Without this the
                # whole session accumulates here and _flush_journal replays
                # every already-delivered line on the next reconnect, which
                # now also re-fires REFLECTION: requests the soul has already
                # answered.
                JOURNAL.pop()
        except Exception as e:
            print("send: error:", e)
    # a crash is always urgent: the soul should hear about it soon
    if (urgent or msg.startswith("CRASH:")) and _wake_now is not None:
        _wake_now.set()

# ── The button: the one explicit channel ───────────────────────────────────
# One press, one True. Detected HERE, not in the instinct, for two reasons: a
# callback registered by an instinct would outlive it (swap_instinct replaces
# the coroutine and unregisters nothing, so every rewrite leaks another
# handler holding a dead scope), and a latch here means the instinct cannot
# miss a press by polling slowly or by sitting inside an await.
#
# A FLAG, not a counter. Counting invited the reading that two presses mean
# something different from one, which nothing has shown. Two presses inside a
# single poll collapse to one True — at the seed's 50 Hz that needs them
# closer together than a human hand manages, and if a rewrite ever wants to
# tell a double from a single it can time consecutive presses itself with
# last_s(). Dropping the count also drops the arbitrary queue cap it needed.
_btn_flag = False       # one-shot: set on press, cleared on read
_btn_last = None        # ticks_ms of the most recent press; None until one


def _btn_event(*_a):    # *_a: the callback may be handed the button state
    global _btn_flag, _btn_last
    _btn_flag = True
    _btn_last = time.ticks_ms()


class _Button:
    """The instinct's handle on the explicit channel — a module like Posture
    or Speaker, not a loose function, so every sense in scope is reached the
    same way. Read-only: the latch above is the body's, so the instinct can
    consume a press but never invent one.

    Both readings are BODY state: they outlive every instinct rewrite and die
    with the power, exactly like the organ's."""

    def pressed(self):
        """True once per press, the moment it lands. Consumed on read — the
        same press is never reported twice."""
        global _btn_flag
        f = _btn_flag
        _btn_flag = False
        return f

    def last_s(self):
        """Seconds since the most recent press, or None if there has not been
        one this wearing. NOT consumed on read: this is a state, not an event
        — read it as often as you like and it keeps counting up. Seconds
        rather than a raw stamp so it needs no epoch and cannot be compared
        against the wrong clock (ticks_ms wraps; this does not)."""
        if _btn_last is None:
            return None
        return max(0.0, time.ticks_diff(time.ticks_ms(), _btn_last) / 1000.0)


def _btn_poll_fn():
    """Resolve the polling edge-reader ONCE, so the fallback path doesn't
    raise AttributeError twenty times a second. wasPressed first: it lands on
    the press itself, where wasClicked waits for the release."""
    for name in ("wasPressed", "wasClicked"):
        if hasattr(M5.BtnA, name):
            return name, getattr(M5.BtnA, name)
    return None, None


# Prefer the driver's own event dispatch: it fires exactly once per press, so
# nothing depends on how fast anyone polls. It is dispatched synchronously
# from inside M5.update() — not an interrupt, not a thread — which is why the
# handler above only sets a flag and never awaits.
#
# WAS_PRESSED before WAS_CLICKED so "the moment it lands" is literally true;
# WAS_CLICKED only fires once the button comes back up. Which edge is live is
# reported in the BOOT line as btn=... — the tuner's `button` recipe is how
# that gets confirmed on real hardware. Confirmed 2026-07-30: presses land
# exactly once, on the first flash of this arm.
_btn_cb = None
for _edge in ("WAS_PRESSED", "WAS_CLICKED"):
    try:
        M5.BtnA.setCallback(type=getattr(M5.BtnA.CB_TYPE, _edge), cb=_btn_event)
        _btn_cb = _edge
        print("btn: driver callback", _edge)
        break
    except Exception as e:
        print("btn: no {} callback ({})".format(_edge, e))
_btn_poll_name, _btn_poll = (None, None) if _btn_cb else _btn_poll_fn()
if not _btn_cb:
    print("btn: polling in heartbeat" if _btn_poll else
          "btn: NO usable button API — the explicit channel is dead")


def reflect(reason):
    """Ask the soul to think, and say WHY. Journalling never does this —
    send() only writes to the record; this is the one call that summons a
    reflection. On a sleeping body it also wakes the radio."""
    send("REFLECTION: " + str(reason))
    if _wake_now is not None:
        _wake_now.set()


INSTINCT_ENV = {
    "send": send,
    "reflect": reflect,
    "Button": _Button(),
    "asyncio": asyncio,
    "time": time,
    "struct": struct,
    "math": math,
    "M5": M5,
    "Imu": Imu,
    "Speaker": Speaker,
    # Calc, NARROWED. calc.py ships to every board but was written for the
    # dancers: across all device creatures 0 of 226 soul-written instincts
    # ever used it. Rather than offer eight classes nobody reaches for, this
    # body hands over the three that suit a back. Madgwick/Pose and Flow want
    # a compass this board does not have (getMag() is always zeros) and would
    # mean a second orientation filter beside the one in the instinct;
    # Periodicity and AlphaBeta track beats at 50-200 bpm, and nothing this
    # animal cares about happens at a tempo. A tool in scope is an invitation
    # to use it.
    "mem": MEM,
    "Calc": type("Calc", (), {"OneEuro": Calc.OneEuro,
                              "Running": Calc.Running,
                              "Onset": Calc.Onset,
                              "Ring": Calc.Ring,
                              "Gate": Calc.Gate}),
    # Gate ADDED 2026-07-31 with the mem arm: the seed's stillness sense
    # keeps its edge inside a Gate stored in mem, so this one is not an
    # invitation but a dependency — remove it and the seed crashes at its
    # first setdefault. The other four are invitations: the seed currently
    # uses none of them, but Running is exactly what the walk-offset recipe
    # in its experience calls for, and Ring is the bounded window it will
    # want the day it keeps recent poses.
}

DEFAULT_INSTINCT = """
async def run():
    while True:
        send("state=idle")
        await asyncio.sleep(5)
"""

async def run_instinct(code):
    env = dict(INSTINCT_ENV)
    # Which instinct am I? The creature compares this against the version it
    # stored in its mem to tell a REWRITE (version changed) from a re-push
    # or reconnect (version identical). 0 = the seed, before any IV: arrived.
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
    # A cancelled instinct can leave the speaker amp on — silence it
    # before the next one starts.
    try:
        Speaker.end()
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
    try:
        Speaker.end()
    except Exception:
        pass
    print("session: cleaned up")


DISPLAY_OFF_AFTER_S = 30   # blank after boot status is readable; the
                           # backlight is a steady ~10-20 mA — battery money

async def heartbeat():
    display_on_until = time.ticks_ms() + DISPLAY_OFF_AFTER_S * 1000
    display_lit = True
    stat_lbls = None
    last_stat = 0
    last_hb = 0
    while True:
        M5.update()
        # Fallback edge detection, at update()'s own 20 Hz. Skipped entirely
        # when the driver callback took, since that already fired.
        if _btn_poll is not None and _btn_poll():
            _btn_event()
        if DISPLAY_MODE == "debug" and (ALWAYS_ON or usb_present()):
            # Workbench narration: panel stays lit and reports link state,
            # battery, uptime and RESET CAUSE — a brownout-rebooting board
            # is diagnosable at a glance (added 2026-07-18: board was
            # resetting every ~minute with the screen dark and mute).
            if not display_lit:
                M5.Display.setBrightness(80)
                display_lit = True
            if time.ticks_diff(time.ticks_ms(), last_stat) > 1000:
                if stat_lbls is None:
                    Widgets.fillScreen(0x000000)
                    stat_lbls = [Widgets.Label("", 5, 10 + 24 * i, 1.0, 0xFFFFFF,
                                               0x000000, Widgets.FONTS.DejaVu18)
                                 for i in range(5)]
                    stat_lbls[0].setText("tilt bench")
                stat_lbls[1].setText("ws " + ("up" if ws else "DOWN"))
                stat_lbls[2].setText("{}mV{}".format(
                    M5.Power.getBatteryVoltage(),
                    " chg" if M5.Power.isCharging() else ""))
                # usb line: ~5000 = 5V present; near 0 = input dropped
                stat_lbls[3].setText("usb {}mV".format(M5.Power.getVBUSVoltage()))
                stat_lbls[4].setText("up {}s {}".format(
                    time.ticks_ms() // 1000, _RESET_CAUSES.get(_rc, _rc)))
                last_stat = time.ticks_ms()
        else:
            stat_lbls = None
            # BtnB, not BtnA: BtnA is the creature's explicit channel (the
            # instinct reads it as the hush) and wasPressed() is one-shot —
            # two readers race and each swallows presses at random.
            if M5.BtnB.wasPressed():       # a press wakes the screen briefly
                M5.Display.setBrightness(80)
                show(["tilt", "vbat: {}mV".format(M5.Power.getBatteryVoltage()),
                      "ws: " + ("up" if ws else "down")])
                display_on_until = time.ticks_ms() + 10 * 1000
                display_lit = True
            if display_lit and time.ticks_ms() > display_on_until:
                Widgets.fillScreen(0x000000)
                M5.Display.setBrightness(0)
                display_lit = False
        await asyncio.sleep(0.05)
        # Remember the last send; do NOT test the clock. `(ticks_ms()//1000) %
        # HEARTBEAT_INTERVAL == 0` was true for a whole SECOND, and this loop
        # runs every 50 ms — so it sent 20 heartbeats per interval, 240 a
        # minute instead of 12 (measured 2026-07-30). On a worn body that is a
        # 20x multiplier on WiFi transmit bursts, which are the expensive part
        # of this board's power budget and the thing brownouts were traced to.
        if time.ticks_diff(time.ticks_ms(), last_hb) > HEARTBEAT_INTERVAL * 1000:
            last_hb = time.ticks_ms()
            try:
                if ws:
                    ws.send("HEARTBEAT")
            except:
                pass


async def _handle_msg(msg):
    """One spine message: session bookkeeping, IV tags, NAP, or instinct."""
    global last_session_id, instinct_version, _pending_iv
    if msg is None:
        return "closed"
    if msg == "NAP":
        return "nap"
    if msg.startswith("SESSION:"):
        sid = msg[len("SESSION:"):]
        if last_session_id is not None and last_session_id != sid:
            await session_start_cleanup()
            instinct_version = 0        # new session: our instinct is stale
        last_session_id = sid
        print("session: {}".format(sid))
        return None
    if msg.startswith("IV:"):
        _pending_iv = int(msg[3:])
        return None
    if msg.startswith("TIME:"):
        _set_clock(msg)
        return None
    # Adopt the version BEFORE the swap: run_instinct puts it in the instinct
    # scope, and a creature that reads its own version one behind cannot tell
    # a real rewrite from a re-push of the code it is already running.
    if _pending_iv is not None:
        instinct_version = _pending_iv
    globals()["_pending_iv"] = None
    await swap_instinct(msg)
    return "instinct"


_pending_iv = None
_clock_set = False


def _set_clock(msg):
    """TIME:<unix_s>:<gmtoff_s> — the laptop's clock, via the spine. Sets
    the RTC, which carries across radio naps (not across power-off; every
    connect re-syncs). Gives the animal a real sense of the hour."""
    global _clock_set
    try:
        u, off = msg[5:].split(":")
        # The epoch is a BUILD property, not a given: MicroPython ports use
        # 2000-01-01, others (and some M5 builds) use the unix 1970 epoch.
        # Assuming 2000 on a 1970-epoch board shifts the DATE back exactly
        # 10957 days — a whole number, so hour:minute stay correct while the
        # YEAR lands in 1996. That failed silently: BOOT printed the right
        # clock=HH:MM (it reads localtime()[3:5]) while every journal entry
        # fell back to t+Nm (the seed tests localtime()[0] >= 2020). Detect
        # it instead of assuming.
        epoch_off = 946684800 if time.gmtime(0)[0] == 2000 else 0
        local = int(u) + int(off) - epoch_off
        tm = time.gmtime(local)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        _clock_set = True
        print("clock: {:02d}:{:02d}".format(tm[3], tm[4]))
    except Exception as e:
        print("clock: set failed:", e)


def _boot_line(reason, down_s=None):
    # clock token LAST: the spine matches startswith("BOOT:") to detect
    # the announce — a prefix would silently break batch detection
    clock = (" clock={:02d}:{:02d}".format(*time.localtime()[3:5])
             if _clock_set else "")
    return ("BOOT: cause={} uptime={}s vbat={}mV vbus={}mV charging={} "
            "mode={} keepalive={} iv={} btn={} wake={}".format(
                _RESET_CAUSES.get(_rc, _rc), time.ticks_ms() // 1000,
                M5.Power.getBatteryVoltage(), M5.Power.getVBUSVoltage(),
                M5.Power.isCharging(),
                WIFI_MODE, HEARTBEAT_INTERVAL, instinct_version,
                # WHICH edge is live, not just that one is: WAS_PRESSED
                # lands on the press, WAS_CLICKED on the release
                ("cb:" + _btn_cb) if _btn_cb else
                ("poll:" + _btn_poll_name if _btn_poll else "none"),
                reason)
            + ("" if down_s is None else " down={}s".format(down_s))
            + clock)


async def _flush_journal(sock):
    """Replay unsynced journal lines with their original timestamps."""
    n = 0
    while JOURNAL:
        t_ms, line = JOURNAL[0]
        sock.send("J:{}:{}".format(t_ms, line))
        JOURNAL.pop(0)
        n += 1
        if n % 20 == 0:
            await asyncio.sleep_ms(50)   # don't starve the loop on big flushes
    sock.send("FLUSH-END")
    print("flushed {} journal lines".format(n))


def _arm_stetho():
    """(Re)arm the organ stream at radio-up, per the STETHO_HOST policy.
    Attach state is RAM-only; the stethoscope module itself heals its
    socket across bounces once it knows the target."""
    if not STETHO_HOST:
        return
    try:
        import stethoscope
        stethoscope.attach(SPINE_HOST if STETHO_HOST == "spine" else STETHO_HOST)
    except Exception as e:
        print("stetho: arm failed:", e)


def _radio_down():
    global ws
    if ws:
        try:
            ws.close()
        except Exception:
            pass
        ws = None
    try:
        network.WLAN(network.STA_IF).active(False)
        print("radio: off")
    except Exception as e:
        print("radio: off failed:", e)


async def session_window(reason):
    """One connected stretch: BOOT, journal flush, then hold until the spine
    says NAP, a fresh instinct lands (grace period after), or the wait runs
    out. A reader task owns recv() — never cancelled mid-frame; the socket
    is closed first, so a partial read can't desync the stream."""
    global ws
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected ({})".format(reason))
    ws.send(_boot_line(reason))
    await _flush_journal(ws)

    inbox = []
    done = [False]

    async def reader(sock):
        try:
            while True:
                m = await sock.recv()
                inbox.append(m)
                if m is None:
                    break
        except Exception as e:
            inbox.append(None)
            print("ws: recv error:", e)
        done[0] = True

    rt = asyncio.create_task(reader(ws))
    deadline = time.ticks_ms() + REFLECT_WAIT_S * 1000
    reason_out = "reflect wait expired"
    while time.ticks_ms() < deadline:
        # drain journal lines produced while connected (an instinct's first
        # sends, crashes); an urgent among them re-runs the flush handshake
        if JOURNAL:
            while JOURNAL:
                t_ms, line = JOURNAL[0]
                ws.send("J:{}:{}".format(t_ms, line))
                JOURNAL.pop(0)
            if _wake_now.is_set():
                _wake_now.clear()
                ws.send("FLUSH-END")
                deadline = time.ticks_ms() + REFLECT_WAIT_S * 1000
        if ALWAYS_ON or usb_present():
            # plugged in (or debug ALWAYS_ON): keep the window rolling
            deadline = time.ticks_ms() + 60 * 1000
        if inbox:
            kind = await _handle_msg(inbox.pop(0))
            if kind == "closed":
                reason_out = "closed by spine"
                break
            if kind == "nap":
                if ALWAYS_ON or usb_present():
                    continue           # live: acknowledge by ignoring
                reason_out = "spine: NAP"
                break
            if kind == "instinct":
                # a rewrite just landed: linger briefly so its first sends
                # and any CRASH make it back before we sleep
                deadline = min(deadline, time.ticks_ms() + 30 * 1000)
        elif done[0]:
            reason_out = "connection ended"
            break
        else:
            await asyncio.sleep_ms(100)
    print(reason_out)
    # close the socket BEFORE cancelling the reader: no mid-frame cancel
    try:
        ws.close()
    except Exception:
        pass
    if not done[0]:
        rt.cancel()
        try:
            await rt
        except asyncio.CancelledError:
            pass


async def _lowbat_alarm():
    """The dying cricket: a slow, falling figure, twice — unmistakably
    different from the vocabulary's quick sweeps. Audition: tuner `lowbat`."""
    try:
        Speaker.begin()
        Speaker.setVolume(100)
        for _ in range(2):
            for f in (3000, 2400, 1800):
                Speaker.tone(f, 130)
                M5.update()
                await asyncio.sleep_ms(150)
            await asyncio.sleep_ms(350)
        Speaker.end()
    except Exception as e:
        print("lowbat alarm failed:", e)


async def wait_for_wake():
    """Sleep (radio off) until the next wake reason. Returns the reason."""
    lowbat_sent = False
    deadline = time.ticks_ms() + FLUSH_EVERY_S * 1000
    while True:
        if _wake_now.is_set():
            _wake_now.clear()
            return "urgent"
        if not lowbat_sent and M5.Power.getBatteryVoltage() < LOW_VBAT_MV \
                and not usb_present():
            lowbat_sent = True
            send("battery low ({}mV) — final sync".format(
                M5.Power.getBatteryVoltage()))
            await _lowbat_alarm()
            return "lowbat"
        if time.ticks_ms() > deadline:
            return "timer"
        if ALWAYS_ON or usb_present():
            # plugged in (or ALWAYS_ON): reconnect promptly
            deadline = min(deadline, time.ticks_ms() + 15 * 1000)
        await asyncio.sleep_ms(500)


async def batch_main():
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    reason = "boot"
    while True:
        try:
            connect_sta(STA_SSID, STA_PASS)
            _arm_stetho()
            await session_window(reason)
        except Exception as e:
            print("wake cycle error:", e)
        _radio_down()
        _wake_now.clear()               # sends during the window are synced
        reason = await wait_for_wake()
        print("wake:", reason)


async def live_listener():
    global ws, _connects, _link_down_ms
    print("ws: connecting to {}:{}".format(SPINE_HOST, SPINE_PORT))
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    # wake= says why this announce happened. The BOOT: line is sent on EVERY
    # connect, so without this the reader cannot tell a power-on from a
    # reconnect except by squinting at uptime=. (In batch mode wake= carries
    # the nap reason — timer/urgent/lowbat — same question, same token.)
    if _connects == 0:
        ws.send(_boot_line("poweron"))
    else:
        down = (0 if _link_down_ms is None
                else max(0, (time.ticks_ms() - _link_down_ms) // 1000))
        ws.send(_boot_line("reconnect", down_s=down))
    _connects += 1
    await _flush_journal(ws)
    while True:
        msg = await ws.recv()
        if msg is None:
            print("ws: closed by server")
            break
        await _handle_msg(msg)


async def live_main():
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    while True:
        try:
            await live_listener()
        except Exception as e:
            print("ws: error:", e)
        globals()["_link_down_ms"] = time.ticks_ms()
        print("ws: reconnect in 3s")
        await asyncio.sleep(3)


async def main():
    global _wake_now
    _wake_now = asyncio.Event()
    if WIFI_MODE == "batch":
        await batch_main()
    else:
        await live_main()


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
    _arm_stetho()
elif MODE == "sta":
    SPINE_HOST = SPINE_HOST_STA
    show(["mode: STA", "ssid: " + STA_SSID, "connecting..."])
    if WIFI_MODE == "live":
        # Retry forever rather than raise: a crash here makes UIFlow reboot
        # the board in a loop whenever the network is down or misnamed.
        while True:
            try:
                ip = connect_sta(STA_SSID, STA_PASS)
                break
            except Exception as e:
                show(["STA failed:", str(e)[-24:], "retrying..."])
                time.sleep(5)
        show(["STA: " + STA_SSID, "ip: " + ip, "spine: " + SPINE_HOST])
        _arm_stetho()
    else:
        # batch: the wake cycle owns connectivity; boot just proceeds
        show(["mode: batch", "ssid: " + STA_SSID, "spine: " + SPINE_HOST])
else:
    show(["bad MODE: " + str(MODE)])
    raise ValueError("MODE must be 'ap' or 'sta'")

asyncio.run(main())
