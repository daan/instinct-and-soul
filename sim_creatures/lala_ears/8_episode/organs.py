"""Organs of this creature: an Ear (the sense of one's own voice), a Motion
sense (orientation + travel that never lose their bearings), a Pulse sense
(the repetition in the body's own movement), and an Episode sense (the
body's motion segmented into bounded gestures: a beginning, an arc, a
landing — with duration, peak, and attack shape).

Pulse exists because its predecessor was abusable: Periodicity's observe()
accepted whatever moments the instinct fed it, and souls twice manufactured
"perfect" regularity — once from an empty instrument (cv() read 0.0 with no
data) and once by feeding observe() their own loop timer. Pulse takes NO
input: it watches the same interposed gyro stream that feeds Motion and
derives period, phase, and a continuous confidence from the signal alone.
Confidence is earned or it is zero; there is nothing to feed and nothing to
fake.

Loaded once per session by the harness socket (creature_sim/organs.py);
attach(scope) runs at every instinct (re)load. All state lives at module
level, so it survives instinct hot-swaps — the whole point: a Madgwick reset
mid-dance cannot converge (the accelerometer never shows clean gravity), and
a wrong 'up' blinds travel reversals for many seconds. Here the fusion is fed
by interposing on the instinct's own Imu reads, updates on every gyro read
using the freshest accel, and boots from the first accel sample (tilt from
gravity), so there is no cold-start rest assumption and no reset, ever.

All senses are read-only from inside: the instinct can attend to them but
cannot clear, write, feed, or restart them.
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
        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        _pulse.feed(rot, now_s)
        w = self.wacc
        _episode.feed(math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2]) + 0.1 * rot, now_s)


_motion = _MotionState()


# ── Pulse ────────────────────────────────────────────────────────────────────

class _PulseState:
    """Autocorrelation over a rolling window of smoothed rotation energy.
    No external inputs: period, phase and confidence all come from the same
    stream. Throttled (recomputes ~4x/s) and bounded, MCU-friendly."""

    WIN_S = 4.0        # analysis window
    LO_S, HI_S = 0.25, 1.5   # period search bounds
    TACTUS_LO, TACTUS_HI = 0.4, 0.9   # report periods folded into this band
    STEP_S = 0.033     # decimate to ~30 Hz

    def __init__(self):
        self.buf = []           # (t, smoothed energy)
        self.ema = 0.0
        self.last_push = -1e9
        self.last_compute = -1e9
        self.period_ = 0.0
        self.conf_ = 0.0
        self.last_peak_t = None  # last local max of the envelope (phase anchor)
        self.last_t = -1e9       # staleness reference

    def feed(self, e, now_s):
        self.last_t = now_s
        self.ema += 0.3 * (e - self.ema)
        if now_s - self.last_push < self.STEP_S:
            return
        self.last_push = now_s
        self.buf.append((now_s, self.ema))
        while self.buf and now_s - self.buf[0][0] > self.WIN_S:
            self.buf.pop(0)
        n = len(self.buf)
        if n >= 3:
            e0, e1, e2 = self.buf[-3][1], self.buf[-2][1], self.buf[-1][1]
            mean = sum(v for _, v in self.buf) / n
            if e1 > e0 and e1 >= e2 and e1 > mean:
                self.last_peak_t = self.buf[-2][0]
        if now_s - self.last_compute >= 0.25:
            self.last_compute = now_s
            self._compute()

    def _compute(self):
        n = len(self.buf)
        if n < 40:                       # under ~1.3 s of data: nothing earned
            self.conf_, self.period_ = 0.0, 0.0
            return
        ts = [t for t, _ in self.buf]
        dt = (ts[-1] - ts[0]) / (n - 1)
        if dt <= 0:
            self.conf_ = 0.0
            return
        es = [v for _, v in self.buf]
        mu = sum(es) / n
        b = [v - mu for v in es]
        r0 = sum(v * v for v in b)
        if r0 <= 1e-9:                   # flat signal: no pulse to find
            self.conf_, self.period_ = 0.0, 0.0
            return
        lo = max(1, int(self.LO_S / dt))
        hi = min(n - 2, int(self.HI_S / dt))
        best_score, best_c, best_lag = 0.0, 0.0, 0
        prev = self.period_
        for lag in range(lo, hi + 1):
            s = 0.0
            for i in range(n - lag):
                s += b[i] * b[i + lag]
            c = (s * n) / (r0 * (n - lag))   # length-normalized correlation
            # continuity: when readings are ambiguous, prefer staying at the
            # metrical level already held rather than flapping between levels
            score = c * 1.2 if (prev > 0 and abs(lag * dt - prev) < 0.15 * prev) else c
            if score > best_score:
                best_score, best_c, best_lag = score, c, lag
        p = best_lag * dt if best_lag else 0.0
        # metrical folding: subdivisions and half-time are the same pulse
        # family — report the tactus, so the sense doesn't flap between levels
        if p > 0:
            while p < self.TACTUS_LO:
                p *= 2.0
            while p > self.TACTUS_HI:
                p *= 0.5
        self.period_ = p
        self.conf_ = max(0.0, min(1.0, best_c))   # confidence stays unboosted


_pulse = _PulseState()


class _Pulse:
    """The repetition in the body's own movement — derived, never fed."""

    def period(self):
        """Dominant cycle of the movement, seconds (0.0 when none is earned)."""
        return _pulse.period_

    def bpm(self):
        p = _pulse.period_
        return 60.0 / p if p > 0 else 0.0

    def confidence(self):
        """0..1, continuous: how strongly the movement repeats right now.
        0 until enough signal has been watched; low means 'no pulse', not
        'unknown but promising'."""
        if time.ticks_ms() / 1000.0 - _pulse.last_t > 1.0:
            return 0.0               # stale: the Imu is not being read
        return _pulse.conf_

    def phase(self):
        """0..1 position within the current cycle (0 = at an energy peak),
        or None while there is no confident pulse to have a phase in."""
        if _pulse.period_ <= 0 or _pulse.conf_ <= 0.05 or _pulse.last_peak_t is None:
            return None
        now = time.ticks_ms() / 1000.0
        return ((now - _pulse.last_peak_t) / _pulse.period_) % 1.0


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


# ── Episode ──────────────────────────────────────────────────────────────────

class _EpisodeState:
    """Hysteresis segmentation of motion energy into bounded happenings.
    The body of this dancer never stops, so an episode is a SURGE above the
    recent level (slow baseline, tau ~8 s — slow enough to define 'lately',
    never fast enough to normalize a sustained gesture away). Fed from the
    same interposed stream as Motion and Pulse; nothing to feed from inside."""

    K_HI, K_LO = 1.4, 1.05     # start above 1.4x recent level, end below 1.05x
    FLOOR_HI, FLOOR_LO = 8.0, 5.0   # absolute floors so stillness stays silent
    TAU_S = 8.0                # baseline timescale
    END_HOLD_S = 0.15          # energy must stay low this long to end
    MIN_DUR_S = 0.25           # shorter surges are jitter, not gestures

    def __init__(self):
        self.ema = 0.0
        self.base = 0.0
        self.last_t = None
        self.in_ep = False
        self.start_t = 0.0
        self.peak = 0.0
        self.peak_t = 0.0
        self.below_since = None
        self.announced = False     # started() fires only once MIN_DUR is real,
                                   # so started()/ended() always come in pairs
        self.last_ep = None        # [start_ms, dur_ms, peak, rise01]
        self.started_flag = False  # one-shots, consumed on read
        self.ended_flag = None

    def feed(self, e, now_s):
        if self.last_t is None:
            self.last_t = now_s
            self.base = e
        dt = max(0.0, now_s - self.last_t)
        self.last_t = now_s
        self.ema += 0.25 * (e - self.ema)
        self.base += min(1.0, dt / self.TAU_S) * (self.ema - self.base)
        hi = max(self.FLOOR_HI, self.base * self.K_HI)
        lo = max(self.FLOOR_LO, self.base * self.K_LO)
        v = self.ema
        if not self.in_ep:
            if v > hi:
                self.in_ep = True
                self.start_t = now_s
                self.peak = v
                self.peak_t = now_s
                self.below_since = None
                self.announced = False
        else:
            if v > self.peak:
                self.peak = v
                self.peak_t = now_s
            if not self.announced and now_s - self.start_t >= self.MIN_DUR_S:
                self.announced = True      # it lasted: it is a gesture
                self.started_flag = True
            if v < lo:
                if self.below_since is None:
                    self.below_since = now_s
                elif now_s - self.below_since > self.END_HOLD_S:
                    dur = self.below_since - self.start_t
                    self.in_ep = False
                    if self.announced:
                        rise = (self.peak_t - self.start_t) / dur if dur > 0 else 0.0
                        rise = max(0.0, min(1.0, rise))
                        ep = [int(self.start_t * 1000), int(dur * 1000),
                              round(self.peak, 1), round(rise, 2)]
                        self.last_ep = ep
                        self.ended_flag = ep
            else:
                self.below_since = None


_episode = _EpisodeState()


class _Episode:
    """Bounded happenings in the body's motion — a gesture with a beginning,
    an arc, and a landing."""

    def started(self):
        """True once, at the moment a gesture begins. Consumed on read."""
        f = _episode.started_flag
        _episode.started_flag = False
        return f

    def ended(self):
        """The completed gesture [start_ms, dur_ms, peak, rise01] once, at the
        moment it lands (rise01 ~0 = struck, ~1 = swelled). Consumed on read."""
        f = _episode.ended_flag
        _episode.ended_flag = None
        return f

    def current(self):
        """The gesture happening NOW as [start_ms, dur_ms_so_far, peak_so_far],
        or None between gestures."""
        if not _episode.in_ep or not _episode.announced:
            return None
        now = _episode.last_t or 0.0
        return [int(_episode.start_t * 1000),
                int((now - _episode.start_t) * 1000), round(_episode.peak, 1)]

    def last(self):
        """The most recent completed gesture [start_ms, dur_ms, peak, rise01],
        or None."""
        return _episode.last_ep


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
    scope["Pulse"] = _Pulse()
    scope["Episode"] = _Episode()
