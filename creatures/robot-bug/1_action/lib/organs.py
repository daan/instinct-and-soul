"""Organs of robot-bug: DRIVE — what this body did when it was told to move.

This is the first body in the menagerie whose own action has a consequence it
can measure ON ITSELF. tilt asked "did my chirp work" and had to read the
answer off another person, through a window four times longer than their
natural time-to-move, so every chirp scored as answered and the measure meant
nothing. Here the triplet closes inside one body:

    intent    "turn clockwise at 40"
    action    four signed bytes to the BugC at 0x38
    outcome   the gyro says how far the body ACTUALLY turned

Every motor command is therefore a small experiment, and this organ scores it
without being asked. One record per command:

    kind, speed, for_s     what was asked, and for how long
    turned                 degrees the body really rotated (gyro, integrated)
    stir                   how much it really shook (accel deviation from rest)
    stalled                commanded to move, and did NOT

`stalled` is the one that matters, and it is UNFAKEABLE: the IMU is fed by the
world, not by the instinct. A soul cannot tell itself it drove beautifully into
a wall. ORGANS.md requires exactly that of any satisfaction-adjacent percept,
and it is the property tilt could never have.

FED BY THE RUNTIME, deliberately — the opposite of the call tilt's condition_3
made on 2026-07-30, and for the reason stated there. In tilt the fed thing was
a plain measurement, so making the instinct feed it bought legibility cheaply.
Here the fed thing IS the satisfaction percept, so an instinct that could write
it could lie to itself about its own competence. The instinct is handed a
read-only view with no feed().

It costs no new pump: main.py's heartbeat already runs at 20 Hz calling
M5.update(), and feeds this from there. That loop's death is already fatal and
visible, so this adds no new silent failure mode.

MOTOR PROTOCOL (M5Stack BugC HAT, docs.m5stack.com/en/hat/hat-bugc and the
reference driver in m5stack/M5StickC examples/Hat/BUGC/bugC.cpp):
    I2C 0x38
    reg 0x00..0x03   one SIGNED byte per motor, -100..+100, + is clockwise
    reg 0x00         bulk: four speed bytes at once
    reg 0x10         RGB: [index, R, G, B]; index 0 = left, 1 = right
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

MOTOR_SIDE = None    # which motor index sits on which side, as a 4-tuple of
                     # -1 (left) / +1 (right) — e.g. (-1, +1, -1, +1).
                     # UNKNOWN until measured: the BugC docs do not say which
                     # register drives which corner. Run the tuner's `motors`
                     # recipe, which spins one index at a time, and write down
                     # what turned.

MOTOR_SIGN = None    # per index, +1 or -1: whether a POSITIVE byte drives that
                     # wheel forward. Two of the four are mounted mirrored, so
                     # two of these are negative. Same recipe finds them.

SPEED_FLOOR = None   # the smallest speed byte that actually breaks stiction on
                     # this floor. Geared DC motors do not start below roughly
                     # a third of full; below this the motors buzz and the body
                     # does not move. Run the tuner's `floor` recipe — it ramps
                     # and reports the value at which the IMU FIRST sees motion,
                     # which is the only honest way to know. Expect it to differ
                     # between carpet and a desk.

STILL_DPS = 8.0      # rotation below this reads as not turning
STIR_G = 0.05        # accel deviation from 1g below this reads as not moving
MIN_BOUT_S = 0.15    # a command shorter than this is not scored: too little
                     # time for the gyro to say anything
GRAV_TAU_S = 1.0     # gravity low-pass, so `stir` measures shaking and not tilt


# ── the drive state ────────────────────────────────────────────────────────

class _DriveState:
    """One bout per command. Opened by note_command(), advanced by feed()
    from the runtime's heartbeat, closed and scored by the next command."""

    def __init__(self):
        self.grav = None
        self.last_t = None
        self.rot_ema = 0.0
        # the open bout
        self.kind = "stop"
        self.speed = 0
        self.t0 = None
        self.turned = 0.0        # degrees, integrated
        self.stir_peak = 0.0     # worst accel deviation seen
        self.stir_sum = 0.0      # integrated, so a long gentle push counts
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
        _tap("cmd", kind=kind, speed=int(speed))

    def _close(self, now_s):
        if self.t0 is None:
            return
        dur = now_s - self.t0
        commanded = self.kind != "stop" and self.speed != 0
        if commanded and dur >= MIN_BOUT_S:
            # Did the world agree that this body moved? Neither term can be
            # written by the instinct; both come off the IMU.
            turned = abs(self.turned)
            stir = self.stir_sum / max(1, self.samples)
            stalled = turned < STILL_DPS * dur * 0.25 and stir < STIR_G
            self.last_bout = {
                "kind": self.kind, "speed": self.speed,
                "for_s": round(dur, 2), "turned": round(turned, 1),
                "stir": round(stir, 3), "stalled": stalled,
                # degrees per second actually achieved — the number that says
                # what this speed BUYS on this floor
                "dps": round(turned / dur, 1) if dur > 0 else 0.0,
            }
            self.bouts += 1
            if stalled:
                self.stalls += 1
            _tap("bout", **self.last_bout)
        self.t0 = None

    def feed(self, a, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
        dt = max(0.0, min(0.2, now_s - self.last_t))
        self.last_t = now_s

        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        self.rot_ema += min(1.0, dt / 0.3) * (rot - self.rot_ema)

        if self.grav is None:
            self.grav = list(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            self.grav[i] += k * (a[i] - self.grav[i])
        # shaking, not tilting: how far the raw accel sits from the smoothed
        # gravity it would read if the body were merely leaning
        dev = math.sqrt(sum((a[i] - self.grav[i]) ** 2 for i in range(3)))

        if self.t0 is not None:
            self.turned += rot * dt
            self.stir_sum += dev
            self.samples += 1
            if dev > self.stir_peak:
                self.stir_peak = dev

        if now_s - _probe_t[0] > 0.5:
            _probe_t[0] = now_s
            _probe("rot_dps", round(self.rot_ema, 1))
            _probe("stir", round(dev, 3))


_probe_t = [-1e9]
_drive = _DriveState()

# The real motor writer, installed by main.py at boot. Absent under the sim
# and on a body with no HAT — the command bookkeeping still runs, so the whole
# loop is exercised without a rover attached.
_writer = [None]


def set_writer(fn):
    _writer[0] = fn


def _send_speeds(speeds):
    if _writer[0] is not None:
        _writer[0] = _writer[0]
        _writer[0](speeds)


def _clamp(v):
    v = int(v)
    return -100 if v < -100 else (100 if v > 100 else v)


def _drive_sides(left, right, kind, speed):
    """Turn a left/right pair into four motor bytes, using the measured side
    and sign maps. With either unmeasured this refuses to move rather than
    guessing — a guessed sign map drives the body in a direction nobody
    predicted, and on a rover that means off a table."""
    if MOTOR_SIDE is None or MOTOR_SIGN is None:
        _tap("uncalibrated")
        return False
    out = []
    for i in range(4):
        v = left if MOTOR_SIDE[i] < 0 else right
        out.append(_clamp(v * MOTOR_SIGN[i]))
    _drive.note_command(kind, speed)
    _send_speeds(out)
    return True


# ── the verbs the instinct gets ────────────────────────────────────────────

def forward(speed):
    return _drive_sides(abs(speed), abs(speed), "forward", abs(speed))


def backward(speed):
    return _drive_sides(-abs(speed), -abs(speed), "backward", abs(speed))


def cw(speed):
    return _drive_sides(abs(speed), -abs(speed), "cw", abs(speed))


def ccw(speed):
    return _drive_sides(-abs(speed), abs(speed), "ccw", abs(speed))


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

        `turned` is degrees the body really rotated. `dps` is what that speed
        BUYS on this floor — the number to learn from, since it changes with
        the surface. `stalled` means commanded and did not move."""
        b = _drive.last_bout
        _drive.last_bout = None
        return b

    def rot(self):
        """How fast the body is turning right now, deg/s (~0.3 s smoothed)."""
        return round(_drive.rot_ema, 1)

    def moving(self):
        """True while the body is actually in motion — not whether a command
        is open, but whether the world agrees anything is happening."""
        return _drive.rot_ema > STILL_DPS

    def commanded(self):
        """(kind, speed) currently written to the motors."""
        return (_drive.kind, _drive.speed)

    def totals(self):
        """(bouts, stalls) this wearing. A stall rate is the bluntest possible
        reading of whether this body can do what it intends on this floor."""
        return (_drive.bouts, _drive.stalls)

    def calibrated(self):
        """False until MOTOR_SIDE/MOTOR_SIGN are measured. While False the
        verbs refuse to move and every command is a no-op."""
        return MOTOR_SIDE is not None and MOTOR_SIGN is not None

    def floor(self):
        """The measured stiction floor, or None if never measured. Commands
        below it are expected to stall."""
        return SPEED_FLOOR


def attach(scope):
    scope["Drive"] = _Drive()
    scope["forward"] = forward
    scope["backward"] = backward
    scope["cw"] = cw
    scope["ccw"] = ccw
    scope["stop"] = stop
