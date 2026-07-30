"""
main.py — M5StickS3 + PuppyC HAT + thermal/ToF runtime (robot_dog 3_interaction).

The merge: 1_action's legs and 2_perception's senses on one body, which is the
first robot_dog stage that can both perceive at a distance AND act on what it
perceives. Two I2C buses coexist:

  SoftI2C(scl=0, sda=8) @0x38   the PuppyC HAT — four single-DOF legs
  I2C(0, sda=9, scl=10)         the Grove bus — VL53L0X @0x29 (nose beam)
                                and M5 Thermal2 @0x32 (32x24 MLX90640)

Runtime-owned, surviving every instinct hot-swap:

  PERCEPTION PUMP   thermal frame -> largest warm blob (area, centroid,
                    excess degC) + ToF mm, exposed as the Thermal and ToF
                    organs and streamed to the stethoscope. The frame itself
                    is DISCARDED: no instinct can ask for pixels, and the
                    display is dark. Instincts read percepts; they never
                    touch the bus.
  LEGS              the gait as an organ. Instincts COMMAND a mode
                    (forward / back / turn / stop) and the organ runs the
                    stride, counts cycles, and refuses to exceed the gentle
                    envelope. It also holds the tip guard, which is a
                    constitutional guardrail and therefore lives where an
                    instinct cannot remove it.

What this stage deliberately does NOT have yet, because it is blocked on
measurement (see README "What we are missing"): the Proxemics organ, the
efference-corrected HUMAN_* token vocabulary, and the act-sequence grammar.
Legs.cycles() and Legs.since_still_ms() are the raw material for those; the
honest tokens cannot be minted until mm/cycle and deg/cycle are measured on
this body. Until then instincts read raw percepts and say what they see.

Gait envelope, measured 2026-07-30 on this chassis with the camera upright:
amplitude 30deg, period 1000ms, stance_duty 0.65, straight-ramp stride,
amplitude eased in over two cycles. The camera makes this a tall inverted
pendulum; the old 40/500 tips it, and smoothing the stride made tipping
WORSE (a smooth reversal dwells at the extreme leg angle). Period is the
gentleness lever. Turning scrubs the feet sideways, so it fights friction
and is the most tip-prone move in the vocabulary.
"""

import M5
from M5 import *
import time
import machine

# Why did we boot? Decisive when hunting spontaneous resets: watchdog vs
# brownout vs power-on look identical from outside. Read before M5.begin().
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
import uselect
import uerrno
import ubinascii
import uos
import struct
import math
from machine import Pin, I2C, PWM, SoftI2C

# ── PuppyC bus + helpers ────────────────────────────────────────────────────
# Lifted verbatim from 1_action (the no-sharing convention: each stage folder
# is self-contained). The HAT is on SoftI2C GPIO0/8 and does not collide with
# the Grove bus below.

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

# UIFlow firmware doesn't put /flash/lib on sys.path by default. Our flashed
# creature drivers land there (lib/*.py -> /lib/ via mpremote, which is
# /flash/lib/ at runtime), so insert it before importing.
import sys as _sys
if "/flash/lib" not in _sys.path:
    _sys.path.insert(0, "/flash/lib")

# ── The stethoscope: the pump's percepts as an EEG, over UDP-OSC ───────────
# Advisory and lossy by contract. With the panel dark this is the ONLY live
# view of the percepts: `stetho` on the laptop sparklines the last 48 samples,
# which is the instrument the blob-flicker question actually needed anyway
# (area flicker at a FIXED pose is the noise floor a later Warmth organ must
# absorb, and a noise floor is a distribution over time — never readable off a
# number that repaints 8x/s). Detached = no-ops, so a missing driver or a dead
# radio costs the pump nothing.
try:
    from stethoscope import tap as _tap, probe as _probe
except ImportError:
    def _tap(kind, **payload):
        pass

    def _probe(name, value):
        pass

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

# ── The sense organs ───────────────────────────────────────────────────────
# Two objects, in the shape of M5's own `Imu`: module-level state the pump
# writes and instincts only read, surviving every hot-swap, unfeedable.
#
# THE THERMAL IMAGE IS NOT PART OF THE API. The pump reduces 768 pixels to
# one warm SHAPE and throws the frame away. An instinct cannot ask for pixels,
# because a creature that can see an image will start reasoning about images —
# and this body's epistemology is "a warm shape, this big, there", nothing
# more. The image is also gone from the display: the screen stays dark (the
# camera mount covers it anyway, and the backlight is battery money). The
# diagnostic channels are the serial `perc:` line and the stethoscope.

# Beyond this the VL53L0X is not reporting a distance, it is reporting that it
# failed: readings run to the ~8190 mm sentinel, and even below that this
# sensor's honest ceiling in the default profile is well under 2 m. For a
# tabletop creature whose furthest zone is 900 mm, anything past here means
# "nothing there" — so it is reported as no echo rather than as a big number.
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
        """Millimetres along the forward beam: ~30 very close, ~2000+ open
        space, 0 = no echo at all, None = no sensor. The beam is NARROW and
        can miss entirely what the thermal sense plainly sees."""
        return _dist_mm

    def age_ms(self):
        """How stale the reading is. The pump cycles the sensor at ~10 Hz."""
        return time.ticks_diff(time.ticks_ms(), _dist_t)


Thermal = _Thermal()
ToF = _ToF()


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


# ── The display: dark ──────────────────────────────────────────────────────
# The screen is OFF on this stage, deliberately. The camera mount covers it,
# the backlight is a steady ~10-20 mA of battery, and the thermal image it used
# to show is no longer something this creature is allowed to have (see the
# organ note above). Nothing paints anything after boot.
#
# What replaced it: the serial `perc:` line once a second, and the stethoscope
# (UDP-OSC :9001 -> `stetho` on the laptop), which sparklines the same percepts
# over time and is a better instrument than the panel ever was.
#
# _head() is kept as a no-op sink so the connect/disconnect call sites read the
# same as the other stages; it prints instead of drawing.


def _display_off():
    try:
        M5.Widgets.fillScreen(0x000000)
        M5.Display.setBrightness(0)
        print("display: off (dark by policy)")
    except Exception as e:
        print("display: could not blank:", e)


def _head(text):
    print("head: {}".format(text))


# ── The perception pump ────────────────────────────────────────────────────

async def perception_pump():
    global _warm, _delta_c, _dist_mm, _dist_t

    if not _thermal_ok:
        print("thermal: ABSENT — blob() will report present=False forever")

    frame = [0] * 768        # persistent full frame, half refreshed per subpage
    have = [False, False]    # which subpages have arrived at least once
    disp_lo = None
    disp_hi = None
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
                    set_warm_delta(d)
                    break
            else:
                set_warm_delta(DELTAS[0])

        # ── ToF: non-blocking single-shot cycle, throttled to ~10 Hz ──────
        if _tof:
            try:
                if _tof.range_started:
                    if _tof.reading_available():
                        raw = _tof.get_range_value()
                        # THE SENTINEL. The driver hands back the range register
                        # verbatim with no range-status check, and the VL53L0X
                        # parks at ~8190/8191 mm when it gets no valid return.
                        # That is NOT a distance — left raw it reads as "the
                        # target is eight metres away", which is how a
                        # distance-holding behaviour ends up marching forward
                        # until it falls over (observed 2026-07-30: err=+8091mm,
                        # forward, forward, tipped).
                        #
                        # Collapse it to 0, which is already this runtime's
                        # documented "no echo". One representation of "the beam
                        # got nothing", fixed here rather than rediscovered by
                        # every behaviour downstream.
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

        # The autoscale that used to drive the image is gone with it — nothing
        # here needs a display range any more. The raw frame is reduced to one
        # blob below and then discarded; it never leaves this function.

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
        # Throttled to ~4 Hz. The pump runs at ~8 subpages/s and each probe is
        # its own datagram, so probing every pass would put ~50 packets/s on
        # the air for no extra insight — 4 Hz still resolves flicker, and the
        # 48-sample sparkline then spans 12 s.
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
                # Horizontal EXTENT of the shape, not just its centre: the
                # stetho radar draws x0..x1 across the frame width so a hand
                # moving left/right is visible as the span sliding, and a hand
                # arriving is visible as the span widening. The centroid alone
                # cannot distinguish "moved left" from "grew to the left".
                # blob = (area, cx, cy, excess, x0, y0, x1, y1)
                if blob:
                    _probe("blob_x0", blob[4])
                    _probe("blob_x1", blob[6])
            _probe("tof_mm", mm_s)
            if _warm["present"] != _warm_was[0]:
                # The first pass establishes the baseline; only a real FLIP is
                # an event. Otherwise every boot into an empty room announces
                # a departure that never happened.
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
            # Slow levels ride the same 1 Hz beat as the serial line: ambient
            # drift is what silently moves the threshold under everything
            # else, and fps says whether the eye is keeping up at all.
            _probe("ambient_c", celsius(med))
            _probe("delta_c", _delta_c)
            _probe("fps", fps)
            subpages = 0
            last_stat = now


# ── The Legs organ ─────────────────────────────────────────────────────────
# The gait, owned by the runtime. Module-level state, so it survives instinct
# hot-swaps; read-only from inside an instinct except through the four command
# methods; unfeedable. Instincts declare a MODE and the organ runs the stride.
#
# Why an organ and not a helper an instinct copies in: three things belong
# here and nowhere else.
#
#   1. The gentle envelope. Amplitude and period are capped (see the module
#      docstring for the measurements). `pace` scales within the envelope, it
#      does not escape it — an unbounded pace on this tall chassis is a way to
#      fall over, and that must not be one rewrite away.
#   2. The tip guard. constitution.md is fixed and the soul may not revise it,
#      so its safety clause is implemented where an instinct cannot reach:
#      past TIP_SIN of tilt, HELD for TIP_PERSIST_MS, the legs centre
#      themselves and the body says so.
#   3. The efference log. cycles() and since_still_ms() are what a later
#      Proxemics organ subtracts to tell "the human moved" from "I moved".
#      Nothing can attribute motion honestly if the motor record lives inside
#      a coroutine that gets cancelled on every rewrite.

GAIT_AMP = 30            # degrees, ceiling. 40 tips this chassis.
GAIT_PERIOD_MS = 1000    # per stride cycle, floor. Shorter tips this chassis.
GAIT_DUTY = 0.65         # stance fraction. NEVER 0.5 — a symmetric stride
                         # nets zero force and translates nowhere.
GAIT_RAMP_CYCLES = 0.4   # ease amplitude in; a full-stride first step lurches.
                         # MUST stay well under the shortest phrase anything
                         # commands. The ramp scales amplitude by
                         # min(1, cycles/RAMP), so a phrase that ENDS inside
                         # the ramp never reaches full stride: at 2.0 (the
                         # first value here) a 0.6-cycle turn phrase peaked at
                         # 5.4 deg and the dog merely twitched, while the
                         # tuner's continuous `turn` worked fine because it
                         # ramped all the way in. 0.4 cycles = 400 ms of
                         # easing, which is all the lurch protection needs.
GAIT_DT_MS = 20
PACE_MIN = 0.35          # below this the legs lack the authority to move us
# ── The tip guard's thresholds ─────────────────────────────────────────────
# These are the SINE OF THE TILT ANGLE, not a raw acceleration magnitude:
# horizontal / total, which cancels the overall scale. That distinction is the
# whole fix for a false trip. A stride shakes every axis at once, so the raw
# horizontal number inflates while the body is perfectly upright — the first
# version of this guard used |ax,ay| and fired at tilt=0.56 mid-walk with the
# dog still on its feet (observed 2026-07-30), then cleared to 0.08 a moment
# later. Dividing by |a| asks about ORIENTATION instead of shaking.
TIP_SIN = 0.55           # sin(33 deg) — going over
TIP_CLEAR_SIN = 0.35     # sin(20 deg) — hysteresis, call it recovered
# And it must HOLD. A real tip develops over the pendulum time constant
# (~100 ms here) and then stays over; a stride transient is one or two ticks.
# Requiring persistence is what separates them, and it is free.
TIP_PERSIST_MS = 200
TIP_SMOOTH = 4           # samples averaged before the test, to kill spikes


class _Legs:
    def __init__(self):
        self._mode = "still"      # still | forward | back | cw | ccw
        self._pace = 1.0
        self._t0 = time.ticks_ms()      # when this mode started
        self._still_since = time.ticks_ms()
        self._cycles = 0.0
        self._tipped = False
        self._tilt = 0.0          # smoothed sin(tilt angle)
        self._over_since = None   # when the tilt first crossed, for persistence
        self._probe_t = time.ticks_ms()   # last stethoscope emission

    # ── commands (the only writable surface) ──────────────────────────────
    def _set(self, mode, pace):
        pace = PACE_MIN if pace < PACE_MIN else (1.0 if pace > 1.0 else pace)
        if mode == self._mode and abs(pace - self._pace) < 0.01:
            return                      # idempotent: don't restart the stride
        if self._tipped and mode != "still":
            return                      # the guard holds until we are upright
        self._mode = mode
        self._pace = pace
        self._t0 = time.ticks_ms()
        self._cycles = 0.0
        if mode == "still":
            self._still_since = time.ticks_ms()
            # Return to a neutral stance. Without this the loop simply stops
            # writing servos and the legs FREEZE wherever the stride left them
            # — standing crooked on an asymmetric stance, which is less stable
            # on a top-heavy body and makes the next phrase jerk out of a
            # random pose. It also meant every "stand still and look" happened
            # while standing lopsided.
            center_all()

    def forward(self, pace=1.0):
        self._set("forward", pace)

    def back(self, pace=1.0):
        self._set("back", pace)

    def turn(self, direction, pace=1.0):
        """direction: "cw" or "ccw". Turning scrubs the feet sideways, so it
        fights friction and is the most tip-prone move — pace down for it."""
        self._set("ccw" if str(direction).lower() == "ccw" else "cw", pace)

    def stop(self):
        self._set("still", 1.0)

    # ── poses and expression ──────────────────────────────────────────────
    # Named shapes rather than four magic numbers every instinct has to
    # rediscover. Each stops the gait first: the stride is a background task
    # and would otherwise walk straight out of the pose.

    POSE_STAND = (90, 90, 90, 90)
    POSE_SIT = (90, 90, 50, 50)      # front centred, rear folded back
    POSE_REST = (30, 30, 30, 30)     # legs out to the sides; unloads the servos

    def stand(self):
        self.stop()
        set_all(*self.POSE_STAND)

    def sit(self):
        self.stop()
        set_all(*self.POSE_SIT)

    def rest(self):
        """Down on the belly, legs splayed. The only pose that takes the load
        off the servos — the one to hold if you mean to be still a while."""
        self.stop()
        set_all(*self.POSE_REST)

    async def wiggle(self, amp=20, cycles=3.0, period_ms=600, leg=None):
        """Expressive motion that travels NOWHERE — the one thing a rover
        cannot do. It works precisely BECAUSE it is symmetric: a symmetric
        sweep nets zero force over a cycle, so the body wags without going
        anywhere. The same physics that makes a symmetric stride useless for
        walking makes it the right shape for a wag.

        leg=None wags the whole body (diagonal pairs in antiphase);
        leg=FL/FR/BL/BR wags that one leg — the paw-wave shape.

        Amplitude is capped at the gait envelope: a big fast wag tips this
        chassis over exactly as well as a big fast stride does. A COROUTINE —
        await it. Returns the legs to centre when it finishes."""
        self.stop()
        amp = GAIT_AMP if amp > GAIT_AMP else (2 if amp < 2 else amp)
        period_ms = 200 if period_ms < 200 else period_ms
        steps = int(cycles * period_ms / GAIT_DT_MS)
        for i in range(steps):
            if self._tipped:
                break
            v = amp * math.sin(2 * math.pi * i * GAIT_DT_MS / period_ms)
            if leg is None:
                set_all(90 + v, 90 - v, 90 - v, 90 + v)
            else:
                set_leg(leg, 90 + v)
            await asyncio.sleep_ms(GAIT_DT_MS)
        center_all()

    # ── percepts (what an instinct may read) ──────────────────────────────
    def mode(self):
        return self._mode

    def pace(self):
        return self._pace

    def moving(self):
        return self._mode != "still"

    def cycles(self):
        """Completed stride cycles since the current mode began. With a
        measured mm/cycle this becomes distance travelled; until then it is
        an honest count of strides and nothing more."""
        return self._cycles

    def since_still_ms(self):
        """How long since the legs last stopped. The efference gate: the
        thermal centroid sloshes and the ToF beam pitches while we walk, so a
        percept is only trustworthy some settling time after this passes."""
        return time.ticks_diff(time.ticks_ms(), self._still_since)

    def tipped(self):
        return self._tipped

    # ── the stride ────────────────────────────────────────────────────────
    def _phase(self, t, amp):
        u = t % 1.0
        if u < GAIT_DUTY:
            u = u / GAIT_DUTY               # slow stance: the propulsive push
        else:
            u = (u - GAIT_DUTY) / (1 - GAIT_DUTY)   # fast swing: unloaded
            amp = -amp
        # Straight ramp, deliberately. A cosine reverses smoothly but DWELLS at
        # the extreme leg angle, and on this tall body the dwell outlasts the
        # pendulum time constant and tips us. Measured 2026-07-30.
        return amp - 2 * amp * u

    def _read_tilt(self):
        """sin(tilt angle), smoothed. Horizontal over TOTAL magnitude, so the
        answer is about orientation and not about how hard we are shaking."""
        ax, ay, az = Imu.getAccel()
        mag = (ax * ax + ay * ay + az * az) ** 0.5
        if mag < 0.2:
            return self._tilt          # freefall or a bad read: keep the last
        s = ((ax * ax + ay * ay) ** 0.5) / mag
        # exponential average over ~TIP_SMOOTH samples
        k = 1.0 / TIP_SMOOTH
        self._tilt += (s - self._tilt) * k
        return self._tilt

    async def run(self):
        while True:
            now = time.ticks_ms()
            tilt = self._read_tilt()

            if tilt > TIP_SIN:
                if self._over_since is None:
                    self._over_since = now
            else:
                self._over_since = None

            # Fire only once the tilt has HELD past the threshold. A stride or
            # a turn spikes it for a tick or two while the body is fine; going
            # over actually stays over.
            over_held = (self._over_since is not None
                         and time.ticks_diff(now, self._over_since) >= TIP_PERSIST_MS)

            if not self._tipped and over_held:
                # A guardrail, not a behaviour: centre the legs and say so.
                self._tipped = True
                self._mode = "still"
                self._still_since = now
                center_all()
                send("tipped: tilt={:.2f} held {}ms — legs centred".format(
                    tilt, TIP_PERSIST_MS), urgent=True)
                _tap("tipped", tilt=round(tilt, 2))
                reflect("I went over (tilt {:.2f}) and stopped my legs. Whatever "
                        "I was doing, my body cannot do it from here.".format(tilt))
            elif self._tipped and tilt < TIP_CLEAR_SIN:
                self._tipped = False
                self._over_since = None
                send("upright again: tilt={:.2f}".format(tilt))

            # Put tilt on the stethoscope at ~5 Hz. TIP_SIN is still a guess,
            # and this is how it stops being one: walk, turn, and read off how
            # high the trace actually goes with the body upright. The threshold
            # belongs just above that, not wherever it was first written.
            if time.ticks_diff(now, self._probe_t) >= 200:
                self._probe_t = now
                _probe("tilt", tilt)
                _probe("legs", 0.0 if self._mode == "still" else self._pace)

            if self._mode == "still" or self._tipped:
                await asyncio.sleep_ms(GAIT_DT_MS)
                continue

            t = time.ticks_diff(time.ticks_ms(), self._t0) / float(GAIT_PERIOD_MS)
            self._cycles = t
            amp = GAIT_AMP * self._pace
            g = min(1.0, t / GAIT_RAMP_CYCLES)
            if self._mode == "forward":
                a = g * self._phase(t, amp)
                b = g * self._phase(t + 0.5, amp)
                set_all(90 + a, 90 + b, 90 + b, 90 + a)
            elif self._mode == "back":
                a = g * self._phase(t, -amp)
                b = g * self._phase(t + 0.5, -amp)
                set_all(90 + a, 90 + b, 90 + b, 90 + a)
            else:
                # Differential stride: left legs one way, right legs the other,
                # diagonal trot pairing preserved (FL+BR on t, FR+BL on t+0.5).
                # Determined empirically on the hardware, 2026-07-30. Driving
                # the LEFT legs propulsively forward and the RIGHT legs
                # backward tank-steers the body to its RIGHT — clockwise seen
                # from above. This originally read `1 if "ccw"`, which mirrored
                # every turn: asking for cw turned ccw. The word is the
                # creature's, so its meaning is fixed HERE, once.
                s = -1 if self._mode == "ccw" else 1
                al, ar = s * amp, -s * amp
                set_all(90 + g * self._phase(t,       al),
                        90 + g * self._phase(t + 0.5, ar),
                        90 + g * self._phase(t + 0.5, al),
                        90 + g * self._phase(t,       ar))
            await asyncio.sleep_ms(GAIT_DT_MS)


Legs = _Legs()


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

STETHO_HOST = "spine"   # the organ stream (UDP-OSC :9001 — advisory, lossy).
                        # "spine": arm toward SPINE_HOST at every radio-up;
                        # an "x.x.x.x" string: toward that host; None: stay
                        # detached. Attach state is RAM-only and a radio
                        # bounce kills the socket, hence re-arm on radio-up.
                        # Run `stetho` on the laptop to watch it.


def _arm_stetho():
    """(Re)arm the organ stream per the STETHO_HOST policy. Never raises: the
    stethoscope keeps its target and heals its own socket once the radio is
    back, and with no driver flashed the probes are already no-ops."""
    if not STETHO_HOST:
        return
    try:
        import stethoscope
        stethoscope.attach(SPINE_HOST if STETHO_HOST == "spine" else STETHO_HOST)
        print("stetho: armed -> {}:9001".format(
            SPINE_HOST if STETHO_HOST == "spine" else STETHO_HOST))
    except Exception as e:
        print("stetho: arm failed:", e)

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
# blip silently swallows everything it journalled during the outage. This
# stage is especially exposed: WiFi failure is non-fatal here, so the pump and
# the instinct run happily with no link at all.
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
    # ── the senses, as organs ─────────────────────────────────────────────
    # Deliberately NOT here: the thermal frame, and any way to draw it. The
    # pump reduces 768 pixels to one warm shape and discards the rest, so an
    # instinct cannot reason about an image even if a rewrite wants to.
    "Thermal": Thermal,
    "ToF": ToF,
    # ── motion ────────────────────────────────────────────────────────────
    # Legs is the rung to write against: command a mode or a pose, read the
    # efference back. set_leg/set_all are the lower rung, for a shape the
    # named moves cannot make.
    "Legs": Legs,
    "set_leg": set_leg,
    "set_all": set_all,
    "center_all": center_all,
    "FL": FL, "FR": FR, "BL": BL, "BR": BR,
    "CENTER": CENTER,
    # The live trim table. Here for the tuner's autotrim/trimdump, which have
    # to read and rewrite it; a creature has no reason to touch it.
    "TRIM": TRIM,
}

DEFAULT_INSTINCT = """
async def run():
    Legs.stop()
    while True:
        b = Thermal.blob()
        send("idle warm={} tof={} legs={}".format(
            b["present"], ToF.read_distance_mm(), Legs.mode()))
        await asyncio.sleep(5)
"""

async def run_instinct(code):
    env = dict(INSTINCT_ENV)
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
    # A cancelled instinct leaves the legs wherever its last command put them,
    # and the Legs organ would happily keep striding on behalf of code that no
    # longer exists. Stop before the next instinct starts: a rewrite should
    # begin from stillness, not inherit a gait it never asked for.
    Legs.stop()
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
    Legs.stop()
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
    ws = await WebSocket.connect(SPINE_HOST, SPINE_PORT)
    print("ws: connected")
    _head("spine ok  " + SPINE_HOST)
    # The radio is up and the target may have changed under us — re-arm the
    # organ stream here as well as at boot, since a socket does not survive a
    # WiFi bounce and the pump's probes would go quietly nowhere.
    _arm_stetho()
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
    asyncio.create_task(perception_pump())
    # The gait runs as its own task, independent of whichever instinct is
    # loaded — that is what makes it survive a hot-swap and what lets the tip
    # guard keep working while a crashed instinct is being replaced.
    asyncio.create_task(Legs.run())
    await swap_instinct(DEFAULT_INSTINCT)
    asyncio.create_task(heartbeat())
    while True:
        try:
            await ws_listener()
        except Exception as e:
            print("ws: error:", e)
        globals()["_link_down_ms"] = time.ticks_ms()
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

# The screen is dark on this stage by policy — see the display note above.
_display_off()

# Arm the organ stream at boot, not only at ws-connect: the stethoscope is now
# the only live view of the percepts, since the panel no longer shows them.
_arm_stetho()

asyncio.run(main())
