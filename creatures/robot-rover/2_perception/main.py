"""
main.py — M5StickS3 + RoverC + ToF/thermal runtime (robot-rover 2_perception).

Forked from creatures/robot-rover/1_action/main.py (2026-08-24): the same
motion runtime — CTL joystick, deadman, journal, the Drive instrument fed from
heartbeat() — with the senses added, the way robot_dog grew them:

  VL53L0X ToF @0x29             one narrow beam straight ahead, millimetres
  M5 Thermal2 @0x32 (MLX90640)  32x24, reduced by the pump to one warm blob

WHERE THE SENSORS PLUG IN IS NOT ASSUMED. robot_dog's live on the stick's own
Grove pins, I2C(0, sda=9, scl=10, 400kHz). This rover's chassis has Grove
ports of its own which may instead sit on the HAT bus (SoftI2C scl=0, sda=8,
100kHz, shared with the motors at 0x38). Boot scans BOTH buses and binds each
sensor to whichever one it answered on — the tuner's `scan` recipe shows the
same picture live. A thermal camera landing on the 100kHz SoftI2C bus is
legal but slow (768-byte frames); the boot log says so when it happens.

THE LOOP, WIDENED. Stage 1 scored every motor command off the IMU: turned,
dps, stir, stalled. Rotation was measured; translation was only witnessed.
This stage hands lib/drive.py a ranger (set_ranger, mirroring set_writer), so
every bout is also bracketed with the beam's range at its start and end —
mm0, mm1, mm — whenever the beam has a fresh echo at both. Point this body at
a wall and its straight lines become measurable for the first time. The
perception pump owns the sensors; instincts read percepts, never devices.

Runtime provides to instinct code:
  send(msg)        write a journal line (costs nothing, does NOT summon)
  reflect(reason)  ask the soul to think, and say why (the only summons)
  forward/backward/slide_left/slide_right/cw/ccw/move/stop, Drive
                                           via drive.attach
  Thermal, ToF     the two senses, percepts maintained by the pump
  mem              one dict that survives a rewrite and dies with the power
  asyncio, Pin, I2C, PWM, SoftI2C, time, struct, math, M5, Imu,
  Speaker, Widgets, i2c_hat, i2c_grove

Device-side libraries flashed to /lib (creatures/robot-rover/2_perception/lib/*.py):
  drive.py         -> attach(scope) (the Drive instrument + the motor verbs)
  vl53l0x_nb.py    -> the non-blocking VL53L0X driver (robot_dog's, verbatim)
  stethoscope.py   -> the bench organ stream (detached unless armed)

CALIBRATION CARRIES OVER from 1_action: MOTOR_CORNER, MOTOR_SIGN and the spin
SPEED_FLOOR=21 were measured 2026-08-15 and live in lib/drive.py. What is NOT
yet measured is everything the beam makes measurable — mm/s per speed, the
straight-line stiction floor, the minimum step, the coast — and the tuner's
wall-bench recipes (`wall`, `step`, `vfloor`, `hold`) exist to measure them.
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


# ── The senses, on whichever bus they answer ────────────────────────────────
#
# Ported from robot_dog/3_interaction (2026-08-24), with one rover-specific
# twist: robot_dog's sensors are plugged into the STICK's Grove port, which is
# the hardware I2C(0) on sda=9/scl=10. This chassis has Grove ports of its
# own, and where THOSE are wired is not something to assume — so both buses
# are scanned and each sensor is bound to the one it answered on. NOTE: bus 1
# is reserved by the M5 internal IMU (see puppyc main.py for the OSError(261)
# story).

# The pump narrates itself to the stethoscope. Detached = no-ops, so a
# missing driver or a dead radio costs it nothing (drive.py makes the same
# bargain for itself).
try:
    from stethoscope import tap as _tap, probe as _probe
except ImportError:
    def _tap(kind, **payload):
        pass

    def _probe(name, value):
        pass

THERMAL_ADDR = 0x32
TOF_ADDR = 0x29

i2c_grove = I2C(0, sda=Pin(9), scl=Pin(10), freq=400000)

try:
    _found_grove = i2c_grove.scan()
except Exception as _e:
    print("grove: scan failed:", _e)
    _found_grove = []
try:
    _found_hat = i2c_hat.scan()
except Exception as _e:
    print("hat: scan failed:", _e)
    _found_hat = []
print("grove: i2c scan:", [hex(a) for a in _found_grove])
print("hat:   i2c scan:", [hex(a) for a in _found_hat])


def _find_bus(addr, name):
    """The stick's Grove bus first (400kHz hardware I2C), the HAT SoftI2C as
    the fallback — that is where a sensor plugged into the CHASSIS Grove
    ports may land, sharing 100kHz with the motor bytes."""
    if addr in _found_grove:
        print("{}: found at {} on the grove bus".format(name, hex(addr)))
        return i2c_grove
    if addr in _found_hat:
        print("{}: found at {} on the HAT bus (100kHz SoftI2C, shared with "
              "the motors)".format(name, hex(addr)))
        return i2c_hat
    print("{}: no {} on either bus".format(name, hex(addr)))
    return None


_thermal_bus = _find_bus(THERMAL_ADDR, "thermal")
_thermal_ok = _thermal_bus is not None
if _thermal_ok:
    if _thermal_bus is i2c_hat:
        print("thermal: WARNING — 768-byte frames over 100kHz SoftI2C are "
              "slow; the stick's own Grove port would be kinder")
    _thermal_bus.writeto_mem(THERMAL_ADDR, 0x0B, b"\x04")  # 8 Hz subpages -> ~4 full fps
    _thermal_bus.writeto_mem(THERMAL_ADDR, 0x6E, b"\x00")  # arm data-ready
    print("thermal: MLX90640 unit ready at 0x32")

_tof = None
_tof_bus = _find_bus(TOF_ADDR, "tof")
if _tof_bus is not None:
    try:
        from vl53l0x_nb import VL53L0X
        _tof = VL53L0X(_tof_bus, io_timeout_s=1)
        print("tof: VL53L0X ready at 0x29")
    except Exception as e:
        print("tof: init failed:", e)
        _tof = None

# ── The sense organs ───────────────────────────────────────────────────────
# Two objects, in the shape of M5's own `Imu`: module-level state the pump
# writes and instincts only read, surviving every hot-swap, unfeedable.
#
# THE THERMAL IMAGE IS NOT PART OF THE API. The pump reduces 768 pixels to
# one warm SHAPE and throws the frame away. An instinct cannot ask for pixels,
# because a creature that can see an image will start reasoning about images —
# and this body's epistemology is "a warm shape, this big, there", nothing
# more.

# Beyond this the VL53L0X is not reporting a distance, it is reporting that it
# failed: readings run to the ~8190 mm sentinel, and even below that this
# sensor's honest ceiling in the default profile is well under 2 m. Anything
# past here means "nothing there" — so it is reported as no echo rather than
# as a big number. (robot_dog learned this the hard way, 2026-07-30: the raw
# sentinel read as "eight metres away" and a distance-holder marched forward
# until it tipped.)
TOF_MAX_TRUST_MM = 2000

DELTAS = (1.5, 2.5, 4.0, 6.0)   # C above ambient; BtnA cycles
MIN_AREA = 2                     # px; reject single-pixel noise blobs

_warm = {"present": False, "area": 0, "cx": 0.0, "cy": 0.0,
         "excess_c": 0.0, "ambient_c": 0.0, "t_ms": 0}
_delta_c = DELTAS[1]
_dist_mm = None
_dist_t = 0


def celsius(raw):
    return raw / 128 - 64


class _Thermal:
    """The warm-shape sense. 32x24 MLX90640 behind the pump."""

    FRAME_W = 32
    FRAME_H = 24
    CENTRE_X = 15.5     # frame centre, for "is it ahead of me"

    def blob(self):
        """The largest warm shape in view, as a dict:

            present    a shape above threshold exists
            area       its size in pixels, of 768
            cx, cy     its excess-weighted centre (x 0..31, y 0..23)
            excess_c   how many degC above ambient it averages
            ambient_c  the frame's ambient temperature
            age_ms     how stale this is (<300 ms is fresh)

        A warm SHAPE in my camera frame — never a person, never a gaze."""
        d = dict(_warm)
        d["age_ms"] = time.ticks_diff(time.ticks_ms(), d.pop("t_ms"))
        return d

    def present(self):
        return _warm["present"]

    def ambient_c(self):
        return _warm["ambient_c"]

    def delta(self):
        """The current detection threshold, degC above ambient."""
        return _delta_c

    def set_warm_delta(self, c):
        """Detection threshold in degC above ambient (default 2.5). Lower
        catches distant people and more noise; higher rejects radiators and
        coffee cups along with faint real ones."""
        global _delta_c
        _delta_c = float(c)


class _ToF:
    """The nose beam. VL53L0X, one narrow ray straight ahead."""

    def read_distance_mm(self):
        """Millimetres along the forward beam: ~30 very close, up to ~2000 a
        real distance, 0 = no echo at all, None = no sensor. The beam is
        NARROW and can miss entirely what the thermal sense plainly sees."""
        return _dist_mm

    def age_ms(self):
        """How stale the reading is. The pump cycles the sensor at ~10 Hz."""
        return time.ticks_diff(time.ticks_ms(), _dist_t)


Thermal = _Thermal()
ToF = _ToF()

# The Drive instrument brackets every bout with the beam's range — installed
# here exactly like the motor writer, so the instinct can no more feed its
# own odometer than it can write its own achieved rotation.
drive.set_ranger(lambda: (None if _tof is None else
                          (_dist_mm, time.ticks_diff(time.ticks_ms(), _dist_t))))


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


# ── The perception pump ────────────────────────────────────────────────────
# One task, running regardless of WiFi/spine state. It owns the sensors;
# everything else reads the percepts it maintains. Ported from
# robot_dog/3_interaction, minus the Legs — this body's motion side is
# untouched by it.

async def perception_pump():
    global _warm, _delta_c, _dist_mm, _dist_t

    if not _thermal_ok:
        print("thermal: ABSENT — blob() will report present=False forever")
    if _tof is None:
        print("tof: ABSENT — read_distance_mm() will report None forever, "
              "and no bout will carry mm")

    frame = [0] * 768        # persistent full frame, half refreshed per subpage
    have = [False, False]    # which subpages have arrived at least once
    subpages = 0
    last_stat = time.ticks_ms()
    blob = None
    med = 0
    _stetho_t = time.ticks_ms()   # last organ-stream emission
    _warm_was = [None]            # presence at the last emission, for the tap

    while True:
        now = time.ticks_ms()

        if M5.BtnA.wasPressed():
            # cycle to the next delta above the current one (instincts may
            # have set an off-menu value; this snaps back onto the menu)
            for d in DELTAS:
                if d > _delta_c + 0.01:
                    Thermal.set_warm_delta(d)
                    break
            else:
                Thermal.set_warm_delta(DELTAS[0])

        # ── ToF: non-blocking single-shot cycle, throttled to ~10 Hz ──────
        if _tof:
            try:
                if _tof.range_started:
                    if _tof.reading_available():
                        raw = _tof.get_range_value()
                        # THE SENTINEL. The driver hands back the range
                        # register verbatim with no range-status check, and
                        # the VL53L0X parks at ~8190/8191 mm when it gets no
                        # valid return. That is NOT a distance. Collapse it to
                        # 0, this runtime's documented "no echo" — one
                        # representation of "the beam got nothing", fixed here
                        # rather than rediscovered by every behaviour
                        # downstream.
                        if raw is None or raw >= TOF_MAX_TRUST_MM:
                            _dist_mm = 0
                        else:
                            _dist_mm = raw
                        _dist_t = now
                elif time.ticks_diff(now, _dist_t) > 100:
                    _tof.start_range_request()
            except Exception as e:
                print("tof: cycle error:", e)

        if not _thermal_ok:
            await asyncio.sleep_ms(100)
            continue

        try:
            ctrl = _thermal_bus.readfrom_mem(THERMAL_ADDR, 0x6E, 2)
            if not (ctrl[0] & 0x01):
                await asyncio.sleep_ms(5)
                continue
            subpage = ctrl[1] & 1

            ov = struct.unpack("<HHHBBHBBHBB",
                               _thermal_bus.readfrom_mem(THERMAL_ADDR, 0x70, 16))
            med = ov[0]

            buf = _thermal_bus.readfrom_mem(THERMAL_ADDR, 0x80, 768)
            _thermal_bus.writeto_mem(THERMAL_ADDR, 0x6E, b"\x00")
        except Exception as e:
            print("thermal: read error:", e)
            await asyncio.sleep_ms(200)
            continue

        vals = struct.unpack("<384H", buf)
        for i in range(384):
            y = i >> 4
            frame[(y << 5) + ((i & 15) << 1) + ((y & 1) != subpage)] = vals[i]
        have[subpage] = True

        # give the ws/heartbeat tasks a slice between frames
        await asyncio.sleep_ms(0)

        # ── blob extraction (needs both subpages at least once) ────────────
        if have[0] and have[1]:
            thr_raw = med + int(_delta_c * 128)
            blob = largest_blob(frame, thr_raw, med)

        if blob:
            area, cx, cy, mexc, x0, y0, x1, y1 = blob
            _warm = {"present": True, "area": area, "cx": cx, "cy": cy,
                     "excess_c": mexc, "ambient_c": celsius(med), "t_ms": now}
        elif have[0] and have[1]:
            _warm = {"present": False, "area": 0, "cx": 0.0, "cy": 0.0,
                     "excess_c": 0.0, "ambient_c": celsius(med), "t_ms": now}

        # ── the stethoscope: the blob as levels, the flips as events ───────
        # Throttled to ~4 Hz — each probe is its own datagram, and 4 Hz still
        # resolves flicker while the 48-sample sparkline spans 12 s.
        if have[0] and have[1] and time.ticks_diff(now, _stetho_t) >= 250:
            _stetho_t = now
            mm_s = _dist_mm if _dist_mm is not None else -1
            _probe("area", _warm["area"])
            _probe("excess_c", _warm["excess_c"])
            # centroid only while there IS a blob: -1 would read as a real
            # excursion on the sparkline, which is a lie about the eye.
            if _warm["present"]:
                _probe("cx", _warm["cx"])
                _probe("cy", _warm["cy"])
                # Horizontal EXTENT, not just centre: the span sliding is a
                # hand moving; the span widening is a hand arriving.
                if blob:
                    _probe("blob_x0", blob[4])
                    _probe("blob_x1", blob[6])
            _probe("tof_mm", mm_s)
            if _warm["present"] != _warm_was[0]:
                # The first pass establishes the baseline; only a real FLIP is
                # an event.
                if _warm_was[0] is not None:
                    _tap("warm",
                         state="appeared" if _warm["present"] else "gone",
                         area=_warm["area"], exc=round(_warm["excess_c"], 1),
                         tof=mm_s, delta=_delta_c)
                _warm_was[0] = _warm["present"]

        subpages += 1
        dt = time.ticks_diff(now, last_stat)
        if dt >= 1000:
            fps = subpages * 500.0 / dt
            mm = _dist_mm if _dist_mm is not None else -1
            if blob:
                print("perc: amb={:.1f} d={:.1f} area={} exc={:.1f} cen=({:.1f},{:.1f}) tof={} fps={:.1f}".format(
                    celsius(med), _delta_c, blob[0], blob[3], blob[1], blob[2], mm, fps))
            else:
                print("perc: amb={:.1f} d={:.1f} no-blob tof={} fps={:.1f}".format(
                    celsius(med), _delta_c, mm, fps))
            _probe("ambient_c", celsius(med))
            _probe("delta_c", _delta_c)
            _probe("fps", fps)
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
    # the stick's Grove hardware bus, mostly so `scan` can ask both buses who
    # is home. The sensors themselves are NOT to be driven from instinct code
    # — the pump owns them; read Thermal and ToF instead.
    "i2c_grove": i2c_grove,
    # The two senses. Percepts the pump maintains; read-only, unfeedable.
    "Thermal": Thermal,
    "ToF": ToF,
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
    # The senses run regardless of WiFi/spine state: perception iteration
    # must not need a network.
    asyncio.create_task(perception_pump())
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
