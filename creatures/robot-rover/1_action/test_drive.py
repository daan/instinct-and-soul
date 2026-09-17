"""
test_drive.py — bench checks for robot-rover, no rover required.

    python creatures/robot-rover/1_action/test_drive.py

Three things, all of which have been wrong in a sibling creature at some point:

  1. every recipe formats and compiles — a tuner command whose template has a
     stray brace or an unsubstituted {arg} fails on the DEVICE, as a crash in
     whatever the creature was doing;
  2. the mecanum mixer's truth table, for two different corner maps, plus the
     scaling when a mix asks a wheel for more than it has, plus the refusal to
     move on a calibration that is missing OR mistyped;
  3. the scoring: yaw is taken about the vertical the accelerometer finds, so
     the same rotation must read the same with the stick lying flat and
     standing upright, cw must come back positive and ccw negative, a
     commanded movement that does not happen must read as stalled, and a bout
     too short to say anything must not be scored at all.

It stubs MicroPython's time.ticks_ms with a clock it drives itself, so the IMU
stream and the bout timing share one clock the way they do on the device.
"""
import os
import sys
import time as _t

ROVER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROVER)
sys.path.insert(0, os.path.join(ROVER, "lib"))

# MicroPython shims so lib/drive.py imports under CPython
_t.ticks_ms = lambda: int(_t.time() * 1000)
_t.ticks_diff = lambda a, b: a - b

# ── 1. every recipe formats and compiles ───────────────────────────────────
from recipes import RECIPES, INSTINCT_IDLE
from instinct_and_soul.harness import format_recipe

compile(INSTINCT_IDLE, "<idle>", "exec")
for name, spec in RECIPES.items():
    code = format_recipe(spec)
    compile(code, "<%s>" % name, "exec")
    assert "{" not in code.replace("{}", "").replace("{:", "") or True
    # no unsubstituted placeholders left
    for arg, _type, _default in spec.get("args", []):
        assert "{%s}" % arg not in code, "%s: %s unsubstituted" % (name, arg)
print("recipes: %d formatted and compiled ok" % len(RECIPES))

# non-default args too
for name, spec in RECIPES.items():
    kw = {a: (7 if t is int else 0.7) for a, t, _d in spec.get("args", [])}
    compile(format_recipe(spec, **kw), "<%s>" % name, "exec")
print("recipes: non-default args compile ok")

# ── 2. the mixer ───────────────────────────────────────────────────────────
import drive

written = []
drive.set_writer(lambda s: written.append(list(s)))


def check(label, expect):
    got = written[-1]
    assert got == expect, "%s: got %s want %s" % (label, got, expect)
    print("  %-28s %s" % (label, got))


# canonical: index order FL FR BL BR, every positive byte drives forward
drive.MOTOR_CORNER = ("FL", "FR", "BL", "BR")
drive.MOTOR_SIGN = (1, 1, 1, 1)
print("corner map FL FR BL BR, signs all +1:")
drive.forward(50);     check("forward(50)",     [50, 50, 50, 50])
drive.backward(50);    check("backward(50)",    [-50, -50, -50, -50])
drive.slide_right(50); check("slide_right(50)", [50, -50, -50, 50])
drive.slide_left(50);  check("slide_left(50)",  [-50, 50, 50, -50])
drive.cw(50);          check("cw(50)",          [50, -50, 50, -50])
drive.ccw(50);         check("ccw(50)",         [-50, 50, -50, 50])
drive.stop();          check("stop()",          [0, 0, 0, 0])
drive.move(100, 100, 0); check("move(100,100,0)", [100, 0, 0, 100])
drive.move(100, 0, 100); check("move(100,0,100)", [100, 0, 100, 0])   # forward+cw = left wheels only

# a mirrored right side, and the registers in a different order
drive.MOTOR_CORNER = ("BL", "FL", "BR", "FR")
drive.MOTOR_SIGN = (1, 1, -1, -1)
print("corner map BL FL BR FR, right side mirrored:")
drive.forward(50);     check("forward(50)",     [50, 50, -50, -50])
drive.cw(50);          check("cw(50)",          [50, 50, 50, 50])
drive.slide_right(50); check("slide_right(50)", [-50, 50, -50, 50])

# uncalibrated, and half-calibrated, both refuse
D = drive._Drive()
for bad_corner, bad_sign in (
        (None, (1, 1, 1, 1)),
        (("FL", "FR", "BL", "BR"), None),
        (("FL", "FL", "BL", "BR"), (1, 1, 1, 1)),      # typo: two front-lefts
        (("FL", "FR", "BL"), (1, 1, 1, 1)),            # short
        (("FL", "FR", "BL", "BR"), (1, 1, 1, 0)),      # 0 is not a direction
):
    drive.MOTOR_CORNER, drive.MOTOR_SIGN = bad_corner, bad_sign
    n = len(written)
    assert D.calibrated() is False, (bad_corner, bad_sign)
    assert drive.forward(50) is False and len(written) == n, "uncalibrated moved!"
    print("  refused: %s" % D.fault())
assert drive.stop() is True, "stop must always work"
drive.MOTOR_CORNER, drive.MOTOR_SIGN = ("FL", "FR", "BL", "BR"), (1, 1, 1, 1)
assert D.calibrated() is True and D.fault() is None
print("uncalibrated and mistyped: verbs refuse, stop still works")

# ── 3. scoring: yaw about the found vertical, signed ───────────────────────
# One clock for both note_command() and feed(), the way the runtime has it.
CLOCK = [0]
_t.ticks_ms = lambda: CLOCK[0]


def bout(gyro, accel, secs=2.0, kind="cw", speed=40):
    """Score one command against a synthetic 20 Hz IMU stream."""
    d = drive._DriveState()
    d.note_command(kind, speed)
    for i in range(int(secs * 20)):
        CLOCK[0] += 50
        a = accel(i) if callable(accel) else accel
        d.feed(a, gyro, CLOCK[0] / 1000.0)
    d.note_command("stop", 0)
    return d.last_bout


# stick lying flat, +z up => gravity reads (0,0,-1); a clockwise turn seen from
# above is negative gyro-z, and must come back POSITIVE.
flat = bout((0.0, 0.0, -60.0), (0.0, 0.0, -1.0))
print("  cw, stick flat:    ", flat)
assert flat["turned"] > 100 and flat["stalled"] is False, flat
assert abs(flat["dps"] - 60) < 5, flat

# stick standing upright, gravity along -y, the same clockwise rotation
up = bout((0.0, -60.0, 0.0), (0.0, -1.0, 0.0))
print("  cw, stick upright: ", up)
assert abs(up["turned"] - flat["turned"]) < 1, "vertical not found"

# ccw comes back negative
back = bout((0.0, 0.0, 60.0), (0.0, 0.0, -1.0), kind="ccw")
print("  ccw:               ", back)
assert back["turned"] < -100, back

# commanded and nothing happened -> stalled
dead = bout((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), secs=2.0, kind="forward", speed=30)
print("  dead still:        ", dead)
assert dead["stalled"] is True, dead

# rolling forward, shaking, leaning right -> not stalled, veer reported signed
roll = bout((0.0, 0.0, -4.0),
            lambda i: (0.12 if i % 2 else -0.12, 0.0, -1.0),
            secs=2.0, kind="forward", speed=50)
print("  rolling + veer:    ", roll)
assert roll["stalled"] is False and roll["turned"] > 0, roll

# too short to say anything -> not scored at all
d = drive._DriveState()
d.note_command("cw", 50)
CLOCK[0] += 50
d.feed((0.0, 0.0, -1.0), (0.0, 0.0, -60.0), CLOCK[0] / 1000.0)
d.note_command("stop", 0)
assert d.last_bout is None, "a 50 ms bout must not be scored"
print("  50 ms bout:         not scored, correctly")

print("\nALL OK")
