"""Organs of this creature: an Ear (the sense of one's own voice) and a
Motion sense (orientation + travel that never lose their bearings).

Loaded once per session by the harness socket (creature_sim/organs.py);
attach(scope) runs at every instinct (re)load. All state lives at module
level, so it survives instinct hot-swaps — the whole point: a Madgwick reset
mid-dance cannot converge (the accelerometer never shows clean gravity), and
a wrong 'up' blinds travel reversals for many seconds. Here the fusion is fed
by interposing on the instinct's own Imu reads, updates on every gyro read
using the freshest accel, and boots from the first accel sample (tilt from
gravity), so there is no cold-start rest assumption and no reset, ever.

Both senses are read-only from inside: the instinct can attend to them but
cannot clear, write, or restart them.
"""
import math
import time

try:
    from instinct_and_soul.instinct_tools import Calc   # sim
except ImportError:
    from calc import Calc                               # device (lib/calc.py)


# ── Ear ──────────────────────────────────────────────────────────────────────

_MAXLEN = 400
_events = []      # newest last; entry formats in _Ear docstring
_cc_total = [0]   # control_change calls since session start


def _record(entry):
    _events.append(entry)
    if len(_events) > _MAXLEN:
        del _events[:len(_events) - _MAXLEN]


class _Ear:
    """The notes this body voiced, newest last. Entry formats:
        [t_ms, "on",   ch, note, velocity]
        [t_ms, "off",  ch, note]
        [t_ms, "note", ch, note, velocity, ms]
    """

    def recent(self, n=None, ch=None):
        """The last n note events (all if n is None), oldest first.
        ch selects a single voice: only events on that channel."""
        evs = _events if ch is None else [e for e in _events if e[2] == ch]
        if n is None or n >= len(evs):
            return list(evs)
        return evs[-int(n):]

    def cc_total(self):
        """Control-change messages sent since the session started."""
        return _cc_total[0]


class _EarSynth:
    def __init__(self, real):
        self._real = real

    def program(self, ch, program):
        return self._real.program(ch, program)

    def control_change(self, ch, control, value):
        _cc_total[0] += 1
        return self._real.control_change(ch, control, value)

    def note_on(self, ch, note, velocity=80):
        _record([time.ticks_ms(), "on", ch, note, velocity])
        return self._real.note_on(ch, note, velocity)

    def note_off(self, ch, note, velocity=0):
        _record([time.ticks_ms(), "off", ch, note])
        return self._real.note_off(ch, note, velocity)

    def note(self, ch, note, ms, velocity=80):
        _record([time.ticks_ms(), "note", ch, note, velocity, ms])
        return self._real.note(ch, note, ms, velocity)


# ── Motion ───────────────────────────────────────────────────────────────────

class _MotionState:
    def __init__(self):
        self.pose = None            # created on the first accel sample
        self.flow = Calc.Flow()
        self.acc = None             # freshest accel (g), waiting for a gyro
        self.wacc = (0.0, 0.0, 0.0)
        self.vel = (0.0, 0.0, 0.0)

    def feed_accel(self, a):
        if self.pose is None:
            # boot orientation from gravity: rotate accel direction -> world +z
            n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
            if n < 1e-6:
                return
            u = (a[0] / n, a[1] / n, a[2] / n)
            q = [1.0 + u[2], u[1], -u[0], 0.0]     # (1+u.z, u x z) for z=(0,0,1)
            qn = math.sqrt(sum(x * x for x in q))
            if qn < 1e-6:
                q, qn = [0.0, 1.0, 0.0, 0.0], 1.0  # upside down: 180 deg about x
            self.pose = Calc.Madgwick(beta=0.1, q=[x / qn for x in q])
        self.acc = a

    def feed_gyro(self, g, now_s):
        if self.pose is None or self.acc is None:
            return
        a = self.acc
        self.wacc = self.pose.update(a[0], a[1], a[2], g[0], g[1], g[2], now_s)
        self.vel = self.flow.update(self.wacc[0], self.wacc[1], self.wacc[2], now_s)


_motion = _MotionState()


class _Motion:
    """The body's sense of its own travel — always warm, never reset."""

    def up(self):
        """Gravity 'up' as a unit vector in the sensor frame (tilt/pose)."""
        return _motion.pose.up() if _motion.pose else (0.0, 0.0, 1.0)

    def accel_world(self):
        """Latest world-frame linear acceleration (m/s^2), gravity removed."""
        return _motion.wacc

    def velocity(self):
        """Travel through space: signed velocity (~m/s, world axes)."""
        return _motion.vel

    def reversal(self):
        """None | (axis, sign): the moment travel on the dominant axis turns
        around. Consumed on read — one reader should own it."""
        return _motion.flow.reversal()


class _MotionImu:
    def __init__(self, real):
        self._real = real

    def getAccel(self):
        a = self._real.getAccel()
        _motion.feed_accel(a)
        return a

    def getGyro(self):
        g = self._real.getGyro()
        _motion.feed_gyro(g, time.ticks_ms() / 1000.0)
        return g

    def getMag(self):
        return self._real.getMag()


def attach(scope):
    synth = scope["Synth"]
    if isinstance(synth, _EarSynth):    # re-attach on hot-swap: don't double-wrap
        synth = synth._real
    scope["Synth"] = _EarSynth(synth)
    scope["Ear"] = _Ear()

    imu = scope["Imu"]
    if isinstance(imu, _MotionImu):
        imu = imu._real
    scope["Imu"] = _MotionImu(imu)
    scope["Motion"] = _Motion()
