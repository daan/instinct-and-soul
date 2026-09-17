"""drive.py — what this body did when it was told to move. (robot-rover)

The sibling of robot-bug's organ of the same job, on a body that can do one
more thing: a RoverC is four MECANUM wheels, so it can travel sideways without
turning, and turn without travelling. The triplet still closes inside one body:

    intent    "slide left at 40"
    action    four signed bytes to the RoverC at 0x38
    outcome   the IMU says how far the body ACTUALLY turned, and how much it
              was really shaken about

Every motor command is a small experiment, and this scores it without being
asked. One record per command:

    kind, speed, for_s     what was asked, and for how long
    turned                 degrees the body really rotated about the vertical,
                           SIGNED: + is clockwise seen from above
    stir                   how much it really shook
    stalled                commanded to move, and did not

WHY `turned` IS SIGNED HERE and was not on robot-bug. On a four-wheeled rover
with independent corners, yaw during a movement that was meant to be straight
is the single most informative number the body can produce: it is VEER, and it
is exactly what a wrong sign map, a weak corner, or a mis-mounted mecanum wheel
produces. `forward(50) -> turned +14` says "my right side is weaker than my
left" in a way no amount of watching does.

THE VERTICAL IS FOUND, NOT ASSUMED. Yaw is the rotation about the smoothed
gravity vector — dot(gyro, gravity_hat) — not "gyro z". Which body axis points
down depends on how the stick sits in its holder, and this body's sibling
robot_dog stands its stick upright while this one lays it flat. Reading yaw off
gravity means the instrument is right on both, and stays right if the stick is
remounted.

WHAT THIS BODY CANNOT MEASURE, and must not pretend to: DISTANCE. There is no
odometry, no ToF (that is 2_perception), and double-integrating accelerometer
noise is not measurement. Rotation is measured; translation is only ever
witnessed as "something was happening" (`stir`) or "nothing was" (`stalled`).
On a very smooth floor a rover can roll almost silently — so for forward,
backward and the slides, `stalled` is the weaker signal, and a stall reported
there deserves a second look. For cw/ccw it is gyro-truth and trustworthy.
That asymmetry is real; it is why the tuner measures the stiction floor with a
SPIN and not with a straight line.

FED BY THE RUNTIME, deliberately. The instinct gets a read-only view with no
feed(): a creature that could write its own achieved rotation would learn to
tell itself it drove beautifully into a wall.

MOTOR PROTOCOL (M5Stack RoverC / RoverC-Pro):
    I2C 0x38
    reg 0x00..0x03   one SIGNED byte per motor, -100..+100
    reg 0x00         bulk: four speed bytes at once
    (RoverC-Pro also has servo registers at 0x10+; stage 1 is motion only and
     does not touch them.)

WHICH byte drives which corner, and which way, is NOT in that protocol and is
NOT guessed here — see MOTOR_CORNER below.
"""
import math
import struct
import time

try:
    from instinct_and_soul.creature_sim.stethoscope import tap as _tap, probe as _probe
except ImportError:
    try:
        from stethoscope import tap as _tap, probe as _probe
    except ImportError:
        def _tap(kind, **payload):
            pass

        def _probe(name, value):
            pass


# ── calibration: measured on the real rover, not guessed ───────────────────

# MEASURED 2026-08-15, tuner `motors` recipe, rover on a book, wheels free.
# One motor index at a time, positive byte, watching which corner turned and
# which way the top of the wheel travelled:
#
#     index 0 -> front-left,  forward
#     index 1 -> front-right, forward
#     index 2 -> back-left,   forward
#     index 3 -> back-right,  forward
#
# So the registers are already in reading order, and — the part worth
# noticing — a POSITIVE byte drives every wheel FORWARD, including the two on
# the right. The RoverC's own firmware mirrors the right-hand pair for us.
# robot-bug's BugC does not, which is why that body expected two negative
# signs and this one has none. If a rover ever comes back with a mixed sign
# map, it is a different hat, not a mistake here.

MOTOR_CORNER = ("FL", "FR", "BL", "BR")  # which corner each index drives
MOTOR_SIGN = (1, 1, 1, 1)                # +1: a positive byte drives it forward

SPEED_FLOOR = 21     # the smallest speed byte that actually breaks stiction.
                     # MEASURED 2026-08-15 with the tuner's `floor` recipe, on
                     # the bench surface of that session — 21 was the first
                     # speed the gyro saw move.
                     #
                     # Lower than the guess it replaces, which said "roughly a
                     # third of full" (~33) from the geared-DC-motor folklore.
                     # A fifth is what this rover actually does, so the
                     # folklore was pessimistic here and the measurement wins.
                     #
                     # This is a fact about the SURFACE as much as about the
                     # body, and it is only advisory: the verbs will still
                     # accept a speed below it and stall. Re-run `floor` on
                     # carpet and expect a different, higher number — that
                     # difference is the point, not an error. It is also the
                     # floor for a SPIN, which is the only movement this body
                     # measures; a straight line may well need more.

STILL_DPS = 8.0      # rotation below this reads as not turning
STIR_G = 0.05        # accel deviation from rest below this reads as not moving
MIN_BOUT_S = 0.15    # a command shorter than this is not scored: too little
                     # time for the IMU to say anything
GRAV_TAU_S = 1.0     # gravity low-pass, so `stir` measures shaking, not tilt


# ── the mecanum mixer ──────────────────────────────────────────────────────
#
# Per corner, how that wheel must turn for each of the three things this body
# can do. Rollers on a mecanum wheel sit at 45 degrees and the four wheels form
# an X seen from above (FL and BR one way, FR and BL the other) — that X is
# what these signs encode.
#
#                      forward   slide-right   spin-cw
_MIX = {
    "FL": (1, 1, 1),
    "FR": (1, -1, -1),
    "BL": (1, -1, 1),
    "BR": (1, 1, -1),
}

# IF SLIDING DOES NOT WORK BUT DRIVING AND SPINNING DO, the X is wrong: two
# wheels are in each other's corners, or a wheel was fitted with its rollers
# mirrored. Look at the rover from above before touching this table — the
# rollers of the four wheels should form an X, not a diamond, and no amount of
# software makes a diamond strafe.


# ── the drive state ────────────────────────────────────────────────────────

class _DriveState:
    """One bout per command. Opened by note_command(), advanced by feed()
    from the runtime's heartbeat, closed and scored by the next command."""

    def __init__(self):
        self.grav = None
        self.last_t = None
        self.yaw_ema = 0.0       # signed deg/s about the vertical, smoothed
        self.stir_ema = 0.0
        # the open bout
        self.kind = "stop"
        self.speed = 0
        self.t0 = None
        self.turned = 0.0        # degrees about the vertical, signed
        self.stir_peak = 0.0
        self.stir_sum = 0.0
        self.samples = 0
        # one-shot outcome, consumed on read
        self.last_bout = None
        self.bouts = 0
        self.stalls = 0

    def note_command(self, kind, speed):
        """The runtime calls this the moment it writes to the motors."""
        self._close(time.ticks_ms() / 1000.0)
        self.kind = kind
        self.speed = int(speed)
        self.t0 = time.ticks_ms() / 1000.0
        self.turned = 0.0
        self.stir_peak = 0.0
        self.stir_sum = 0.0
        self.samples = 0
        # `motion=`, not `kind=`: the stethoscope's own first parameter is
        # named kind, so tap("cmd", kind=...) is a TypeError on every single
        # motor command. (robot-bug still carries that one.)
        _tap("cmd", motion=kind, speed=int(speed))

    def _close(self, now_s):
        if self.t0 is None:
            return
        dur = now_s - self.t0
        commanded = self.kind != "stop" and self.speed != 0
        if commanded and dur >= MIN_BOUT_S:
            # Did the world agree that this body moved? Neither term can be
            # written by the instinct; both come off the IMU.
            stir = self.stir_sum / max(1, self.samples)
            spun = abs(self.turned) >= STILL_DPS * dur * 0.25
            shook = stir >= STIR_G
            self.last_bout = {
                "kind": self.kind, "speed": self.speed,
                "for_s": round(dur, 2), "turned": round(self.turned, 1),
                "stir": round(stir, 3), "stalled": not spun and not shook,
                # degrees per second actually achieved, signed. For cw/ccw this
                # is what the speed BUYS on this floor; for forward/backward
                # and the slides it is VEER — what the body did that nobody
                # asked for.
                "dps": round(self.turned / dur, 1) if dur > 0 else 0.0,
            }
            self.bouts += 1
            b = self.last_bout
            if b["stalled"]:
                self.stalls += 1
            _tap("bout", motion=b["kind"], speed=b["speed"], for_s=b["for_s"],
                 turned=b["turned"], dps=b["dps"], stir=b["stir"],
                 stalled=b["stalled"])
        self.t0 = None

    def feed(self, a, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
        dt = max(0.0, min(0.2, now_s - self.last_t))
        self.last_t = now_s

        if self.grav is None:
            self.grav = list(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            self.grav[i] += k * (a[i] - self.grav[i])

        # Yaw about the FOUND vertical: the component of the rotation vector
        # along gravity. Right-hand rule about a downward axis means positive
        # is clockwise seen from above. Falls back to zero rather than to a
        # guess when gravity is not readable (free fall, or a dead IMU).
        gmag = math.sqrt(self.grav[0] ** 2 + self.grav[1] ** 2 + self.grav[2] ** 2)
        if gmag > 0.2:
            yaw_rate = (g[0] * self.grav[0] + g[1] * self.grav[1]
                        + g[2] * self.grav[2]) / gmag
        else:
            yaw_rate = 0.0
        self.yaw_ema += min(1.0, dt / 0.3) * (yaw_rate - self.yaw_ema)

        # shaking, not tilting: how far the raw accel sits from the smoothed
        # gravity it would read if the body were merely leaning
        dev = math.sqrt(sum((a[i] - self.grav[i]) ** 2 for i in range(3)))
        self.stir_ema += min(1.0, dt / 0.3) * (dev - self.stir_ema)

        if self.t0 is not None:
            self.turned += yaw_rate * dt
            self.stir_sum += dev
            self.samples += 1
            if dev > self.stir_peak:
                self.stir_peak = dev

        if now_s - _probe_t[0] > 0.5:
            _probe_t[0] = now_s
            _probe("yaw_dps", round(self.yaw_ema, 1))
            _probe("stir", round(dev, 3))


_probe_t = [-1e9]
_drive = _DriveState()

# The real motor writer, installed by main.py at boot. Absent under the sim and
# on a stick with no rover under it — the command bookkeeping still runs, so
# the whole loop is exercised without a rover attached.
_writer = [None]


def set_writer(fn):
    _writer[0] = fn


def _send_speeds(speeds):
    if _writer[0] is not None:
        _writer[0](speeds)


def _clamp(v):
    v = int(v)
    return -100 if v < -100 else (100 if v > 100 else v)


def _calibration_fault():
    """None when the calibration is usable, else what is wrong with it.

    A HALF-WRONG map is the dangerous case, not a missing one: ("FL", "FL",
    "BL", "BR") is a typo that reads as calibrated, drives two wheels as if
    they were the same corner, and leaves the fourth wheel dead — so it moves,
    which is exactly why nobody suspects the map. Each corner must appear
    exactly once."""
    if MOTOR_CORNER is None or MOTOR_SIGN is None:
        return "unmeasured"
    if len(MOTOR_CORNER) != 4 or len(MOTOR_SIGN) != 4:
        return "MOTOR_CORNER and MOTOR_SIGN must both have 4 entries"
    if sorted(MOTOR_CORNER) != ["BL", "BR", "FL", "FR"]:
        return ("MOTOR_CORNER must name each of FL FR BL BR exactly once, "
                "got {}".format(MOTOR_CORNER))
    for s in MOTOR_SIGN:
        if s not in (1, -1):
            return "MOTOR_SIGN entries must be +1 or -1, got {}".format(MOTOR_SIGN)
    return None


def move(fwd, strafe, spin, kind=None, speed=None):
    """The one primitive: mix a forward, a sideways and a rotation into four
    wheel bytes. Each argument is -100..100; + is forward, + is to the RIGHT,
    + is clockwise seen from above. All three compose — that is what mecanum
    wheels are for — and if the mix asks any wheel for more than 100 the whole
    set is scaled down together, so the DIRECTION survives and only the speed
    is lost.

    Refuses to move while uncalibrated. A guessed corner map drives a rover
    somewhere nobody predicted, and on a table that means off it."""
    fault = _calibration_fault()
    if fault is not None:
        _tap("uncalibrated", why=fault)
        return False
    raw = []
    for i in range(4):
        kf, ks, kw = _MIX[MOTOR_CORNER[i]]
        raw.append(kf * fwd + ks * strafe + kw * spin)
    peak = max(abs(v) for v in raw)
    scale = 100.0 / peak if peak > 100 else 1.0
    out = [_clamp(raw[i] * scale * MOTOR_SIGN[i]) for i in range(4)]
    if kind is None:
        kind = "move"
        speed = int(max(abs(fwd), abs(strafe), abs(spin)))
    _drive.note_command(kind, speed)
    _send_speeds(out)
    return True


# ── the verbs the instinct gets ────────────────────────────────────────────
#
# Direction is in the VERB, speed is always a positive magnitude — the same
# bargain robot-bug makes, so instinct code reads the same on both bodies.
# `cw`/`ccw` turn on the spot; `slide_left`/`slide_right` travel sideways
# without turning. They are named apart on purpose: on this body "left" alone
# is ambiguous in a way it is not on a creature that can only turn.

def forward(speed):
    return move(abs(speed), 0, 0, "forward", abs(speed))


def backward(speed):
    return move(-abs(speed), 0, 0, "backward", abs(speed))


def slide_left(speed):
    return move(0, -abs(speed), 0, "slide_left", abs(speed))


def slide_right(speed):
    return move(0, abs(speed), 0, "slide_right", abs(speed))


def cw(speed):
    return move(0, 0, abs(speed), "cw", abs(speed))


def ccw(speed):
    return move(0, 0, -abs(speed), "ccw", abs(speed))


def stop():
    _drive.note_command("stop", 0)
    _send_speeds([0, 0, 0, 0])
    return True


class _Drive:
    """The instinct's view of what its own commands actually did. READ ONLY —
    there is no feed() and no way to write an outcome. This is the creature's
    competence, and a percept it could write is a percept it would flatter."""

    def last(self):
        """The most recent scored command, or None. Consumed on read.

            {"kind": "cw", "speed": 40, "for_s": 1.2, "turned": 71.0,
             "dps": 59.2, "stir": 0.08, "stalled": False}

        `turned` is degrees really rotated about the vertical, + clockwise. For
        a turn that is the achievement; for forward, backward and the slides it
        is the VEER — rotation nobody asked for. `stalled` means commanded and
        did not move, and is gyro-truth for turns but only vibration for
        straight lines."""
        b = _drive.last_bout
        _drive.last_bout = None
        return b

    def rot(self):
        """How fast the body is turning right now, deg/s about the vertical,
        + clockwise (~0.3 s smoothed)."""
        return round(_drive.yaw_ema, 1)

    def stir(self):
        """How much the body is being shaken right now (~0.3 s smoothed). The
        only live evidence of straight-line motion this body has."""
        return round(_drive.stir_ema, 3)

    def moving(self):
        """True while the world agrees something is happening — turning OR
        being shaken. NOT whether a command is open: a command can be open
        while the body sits against a chair leg going nowhere."""
        return abs(_drive.yaw_ema) > STILL_DPS or _drive.stir_ema > STIR_G

    def commanded(self):
        """(kind, speed) currently written to the motors."""
        return (_drive.kind, _drive.speed)

    def totals(self):
        """(bouts, stalls) this waking. A stall rate is the bluntest possible
        reading of whether this body can do what it intends on this floor."""
        return (_drive.bouts, _drive.stalls)

    def calibrated(self):
        """False until MOTOR_CORNER/MOTOR_SIGN are measured AND make sense.
        While False the verbs refuse to move and every command is a no-op."""
        return _calibration_fault() is None

    def fault(self):
        """Why calibrated() is False, in words, or None when it is True. A map
        with a typo in it is worth naming: it looks measured and drives two
        wheels as the same corner."""
        return _calibration_fault()

    def corners(self):
        """The measured corner map, or None. Which register index drives which
        wheel."""
        return MOTOR_CORNER

    def floor(self):
        """The measured stiction floor, or None if never measured. Commands
        below it are expected to stall."""
        return SPEED_FLOOR


def attach(scope):
    scope["Drive"] = _Drive()
    scope["move"] = move
    scope["forward"] = forward
    scope["backward"] = backward
    scope["slide_left"] = slide_left
    scope["slide_right"] = slide_right
    scope["cw"] = cw
    scope["ccw"] = ccw
    scope["stop"] = stop
