"""A Madgwick that runs on its own, independent of the instinct + local Calc.

The point of this creature: the world frame is a real, autonomous body
process. A background task (started once, on the event loop, surviving every
instinct hot-swap) reads the IMU at 100 Hz and advances ONE Madgwick filter —
boot-seeded from gravity, never reset — no matter what the soul does. The soul
reads `Imu` or `Madgwick` whenever it likes, at whatever rate; neither paces
the filter. This is the honest analog of the filter running in the device's
main.py, not something fed by interposing on the instinct's own reads.

It is exactly Madgwick and nothing more — a stable frame, not a gesture
parser. It exposes getAccel / getUp / getQuat (getX() shape, like Imu).
Velocity, reversals, tempo, phrasing are dance-specific readings the soul
builds on top (and keeps in experience).

Two rules, both about there being exactly ONE Madgwick:
  - Calc is loaded from this creature's own lib/calc.py (editable per-creature,
    like the real device creatures), not the shared module.
  - The soul is given the RUNNING Madgwick (a read-only view), not the
    Madgwick class — so it cannot spin up a second one. It keeps the rest of
    Calc (OneEuro/Running/Onset/Periodicity/AlphaBeta/Flow) to build its own
    percepts from the frame.
"""
import asyncio
import math
import os
import sys
import time

# Load THIS creature's local Calc (lib/calc.py), not the shared module.
_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
from calc import Calc            # noqa: E402  (creature-local, iterable)

PUMP_HZ = 100                    # the frame's own update rate, independent of
                                 # the soul (the clip is interpolated, so this
                                 # is robust to the clip's native sample rate)


class _MotionState:
    """The one persistent Madgwick. Module scope: survives hot-swaps. Boot-
    seeded from the first accel so there is no convergence transient — the
    frame is correct from sample one."""

    def __init__(self):
        self.pose = None
        self.wacc = (0.0, 0.0, 0.0)

    def feed(self, a, g, now_s):
        if self.pose is None:
            # boot orientation from gravity: rotate accel direction -> world +z
            n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
            if n < 1e-6:
                return
            u = (a[0] / n, a[1] / n, a[2] / n)
            q = [1.0 + u[2], u[1], -u[0], 0.0]
            qn = math.sqrt(sum(x * x for x in q))
            if qn < 1e-6:
                q, qn = [0.0, 1.0, 0.0, 0.0], 1.0  # upside down: 180 deg about x
            self.pose = Calc.Madgwick(beta=0.1, q=[x / qn for x in q])
        self.wacc = self.pose.update(a[0], a[1], a[2], g[0], g[1], g[2], now_s)


_motion = _MotionState()
_pump_task = None                # the one background pump; started once


async def _pump(imu):
    """Read the IMU at PUMP_HZ and advance the frame — forever, independent of
    the instinct. Reads the raw clip source directly when available (so the
    soul's imu_reads log stays the soul's), else the plain injected IMU."""
    src = getattr(imu, "_source", None)
    clock = getattr(imu, "_clock", None)
    dt = 1.0 / PUMP_HZ
    while True:
        if src is not None and clock is not None:
            t = clock.now_ms
            _motion.feed(src.accel_at(t), src.gyro_at(t), t / 1000.0)
        else:                    # device / non-sim: read the injected IMU
            _motion.feed(imu.getAccel(), imu.getGyro(), time.ticks_ms() / 1000.0)
        await asyncio.sleep(dt)


class _MadgwickView:
    """Read-only handle on the body's running Madgwick — always warm, advanced
    by its own 100 Hz pump, never reset. Read it at any rate (no update(): the
    body feeds it). A frame, not a gesture parser."""

    def getAccel(self):
        """Latest world-frame linear acceleration (m/s^2), gravity removed —
        the fused counterpart to Imu.getAccel()'s raw reading. A SIGNED vector
        in fixed world axes (x, y horizontal; z = up): the sign of each axis
        is a real direction. Tilt is solid; heading (yaw) drifts slowly."""
        return _motion.wacc

    def getUp(self):
        """Gravity 'up' as a unit vector in the sensor frame (tilt/pose)."""
        return _motion.pose.up() if _motion.pose else (0.0, 0.0, 1.0)

    def getQuat(self):
        """(w, x, y, z) unit quaternion, sensor->world orientation."""
        return _motion.pose.quat() if _motion.pose else (1.0, 0.0, 0.0, 0.0)


class _SoulCalc:
    """Calc for the soul — everything EXCEPT Madgwick. The frame is the
    organ's; the soul gets the composable tools to build its own percepts."""
    OneEuro = Calc.OneEuro
    Running = Calc.Running
    Onset = Calc.Onset
    Periodicity = Calc.Periodicity
    AlphaBeta = Calc.AlphaBeta
    Flow = Calc.Flow


def attach(scope):
    global _pump_task
    scope["Madgwick"] = _MadgwickView()    # the one warm, running Madgwick
    scope["Calc"] = _SoulCalc              # the CLASS removed — no second Madgwick
    if _pump_task is None:                 # start the pump once; it outlives hot-swaps
        try:
            _pump_task = asyncio.create_task(_pump(scope["Imu"]))
        except RuntimeError:
            _pump_task = asyncio.ensure_future(_pump(scope["Imu"]))
