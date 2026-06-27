"""instinct_tools — a tiny "pocket calculator" of streaming signal tools,
injected into the instinct scope as `Calc` (beside `Imu` / `Synth` / `Mem`).

Pure Python, no numpy/ulab — runs identically in the CPython sim and on bare
MicroPython (ESP32-S). Everything is O(1) per sample EXCEPT `Periodicity`, whose
autocorrelation is throttled (recomputed at most every `every_ms`) and bounded
to a short buffer, so it stays cheap enough for an MCU.

The point of the toolbox is to MODEL the signal and PREDICT what comes next, not
to threshold the latest sample and react. The useful shape is a pipeline:

    clean  ->  detect accents  ->  estimate their period  ->  predict the next

    clean   = Calc.OneEuro(min_cutoff=0.5, beta=0.7)
    onset   = Calc.Onset(refractory_ms=120)
    beat    = Calc.Periodicity(win_s=2.0)
    predict = Calc.AlphaBeta()
    # each loop, with now = time.ticks_ms()/1000:
    e = clean.update(energy, now)
    if onset.step(e, now):                 # an accent happened
        beat.observe(now)                  # (optional) feed IOIs for regularity
        predict.correct(now, beat.period())   # correct the model from what we saw
    if predict.due(now, lead_ms=20):       # the model says a beat is about to land
        Synth.note(9, KICK, 100, vel)      # fire to MEET it — anticipate, not react
"""

import math


class OneEuro:
    """1€ filter (Casiez et al. 2012): smooths jitter when the signal is slow,
    stays low-lag when it moves fast. `min_cutoff` (Hz) is the baseline cutoff,
    `beta` raises it with signal speed, `dcutoff` (Hz) filters the speed estimate.
    Call update(x, now_s) every sample."""

    def __init__(self, min_cutoff=0.5, beta=0.7, dcutoff=1.0):
        self.mc = min_cutoff
        self.b = beta
        self.dc = dcutoff
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def update(self, x, now_s):
        if self.t_prev is None or self.x_prev is None:
            self.t_prev = now_s
            self.x_prev = x
            return x
        dt = now_s - self.t_prev
        if dt <= 0:
            return self.x_prev
        dx = (x - self.x_prev) / dt
        ad = self._alpha(self.dc, dt)
        self.dx_prev = ad * dx + (1.0 - ad) * self.dx_prev
        cutoff = self.mc + self.b * abs(self.dx_prev)
        a = self._alpha(cutoff, dt)
        y = a * x + (1.0 - a) * self.x_prev
        self.x_prev = y
        self.t_prev = now_s
        return y


class Running:
    """Sliding-window mean / std / z-score over the last `n` samples. push(x)
    each sample; use mean()/std() for an adaptive level and z(x) to normalise.
    O(1) per sample (running sums)."""

    def __init__(self, n=50):
        self.n = n
        self.buf = []
        self._s = 0.0
        self._s2 = 0.0

    def push(self, x):
        self.buf.append(x)
        self._s += x
        self._s2 += x * x
        if len(self.buf) > self.n:
            old = self.buf.pop(0)
            self._s -= old
            self._s2 -= old * old
        return x

    def mean(self):
        m = len(self.buf)
        return self._s / m if m else 0.0

    def var(self):
        m = len(self.buf)
        if m < 2:
            return 0.0
        mu = self._s / m
        return max(0.0, self._s2 / m - mu * mu)

    def std(self):
        return self.var() ** 0.5

    def z(self, x):
        s = self.std()
        return (x - self.mean()) / s if s > 1e-9 else 0.0


class Onset:
    """Adaptive-threshold + refractory accent detector. step(x, now_s) returns
    True the moment x rises above mean + k·std of recent x (self-calibrating, so
    you never hard-code a threshold). Re-arms when x falls back below; refractory
    blocks double-triggers within `refractory_ms`."""

    def __init__(self, win=50, k=2.0, refractory_ms=120):
        self.run = Running(win)
        self.k = k
        self.refr = refractory_ms / 1000.0
        self.last = -1e9
        self.armed = True

    def step(self, x, now_s):
        self.run.push(x)
        if len(self.run.buf) < self.run.n:    # warm up: need a full window for a stable threshold
            return False
        thr = self.run.mean() + self.k * self.run.std()
        if x < thr:
            self.armed = True
            return False
        if self.armed and (now_s - self.last) > self.refr:
            self.last = now_s
            self.armed = False
            return True
        return False

    def threshold(self):
        return self.run.mean() + self.k * self.run.std()


class Periodicity:
    """Dominant period of a feature via windowed autocorrelation. push(x, now_s)
    each sample; period() returns seconds (0.0 when unsure), bpm() the tempo.
    The autocorrelation is throttled (recomputed at most every `every_ms`) over a
    bounded `win_s` buffer, so it is light enough for an MCU. Feed it a smooth
    feature (e.g. a OneEuro'd energy), ideally decimated to ~30-50 Hz. `min_s` /
    `max_s` bound the period search. Also reports observed-interval regularity."""

    def __init__(self, win_s=2.0, min_s=0.3, max_s=1.2, every_ms=250):
        self.win = win_s
        self.lo = min_s
        self.hi = max_s
        self.every = every_ms / 1000.0
        self.buf = []
        self.tbuf = []
        self._p = 0.0
        self._last = -1e9
        # observed inter-accent intervals (for regularity), if observe() is used
        self._ioi = []
        self._last_obs = None

    def push(self, x, now_s):
        self.buf.append(x)
        self.tbuf.append(now_s)
        while self.tbuf and now_s - self.tbuf[0] > self.win:
            self.buf.pop(0)
            self.tbuf.pop(0)
        if now_s - self._last >= self.every:
            self._compute()
            self._last = now_s
        return x

    def observe(self, now_s):
        """Optionally feed accent times to track interval regularity (cv)."""
        if self._last_obs is not None:
            d = now_s - self._last_obs
            if 0 < d < 3.0:
                self._ioi.append(d)
                if len(self._ioi) > 32:
                    self._ioi.pop(0)
        self._last_obs = now_s

    def _compute(self):
        m = len(self.buf)
        if m < 8:
            self._p = 0.0
            return
        dt = (self.tbuf[-1] - self.tbuf[0]) / (m - 1)
        if dt <= 0:
            self._p = 0.0
            return
        mu = sum(self.buf) / m
        b = [v - mu for v in self.buf]
        lo = max(1, int(self.lo / dt))
        hi = min(m - 1, int(self.hi / dt))
        best = 0.0
        best_lag = 0
        for lag in range(lo, hi + 1):
            s = 0.0
            for i in range(m - lag):
                s += b[i] * b[i + lag]
            if s > best:
                best = s
                best_lag = lag
        self._p = best_lag * dt if best_lag else 0.0

    def period(self):
        return self._p

    def bpm(self):
        return 60.0 / self._p if self._p > 0 else 0.0

    def cv(self):
        """Coefficient of variation of observed intervals: how regular (and so
        how predictable) the pulse is. ~0 = metronomic, >0.5 = loose. Needs
        observe()."""
        m = len(self._ioi)
        if m < 3:
            return 0.0
        mean = sum(self._ioi) / m
        if mean <= 0:
            return 0.0
        var = sum((x - mean) ** 2 for x in self._ioi) / m
        return var ** 0.5 / mean


class AlphaBeta:
    """Predict-and-correct event tracker — the react→anticipate engine. Feed it
    observed accent times via correct(now_s, period_hint) and it keeps a running
    estimate of the next accent time. Ask due(now_s, lead_ms) to fire ON the
    PREDICTION (optionally `lead_ms` early to beat output latency), and
    predict_next() for the next expected time. `alpha` corrects phase from the
    timing residual, `beta` corrects the period; `gate` (fraction of a period)
    rejects off-beat observations so noise doesn't capture the tracker."""

    def __init__(self, alpha=0.2, beta=0.01, gate=0.35):
        self.a = alpha
        self.b = beta
        self.gate = gate
        self.T = None        # period estimate (s)
        self.next = None     # next predicted accent time (s)

    def correct(self, now_s, period_hint=None):
        if self.T is None:
            self.T = period_hint if period_hint and period_hint > 0 else 0.5
            self.next = now_s + self.T
            return
        if period_hint and period_hint > 0 and self.T <= 0:
            self.T = period_hint
        # slide the prediction to the cycle nearest this observation
        pred = self.next
        while pred - self.T / 2.0 > now_s:
            pred -= self.T
        while pred + self.T / 2.0 < now_s:
            pred += self.T
        r = now_s - pred                      # timing residual
        if abs(r) <= self.gate * self.T:      # on-beat -> correct phase + period
            self.T = max(0.1, self.T + self.b * r)
            pred = pred + self.a * r          # corrected phase of this beat
        # always schedule the next prediction strictly in the future
        self.next = pred + self.T
        while self.next <= now_s:
            self.next += self.T

    def due(self, now_s, lead_ms=0.0):
        """True once when now reaches (next predicted accent − lead_ms), then
        advances to the following beat. Free-runs at the current period when no
        observations arrive (the 'predict' half); correct() re-locks it."""
        if self.next is None or self.T is None:
            return False
        if now_s >= self.next - lead_ms / 1000.0:
            self.next += self.T
            return True
        return False

    def predict_next(self):
        return self.next

    def period(self):
        return self.T if self.T else 0.0


class Calc:
    """Namespace injected into the instinct scope (like Imu / Synth / Mem)."""
    OneEuro = OneEuro
    Running = Running
    Onset = Onset
    Periodicity = Periodicity
    AlphaBeta = AlphaBeta
