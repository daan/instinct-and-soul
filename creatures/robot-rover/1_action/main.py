"""
main.py — M5StickS3 + RoverC runtime (robot-rover stage 1_action).

The third body on the same stick and the same 8-pin header: robot_dog's PuppyC
puts four legs behind an STM32 at I2C 0x38, robot-bug's BugC puts four DC
motors there, and a RoverC puts four MECANUM wheels there. Forked from
creatures/robot-bug/1_action/main.py (2026-08-15), register map and verbs
swapped for the rover, LEDs dropped (the RoverC has none).

The RoverC is sold for the M5StickC, whose HAT pins are quoted as SDA=G0,
SCL=G26. That is StickC GPIO numbering and does NOT transfer to an S3. The
pins used here are the StickS3 mapping, already proven on this header twice
by robot_dog and robot-bug.

Stage 1 is the MOTION half: forward, backward, sideways, cw, ccw, and speed.
No senses on the Grove bus; nothing on the RoverC-Pro's servo registers.

THE LOOP is why this body exists. It writes motor bytes, and the IMU reports
what actually happened. Every command is a small experiment and lib/drive.py
scores it: turned, dps, stir, stalled. It is fed HERE, from heartbeat(), and
the instinct gets a read-only view: an instinct that could write its own
achieved rotation could flatter itself about its own competence.

Runtime provides to instinct code:
  send(msg)        write a journal line (costs nothing, does NOT summon)
  reflect(reason)  ask the soul to think, and say why (the only summons)
  forward/backward/slide_left/slide_right/cw/ccw/move/stop, Drive
                                           via drive.attach
  mem              one dict that survives a rewrite and dies with the power
  asyncio, Pin, I2C, PWM, SoftI2C, time, struct, math, M5, Imu,
  Speaker, Widgets, i2c_hat

Device-side libraries flashed to /lib (creatures/robot-rover/1_action/lib/*.py):
  drive.py         -> attach(scope) (the Drive instrument + the motor verbs)
  stethoscope.py   -> the bench organ stream (detached unless armed)

UNCALIBRATED UNTIL MEASURED. drive.MOTOR_CORNER / MOTOR_SIGN / SPEED_FLOOR all
start None, and while the first two are None the verbs REFUSE to move. The
RoverC protocol says which register is which motor; it does not say which
motor is which WHEEL, and on a mecanum base that is not cosmetic — the mixer
sends opposite signs to the two front wheels when sliding. Run the tuner's
`motors` and `floor` recipes and paste the numbers in.
"""

import M5
from M5 import *
import time
import machine

# Why did we boot? Decisive when hunting spontaneous resets: watchdog vs
# brownout vs power-on look identical from outside (the servo rail makes
# brownouts a live hazard here). Read before M5.begin() touches anything.
_RESET_CAUSES = {machine.PWRON_RESET: "PWRON", machine.HARD_RESET: "HARD",
                 machine.WDT_RESET: "WDT", machine.DEEPSLEEP_RESET: "DEEPSLEEP",
                 machine.SOFT_RESET: "SOFT"}
_rc = machine.reset_cause()
print("reset cause:", _RESET_CAUSES.get(_rc, _rc))

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

# UIFlow firmware doesn't put /flash/lib on sys.path by default. Our flashed
# creature drivers land there (creatures/robot-rover/1_action/lib/*.py → /lib/
# via mpremote, which is /flash/lib/ at runtime), so we insert it manually
# before importing. Without this the import below fails with "no module named
# 'drive'" while the file sits plainly visible in `mpremote fs ls :lib` —
# because sys.path's own "/lib" is a path in the root VFS, where nothing is
# mounted. robot_dog, tilt and kata_master all carry this block; robot-bug
# does not, which is one more reason to think it was never run.
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

import drive

# ── RoverC bus + helpers ────────────────────────────────────────────────────
#
# Same 8-pin StickC HAT header, same I2C address, same SoftI2C bus that
# robot_dog drives its legs on and robot-bug its motors — a different STM32
# behind it with its own register map. The StickS3 pin mapping, not the
# StickC numbering the RoverC docs quote.
#
#   reg 0x00..0x03   one SIGNED byte per motor, -100..+100
#   reg 0x00         bulk: four speed bytes
#   reg 0x10+n       RoverC-Pro servo angles — NOT touched in stage 1
#
# The RoverC has no LEDs. This body's only output is movement.

ROVERC_ADDR = 0x38

i2c_hat = SoftI2C(scl=Pin(0), sda=Pin(8), freq=100000)


def _write_speeds(speeds):
    """Four signed bytes in one transaction. struct.pack('b'), NOT bytes():
    bytes([-50]) raises ValueError in MicroPython, and every speed here can
    be negative."""
    try:
        i2c_hat.writeto_mem(ROVERC_ADDR, 0x00, struct.pack("bbbb", *speeds))
    except Exception as e:
        print("roverc: motor write error {} err={}".format(speeds, e))


# The motor verbs and the DRIVE instrument both live in lib/drive.py: the
# instrument has to know what was commanded in order to score it, and putting
# the verbs beside it is what makes that impossible to bypass. The runtime
# installs the real I2C writer; with none installed (the sim, or a stick with
# no rover under it) the command bookkeeping still runs, so the whole loop is
# exercised without a rover attached.
drive.set_writer(_write_speeds)
drive.stop()           # motors off early — covers power-on hold and post-flash
                       # junk, the way robot_dog centres its legs


# ── mem: what an instinct carries across its own rewrites ───────────────────
#
# ONE plain dict, module scope: it outlives every hot-swap and dies with the
# power. The instinct holds the very dict this name holds, so a mutation is
# persisted the instant it happens — nothing to flush, nothing to restore.
# Instincts declare defaults with mem.setdefault(...) at the top of run().
# (The same shape kata_master settled on; robot-bug's seed still calls a Mem
# class that no runtime provides.)
MEM = {}


# ── CTL: the operator's hand on the wheel ───────────────────────────────────
#
# `CTL:<fwd>,<strafe>,<spin>[,<label>]` drives the motors DIRECTLY, without
# touching the running instinct. It exists for the tuner's joystick mode, and
# it is deliberately not a way to write instinct code: every other message the
# spine sends gets exec'd and swaps the coroutine, which stops the body
# (swap_instinct calls drive.stop() first) and restarts it from scratch. At
# keystroke rates that is a stutter machine.
#
# THE DEADMAN IS THE POINT. A latched joystick means the rover keeps moving
# after you let go of the key — so if the laptop closes, the tuner quits, or
# the wifi drops mid-drive, something has to notice that nobody is holding the
# wheel any more. The heartbeat loop stops the motors CTL_DEADMAN_MS after the
# last CTL. The tuner re-sends the current vector every ~200 ms to say "still
# here"; a repeat of the SAME vector only refreshes the timer and does not
# re-issue the command, so the record gets one scored bout per thing you
# actually did rather than five per second.
CTL_DEADMAN_MS = 400
_ctl_last = None          # ticks_ms of the last CTL heard
_ctl_vec = (0, 0, 0)      # what the operator currently has commanded
_ctl_active = False       # is the operator the one driving right now?


def _handle_ctl(body):
    """One CTL payload: fwd,strafe,spin[,label], each -100..100."""
    global _ctl_last, _ctl_vec, _ctl_active
    try:
        parts = body.split(",")
        vec = (int(parts[0]), int(parts[1]), int(parts[2]))
        label = parts[3] if len(parts) > 3 else "ctl"
    except Exception as e:
        print("ctl: bad payload {!r}: {}".format(body, e))
        return
    _ctl_last = time.ticks_ms()
    if vec == _ctl_vec:
        return                      # keepalive only: no new bout, no I2C
    _ctl_vec = vec
    if vec == (0, 0, 0):
        drive.stop()
        _ctl_active = False
        return
    if drive.move(vec[0], vec[1], vec[2], label,
                  max(abs(vec[0]), abs(vec[1]), abs(vec[2]))):
        _ctl_active = True
    else:
        _ctl_active = False
        send("LOG: operator asked for {} but {}".format(
            label, drive._calibration_fault()))


# ── No senses on the Grove bus in this stage ────────────────────────────────
# 1_action is the motion half. The camera and the ToF arrive in 2_perception,
# on I2C(0, sda=9, scl=10) — a second bus that does not collide with the HAT's
# SoftI2C, as robot_dog/3_interaction already proves.


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
    AP_SSID, AP_PASS, AP_CHANNEL = "rover", "rover123", 6
    STA_SSID, STA_PASS = "Lee", "coffeepot"
    SPINE_HOST_AP, SPINE_HOST_STA = "192.168.4.2", "10.0.0.2"
    SPINE_PORT = 8765
    CONFIG_SOURCE = "defaults"

STETHO_HOST = None      # the bench organ stream (UDP-OSC :9001). DETACHED:
                        # on tilt, left armed it was the single largest radio
                        # load on the body — 6 packets/s, ~24,000 over one
                        # wearing, larger than the 20x heartbeat bug. A rover
                        # is always on its own battery. The tuner's `stetho`
                        # command arms it by hand for bench work.

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

# ── The spine handshake: version, clock, link ──────────────────────────────
# The spine teaches us our own instinct version with IV: and the hour with
# TIME:, and we announce both back in every BOOT: line. iv= is what lets a
# RECONNECT skip the re-push: pushing calls swap_instinct, which restarts
# run() and wipes every local it holds, so walking out of WiFi range and
# back would otherwise cost the creature its running state.
instinct_version = 0    # spine's version of the instinct we run (0 = seed)
_pending_iv = None      # an IV: seen, not yet adopted by the swap it tags
_clock_set = False      # has a TIME: landed since power-on?
_connects = 0           # websocket connects this boot: 0 = the first
_link_down_ms = None    # when the link dropped, to report how long it was out

# The journal (matching creatures/tilt): every send() lands here with the
# creature clock, and whatever has NOT reached the spine is replayed at the
# next connect. Load-bearing now that a reconnect no longer restarts the
# instinct — the body keeps running and keeps talking, so without this a WiFi
# blip silently swallows everything it journalled during the outage.
JOURNAL = []            # (t_ms, line) — UNSYNCED lines only
JOURNAL_MAX = 400

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
    """Write one line to the journal. This does NOT summon the soul, so it is
    cheap — write what the moment deserves.

    `urgent` is accepted for parity with the batch runtimes (creatures/tilt),
    where it wakes a sleeping radio. This body is live-only: there is nothing
    to wake, so it is a no-op here. Kept in the signature so instinct code
    moves between the two families unchanged."""
    msg = _typed(msg)
    JOURNAL.append((time.ticks_ms(), msg))
    if len(JOURNAL) > JOURNAL_MAX:
        del JOURNAL[:JOURNAL_MAX // 4]
    try:
        if ws:
            ws.send(msg)
            # Delivered — drop it again, so JOURNAL holds only the UNSYNCED
            # lines its docstring claims. send() has no awaits, so the entry
            # just appended is still the last one.
            JOURNAL.pop()
    except Exception as e:
        print("send: error:", e)

def reflect(reason):
    """Ask the soul to think, and say WHY. Journalling never does this —
    send() only writes to the record; this is the one call that summons a
    reflection. Say what changed or what you cannot resolve."""
    send("REFLECTION: " + str(reason), urgent=True)


async def _flush_journal(sock):
    """Replay unsynced lines with their ORIGINAL timestamps, so the record says
    when things happened rather than when the link came back.

    Deliberately NO FLUSH-END: that token drives the spine's batch handshake,
    which answers with NAP (spine.py _flush_ack) — and a NAP arriving here
    would be exec'd as instinct code. Live runtimes replay and carry on.

    A replayed REFLECTION: registers with the spine but does not schedule one
    (the spine gates scheduling on the batch handshake), so if the outage
    swallowed any asks, make ONE afterwards. That is also the right number: the
    soul wants the situation now, not a queue of stale requests."""
    n = asks = 0
    while JOURNAL:
        t_ms, line = JOURNAL[0]
        sock.send("J:{}:{}".format(t_ms, line))
        JOURNAL.pop(0)
        n += 1
        if line.startswith("REFLECTION:"):
            asks += 1
        if n % 20 == 0:
            await asyncio.sleep_ms(50)   # don't starve the loop on big flushes
    if n:
        print("flushed {} journal lines ({} asks)".format(n, asks))
    if asks:
        reflect("the link was down: {} lines replayed, {} earlier request(s) "
                "to think folded into this one".format(n, asks))


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
    "mem": MEM,
    # the rover's own bus, for anything the register map allows that the verbs
    # do not (the Pro's servos, a raw four-byte poke while calibrating).
    "i2c_hat": i2c_hat,
    # The movement verbs and the Drive instrument are NOT here —
    # drive.attach() puts them in, so the verbs and the thing that scores
    # them can never come apart.
}

DEFAULT_INSTINCT = """
async def run():
    stop()
    while True:
        send("state=idle")
        await asyncio.sleep(5)
"""

async def run_instinct(code):
    env = dict(INSTINCT_ENV)
    # The body verbs and the Drive instrument. Module state survives hot-swaps
    # (drive is imported once); attach re-binds the read facade onto the
    # fresh scope exactly as the sim harness does.
    try:
        drive.attach(env)
    except Exception as e:
        send("CRASH:drive:{}".format(e))
        print("drive: attach error:", e)
    # Which instinct am I? Compared against a version the creature stored for
    # itself, this tells a REWRITE (version changed) from a re-push or a
    # reconnect (identical). 0 = the seed, before any IV: arrived.
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
    if current_task:
        current_task.cancel()
        try:
            await current_task
        except asyncio.CancelledError:
            pass
    # Always start a fresh instinct from a stopped body. (robot-bug still
    # calls robot_dog's center_all() here, which does not exist on a wheeled
    # runtime — every swap there raises NameError before the new code runs.)
    drive.stop()
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
    drive.stop()
    try:
        Speaker.end()
    except Exception:
        pass
    print("session: cleaned up")


async def heartbeat():
    global _ctl_active, _ctl_vec
    last_hb = 0
    while True:
        M5.update()
        # THE LOOP. Drive is fed here, by the body, and never by the
        # instinct — an instinct that could write its own achieved rotation
        # could tell itself it drove beautifully into a wall. 20 Hz is ample
        # for integrating a turn that takes seconds, and this loop already
        # exists: its death is fatal and visible, so this adds no new silent
        # failure mode of the kind a separate pump would.
        try:
            drive._drive.feed(Imu.getAccel(), Imu.getGyro(),
                               time.ticks_ms() / 1000.0)
        except Exception as e:
            print("drive: feed error:", e)
        # THE DEADMAN. Nobody has said anything for CTL_DEADMAN_MS and the
        # operator was the one driving: stop. This is what makes a LATCHED
        # joystick safe — the rover keeps rolling when you let go of the key,
        # but not when the tuner quits, the laptop sleeps or the wifi drops.
        # Only ever cancels the operator's own commands; an instinct driving
        # itself is none of its business.
        if _ctl_active and _ctl_last is not None and \
                time.ticks_diff(time.ticks_ms(), _ctl_last) > CTL_DEADMAN_MS:
            _ctl_active = False
            _ctl_vec = (0, 0, 0)
            drive.stop()
            send("LOG: operator link went quiet — motors stopped (deadman)")
        await asyncio.sleep(0.05)
        # Remember the last send; do NOT test the clock. `(ticks_ms()//1000) %
        # HEARTBEAT_INTERVAL == 0` is true for a whole SECOND and this loop
        # runs every 50 ms, so it sent 20 heartbeats per interval — 240 a
        # minute instead of 12. On a rover, which is always on its own
        # battery and already spends 200-280 mA on motors, that is a 20x
        # multiplier on the most expensive thing the radio does.
        if time.ticks_diff(time.ticks_ms(), last_hb) > HEARTBEAT_INTERVAL * 1000:
            last_hb = time.ticks_ms()
            try:
                if ws:
                    ws.send("HEARTBEAT")
            except:
                pass


def _set_clock(msg):
    """TIME:<unix_s>:<gmtoff_s> — the laptop's clock, via the spine. Sets the
    RTC, which survives a reconnect but not a power-off; every connect
    re-syncs. This is what lets the creature journal the hour instead of a
    boot-relative t+Nm."""
    global _clock_set
    try:
        u, off = msg[5:].split(":")
        # The epoch is a BUILD property, not a given: MicroPython ports use
        # 2000-01-01, others (and some M5 builds) the unix 1970 epoch.
        # Guessing wrong shifts the DATE by exactly 10957 days — a whole
        # number, so hour:minute still read correctly while the YEAR lands in
        # 1996, and anything gated on localtime()[0] >= 2020 fails silently.
        # Detect it instead of assuming.
        epoch_off = 946684800 if time.gmtime(0)[0] == 2000 else 0
        local = int(u) + int(off) - epoch_off
        tm = time.gmtime(local)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        _clock_set = True
        print("clock: {:02d}:{:02d}".format(tm[3], tm[4]))
    except Exception as e:
        print("clock: set failed:", e)


def _boot_line(reason, down_s=None):
    # The spine reads mode=, iv=, uptime= and keepalive= out of this line, and
    # detects the announce with startswith("BOOT:") — so no prefix, and the
    # clock token goes LAST. A missing mode= silently costs us the clock (the
    # spine gates TIME: on it, since older runtimes would exec it as code).
    clock = (" clock={:02d}:{:02d}".format(*time.localtime()[3:5])
             if _clock_set else "")
    return ("BOOT: cause={} uptime={}s vbat={}mV vbus={}mV charging={} "
            "mode={} keepalive={} iv={} wake={}".format(
                _RESET_CAUSES.get(_rc, _rc), time.ticks_ms() // 1000,
                M5.Power.getBatteryVoltage(), M5.Power.getVBUSVoltage(),
                M5.Power.isCharging(),
                "live", HEARTBEAT_INTERVAL, instinct_version, reason)
            + ("" if down_s is None else " down={}s".format(down_s))
            + clock)


async def _handle_msg(msg):
    """One spine message: session bookkeeping, an IV/TIME tag, or instinct."""
    global last_session_id, instinct_version, _pending_iv
    if msg == "NAP":
        # This runtime never sleeps, so a NAP is not for us — but it must be
        # RECOGNISED, because anything unrecognised is exec'd as instinct code
        # and would kill the running creature with a NameError.
        print("ignoring NAP (live runtime)")
        return
    if msg.startswith("SESSION:"):
        sid = msg[len("SESSION:"):]
        if last_session_id is not None and last_session_id != sid:
            await session_start_cleanup()
            instinct_version = 0        # new session: our instinct is stale
        last_session_id = sid
        print("session: {}".format(sid))
        return
    if msg.startswith("IV:"):
        _pending_iv = int(msg[3:])
        return
    if msg.startswith("TIME:"):
        _set_clock(msg)
        return
    if msg.startswith("CTL:"):
        # The operator's hand, not code. Must be recognised BEFORE the exec
        # fallback below, or a joystick keystroke would be run as instinct.
        _handle_ctl(msg[4:])
        return
    # Adopt the version BEFORE the swap: run_instinct puts it in the instinct
    # scope, and a creature reading its own version one behind cannot tell a
    # real rewrite from a re-push of the code it is already running.
    if _pending_iv is not None:
        instinct_version = _pending_iv
        _pending_iv = None
    await swap_instinct(msg)


async def ws_listener():
    global ws, _connects
    print("ws: connecting to {}:{}".format(SPINE_HOST, SPINE_PORT))
    ws = WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    # Announce on EVERY connect. wake= says why this one happened, because
    # uptime= alone makes a reconnect read as a power-on, and cause= is frozen
    # at the last real reset.
    if _connects == 0:
        ws.send(_boot_line("poweron"))
    else:
        # ticks_ms is a WRAPPING counter (~12.4 days on ESP32) — plain
        # subtraction goes hugely negative across the wrap. ticks_diff is the
        # only correct way to take a difference of two of them.
        down = (0 if _link_down_ms is None
                else max(0, time.ticks_diff(time.ticks_ms(), _link_down_ms) // 1000))
        ws.send(_boot_line("reconnect", down_s=down))
    _connects += 1
    # Anything journalled while the link was down goes out now, timestamped
    # when it happened. Must follow the BOOT line: the spine reads BOOT out of
    # the first frame, and a J: arriving first would cost us the clock.
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
