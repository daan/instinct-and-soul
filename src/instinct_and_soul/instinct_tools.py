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
        observe(). Returns 9.9 until at least 3 intervals have been observed:
        no data means unpredictable, not metronomic."""
        m = len(self._ioi)
        if m < 3:
            return 9.9
        mean = sum(self._ioi) / m
        if mean <= 0:
            return 9.9
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


def _qrot(q, vx, vy, vz):
    """Rotate vector v by quaternion q=[w,x,y,z] (applies R(q): sensor->world)."""
    w, x, y, z = q
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


class Madgwick:
    """Madgwick AHRS (IMU mode: accelerometer + gyroscope, no magnetometer).
    Fuses the accelerometer's absolute 'down' (gravity) with the gyroscope's
    smooth rotation into an attitude, so you can read the sensor as VECTORS IN
    SPACE instead of raw axes. Make one at the top of run(); each loop call
    update(ax, ay, az, gx, gy, gz, now) with accel in g and gyro in deg/s.

    update() returns the world-frame linear acceleration (ax, ay, az) in
    **m/s^2**, gravity removed — the body's motion THROUGH SPACE as a SIGNED
    vector in fixed world axes (x, y horizontal; z = up), the same no matter how
    the sensor is twisted (so +z is reaching up, -z dropping; the sign of each
    axis is a real direction, not just a magnitude). Other readings:
        up()   -> gravity 'up' as a unit 3-vector in the SENSOR frame (tilt/pose;
                  dimensionless direction)
        quat() -> (w, x, y, z) unit quaternion, orientation sensor->world
    Tilt (pitch/roll) is absolutely referenced by gravity and does not drift;
    heading (yaw) rides the gyro and can drift slowly (there is no magnetometer).
    Pass q=(w,x,y,z) to start from a known orientation instead of level."""

    def __init__(self, beta=0.08, q=None):
        self.q = [1.0, 0.0, 0.0, 0.0] if q is None else [float(v) for v in q]
        self.beta = beta
        self.t_prev = None
        self._wacc = (0.0, 0.0, 0.0)

    def update(self, ax, ay, az, gx, gy, gz, now_s):
        if self.t_prev is None:
            dt = 0.0
        else:
            dt = now_s - self.t_prev
        self.t_prev = now_s
        q0, q1, q2, q3 = self.q
        d2r = 0.017453292519943295
        wx, wy, wz = gx * d2r, gy * d2r, gz * d2r            # deg/s -> rad/s
        if 0.0 < dt < 1.0:
            # quaternion rate from the gyro
            qd0 = 0.5 * (-q1 * wx - q2 * wy - q3 * wz)
            qd1 = 0.5 * ( q0 * wx + q2 * wz - q3 * wy)
            qd2 = 0.5 * ( q0 * wy - q1 * wz + q3 * wx)
            qd3 = 0.5 * ( q0 * wz + q1 * wy - q2 * wx)
            # accelerometer gradient-descent correction (pulls 'up' toward gravity)
            n = math.sqrt(ax * ax + ay * ay + az * az)
            if n > 1e-9:
                nx, ny, nz = ax / n, ay / n, az / n
                _2q0, _2q1, _2q2, _2q3 = 2.0 * q0, 2.0 * q1, 2.0 * q2, 2.0 * q3
                _4q0, _4q1, _4q2 = 4.0 * q0, 4.0 * q1, 4.0 * q2
                _8q1, _8q2 = 8.0 * q1, 8.0 * q2
                q0q0, q1q1, q2q2, q3q3 = q0 * q0, q1 * q1, q2 * q2, q3 * q3
                s0 = _4q0 * q2q2 + _2q2 * nx + _4q0 * q1q1 - _2q1 * ny
                s1 = (_4q1 * q3q3 - _2q3 * nx + 4.0 * q0q0 * q1 - _2q0 * ny
                      - _4q1 + _8q1 * q1q1 + _8q1 * q2q2 + _4q1 * nz)
                s2 = (4.0 * q0q0 * q2 + _2q0 * nx + _4q2 * q3q3 - _2q3 * ny
                      - _4q2 + _8q2 * q1q1 + _8q2 * q2q2 + _4q2 * nz)
                s3 = 4.0 * q1q1 * q3 - _2q1 * nx + 4.0 * q2q2 * q3 - _2q2 * ny
                sn = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
                if sn > 1e-9:
                    b = self.beta / sn
                    qd0 -= b * s0; qd1 -= b * s1; qd2 -= b * s2; qd3 -= b * s3
            q0 += qd0 * dt; q1 += qd1 * dt; q2 += qd2 * dt; q3 += qd3 * dt
            qn = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
            if qn > 1e-9:
                self.q = [q0 / qn, q1 / qn, q2 / qn, q3 / qn]
        # motion through space: sensor accel rotated to world, gravity removed,
        # converted from g to m/s^2
        rx, ry, rz = _qrot(self.q, ax, ay, az)
        self._wacc = (rx * 9.81, ry * 9.81, (rz - 1.0) * 9.81)
        return self._wacc

    def up(self):
        """Gravity 'up' direction in the SENSOR frame (unit 3-vector)."""
        w, x, y, z = self.q
        return (2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y))

    def world_accel(self):
        return self._wacc

    def quat(self):
        return tuple(self.q)


Pose = Madgwick    # backward-compatible alias


class Flow:
    """Leaky integrator over world-frame linear acceleration (Madgwick's
    output) -> a running velocity estimate: the body's travel through space as
    a signed vector, plus the moment that travel turns around. The leak keeps
    integration drift bounded, so the magnitude is a short-horizon speed, not
    an odometer — trust direction and the rhythm of reversals over absolute
    size. Feed every loop with the (wx, wy, wz) Madgwick.update() returns.

        f.update(wx, wy, wz, now_s) -> (vx, vy, vz)   # world frame, ~m/s
        f.reversal() -> None | (axis, sign)
            ('x'|'y'|'z', +1|-1) the instant travel along the currently
            dominant axis flips direction — a swing's turnaround. The event
            is consumed on read; it fires once, shortly after the turn (the
            new stroke must exceed min_speed to confirm).
    """

    def __init__(self, leak=2.0, min_speed=0.4):
        self._v = [0.0, 0.0, 0.0]
        self._leak = leak          # fraction of velocity shed per second
        self._min = min_speed      # speed needed to confirm a direction
        self._last_t = None
        self._sign = [0, 0, 0]     # last confirmed direction per axis
        self._rev = None

    def update(self, wx, wy, wz, now_s):
        if self._last_t is None:
            self._last_t = now_s
        dt = now_s - self._last_t
        self._last_t = now_s
        if dt < 0.0:
            dt = 0.0
        elif dt > 0.1:
            dt = 0.1               # a feeding gap must not integrate garbage
        k = 1.0 - self._leak * dt
        if k < 0.0:
            k = 0.0
        v = self._v
        v[0] = v[0] * k + wx * dt
        v[1] = v[1] * k + wy * dt
        v[2] = v[2] * k + wz * dt
        m0, m1, m2 = abs(v[0]), abs(v[1]), abs(v[2])
        dom = 0 if (m0 >= m1 and m0 >= m2) else (1 if m1 >= m2 else 2)
        if (m0, m1, m2)[dom] > self._min:
            s = 1 if v[dom] > 0 else -1
            if self._sign[dom] != 0 and s != self._sign[dom]:
                self._rev = ("xyz"[dom], s)
            self._sign[dom] = s
        return (v[0], v[1], v[2])

    def reversal(self):
        r = self._rev
        self._rev = None
        return r


class Ring:
    """A bounded list: push drops the oldest once full. The container half of
    what Mem used to be — Mem bundled a bounded buffer together with a
    registry of named slots, and those are two different jobs. This is just
    the buffer. Persisting it across a rewrite is keep()'s job, and `maxlen`
    is a constructor argument here so a window cannot exist without stating
    how big it is.

    Takes anything, unlike Running, which maintains numeric sums."""

    def __init__(self, n):
        self.n = int(n)
        self.buf = []

    def push(self, v):
        self.buf.append(v)
        if len(self.buf) > self.n:
            self.buf.pop(0)
        return v

    def recent(self, n=None):
        return list(self.buf) if n is None else list(self.buf[-n:])

    def latest(self):
        return self.buf[-1] if self.buf else None

    def clear(self):
        del self.buf[:]      # IN PLACE: rebinding orphans whatever keep() holds

    def __len__(self):
        return len(self.buf)


class Calc:
    """Namespace injected into the instinct scope (like Imu / Synth / Mem)."""
    OneEuro = OneEuro
    Running = Running
    Ring = Ring
    Onset = Onset
    Periodicity = Periodicity
    AlphaBeta = AlphaBeta
    Madgwick = Madgwick
    Pose = Madgwick    # alias so older instincts keep working
    Flow = Flow
