"""Organs of tilt: a Posture sense — the lean of the wearer's upper spine
against a CAPTURED upright, and how long the body has been holding still.

Posture is the IMU's easiest regime (the perch note in MENAGERIE.md): no
dynamics, no heading, no fusion — gravity from low-passed accel, stillness
from gyro magnitude. The upright reference is CAPTURED, never assumed
(Posture.set_upright()), so angle() is mounting-agnostic.

MOUNTING CONVENTION (measured worn, 2026-07-15): standing upright reads
gravity on X- (accel ~ (-1,0,0)) — the X axis runs along the spine with
+X pointing DOWN it. Bending is rotation about the device Y axis. lean()
maps this to anatomical angles: upright = 0, bending FORWARD positive
(+90 = lying on the belly), bending BACK negative (-90 = lying on the
back):  fwd = atan2(gz, -gx),  side = atan2(gy, -gx).

The organ measures; it does not judge. What angle counts as a slouch and
how long it must persist before it deserves a sound is the instinct's
grammar (and eventually the soul's pedagogy) — same division of labor as
Kata: the body owns the measurement, the mind owns the meaning.

All constants are first guesses (2026-07-15) to calibrate with the tuner's
`posture` stream, worn, on a real back.

Fed by interposing on the instinct's own Imu reads; state survives instinct
hot-swaps.
"""
import math
import time

try:
    # host (sim bench): the session-attached stethoscope
    from instinct_and_soul.creature_sim.stethoscope import tap as _tap, probe as _probe
except ImportError:
    try:
        # device: the UDP twin in /flash/lib — a no-op until a tuner
        # recipe calls stethoscope.attach(<laptop ip>)
        from stethoscope import tap as _tap, probe as _probe
    except ImportError:
        def _tap(kind, **payload):
            pass

        def _probe(name, value):
            pass


STILL_DPS = 10.0     # gyro magnitude below this reads as holding still —
                     # breathing and micro-sway on-body measure a few dps
                     # (guess; calibrate worn)
GRAV_TAU_S = 1.0     # gravity low-pass: slow enough to ignore gestures,
                     # fast enough to catch a real postural shift

# ── movement-verb segmentation (all first guesses — tuner `verbs`) ──────────
EP_SETTLE_S = 1.5    # stillness this long closes a motion episode
SHIFT_DEG = 7.0      # lean moved this far AND stuck -> SHIFT (else MICRO)
STRETCH_DEG = 25.0   # peak excursion beyond this (but returning) -> FULL_STRETCH
AWAY_S = 45.0        # motion longer than this = they left the chair (MOVED_OFF)
FLAVOR_UP_DEG = 8.0  # |lean| within this of upright -> "upright-ish"
FLAVOR_FWD_DEG = 12.0  # fwd beyond this -> "slumped-ish" (back: "reclined-ish")

TAP_G = 1.2          # accel-magnitude deviation (g) that counts as a tap on
                     # the housing — knuckle taps measure well above body
                     # motion (guess; calibrate worn with the tuner's `tap`)
TAP_REFRACT_S = 0.25 # one tap, one count
TAP_BURST_GAP_S = 0.5  # taps closer than this group into one burst


class _PostureState:
    def __init__(self):
        self.grav = None            # low-passed accel (the gravity read)
        self.rot_ema = 0.0
        self.last_t = None
        self.ref = None             # captured upright, unit vector
        self.still_since = None
        self.angle_ = None
        self._probe_t = -1e9
        # movement-verb episode machine
        self.ep_state = "still"     # "still" | "moving" | "away"
        self.grav_still = None      # gravity at the last settled pose
        self.ep_t0 = 0.0
        self.ep_peak_exc = 0.0
        self.settle_since = None
        self.verb_flag = None       # one-shot [VERB, detail]

    def feed(self, a, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
        dt = max(0.0, min(0.2, now_s - self.last_t))
        self.last_t = now_s

        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        self.rot_ema += min(1.0, dt / 1.0) * (rot - self.rot_ema)

        if self.grav is None:
            self.grav = list(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            self.grav[i] += k * (a[i] - self.grav[i])

        # stillness: quiet gyro, uninterrupted
        quiet = self.rot_ema < STILL_DPS
        if quiet:
            if self.still_since is None:
                self.still_since = now_s
        else:
            self.still_since = None

        # ── movement-verb episodes: still -> moving -> settled again ──
        if self.ep_state == "still":
            if quiet:
                self.grav_still = list(self.grav)   # keep the settled pose fresh
            else:
                self.ep_state = "moving"
                self.ep_t0 = now_s
                self.ep_peak_exc = 0.0
                self.settle_since = None
                # the STILL_DPS edge firing: what the verb machine calls
                # "motion started" — the thing to watch when tuning it
                _tap("ep_start", rot=round(self.rot_ema, 1))
        else:
            exc = self._angle_between(self.grav, self.grav_still)
            if exc is not None:
                self.ep_peak_exc = max(self.ep_peak_exc, exc)
            if self.ep_state == "moving" and now_s - self.ep_t0 > AWAY_S:
                self.ep_state = "away"
                _tap("away")
            if quiet:
                if self.settle_since is None:
                    self.settle_since = now_s
                elif now_s - self.settle_since >= EP_SETTLE_S:
                    self._close_episode(now_s)
            else:
                self.settle_since = None

        # angle vs the captured upright
        if self.ref is not None:
            gx, gy, gz = self.grav
            n = math.sqrt(gx * gx + gy * gy + gz * gz)
            if n > 0.5:
                d = (gx * self.ref[0] + gy * self.ref[1] + gz * self.ref[2]) / n
                self.angle_ = math.degrees(math.acos(max(-1.0, min(1.0, d))))

        if now_s - self._probe_t > 0.5:
            if self.angle_ is not None:
                _probe("posture_deg", round(self.angle_, 1))
            _probe("rot_ema", round(self.rot_ema, 1))
            _probe("still_s", round(now_s - self.still_since, 1)
                   if self.still_since is not None else 0.0)
            self._probe_t = now_s

    def _angle_between(self, a, b):
        if a is None or b is None:
            return None
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na < 0.5 or nb < 0.5:
            return None
        d = sum(x * y for x, y in zip(a, b)) / (na * nb)
        return math.degrees(math.acos(max(-1.0, min(1.0, d))))

    def _close_episode(self, now_s):
        """Motion settled: name what just happened. Verbs about movement,
        never judgments about form."""
        dur = self.settle_since - self.ep_t0
        delta = self._angle_between(self.grav, self.grav_still)
        was_away = self.ep_state == "away"
        self.ep_state = "still"
        self.grav_still = list(self.grav)
        if was_away:
            verb = ["MOVED_OFF", "{:.0f}min".format(max(1, round(dur / 60)))]
        elif delta is not None and delta > SHIFT_DEG:
            verb = ["SHIFT", _flavor(self.grav)]
        elif self.ep_peak_exc > STRETCH_DEG:
            verb = ["FULL_STRETCH", None]
        else:
            verb = ["MICRO_SHIFT", None]
        self.verb_flag = verb
        _tap("verb", v=verb[0], d=verb[1], dur=round(dur, 1),
             peak=round(self.ep_peak_exc, 1),
             delta=round(delta, 1) if delta is not None else None)

    def capture(self):
        if self.grav is None:
            return False
        gx, gy, gz = self.grav
        n = math.sqrt(gx * gx + gy * gy + gz * gz)
        if n < 0.5:
            return False
        self.ref = (gx / n, gy / n, gz / n)
        self.angle_ = 0.0
        _tap("upright_set")
        return True


def _flavor(grav):
    """A coarse, hedged word for where gravity sits — descriptive, never a
    verdict. From the mounting frame (up = X-)."""
    if grav is None:
        return "unknown"
    fwd = math.degrees(math.atan2(grav[2], -grav[0]))
    side = math.degrees(math.atan2(grav[1], -grav[0]))
    if abs(fwd) <= FLAVOR_UP_DEG and abs(side) <= FLAVOR_UP_DEG:
        return "upright-ish"
    if abs(side) > abs(fwd):
        return "sideways-ish"
    return "slumped-ish" if fwd > 0 else "reclined-ish"


_posture = _PostureState()


class _TapState:
    """Explicit feedback: a tap on the housing is a sharp accel spike far
    above anything posture or walking produces. Taps group into bursts
    (x1, x2, x3...) so a deliberate double-tap is distinguishable from an
    accidental knock. NOTE: spikes are short — read the Imu fast (<=20 ms)
    when taps matter; a 50 ms poll can miss soft ones."""

    def __init__(self):
        self.last_tap_t = -1e9
        self.burst_n = 0
        self.burst_flag = None
        self.last_ = None
        self.total = 0
        self.peak_dev = 0.0     # rolling peak since last peak() read

    def feed(self, a, now_s):
        dev = abs(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) - 1.0)
        if dev > self.peak_dev:
            self.peak_dev = dev
        if dev > TAP_G and now_s - self.last_tap_t > TAP_REFRACT_S:
            self.last_tap_t = now_s
            self.burst_n += 1
            self.total += 1
            _tap("tap", g=round(dev, 2), n=self.burst_n)
        if self.burst_n and now_s - self.last_tap_t > TAP_BURST_GAP_S:
            self.burst_flag = [int(now_s * 1000), self.burst_n]
            self.last_ = self.burst_flag
            self.burst_n = 0


_taps = _TapState()


class _Posture:
    """The tree's lean, and how long it has stood unmoved."""

    def angle(self):
        """Degrees away from the captured upright (live, ~1 s smoothed), or
        None before a reference exists. Direction is deliberately absent —
        a slump forward and a lean sideways are both 'away from upright';
        v1 treats them alike."""
        return round(_posture.angle_, 1) if _posture.angle_ is not None else None

    def set_upright(self):
        """Capture the CURRENT gravity as the upright reference. Call while
        the wearer sits/stands the way they'd like to be reminded toward.
        Returns True once captured. The reference lives in organ state:
        it survives instinct hot-swaps, not reboots."""
        return _posture.capture()

    def has_ref(self):
        """True once an upright reference has been captured."""
        return _posture.ref is not None

    def still_s(self):
        """Seconds the body has been holding still (gyro quiet,
        uninterrupted). 0.0 while moving. Walking, stretching, or even a
        good fidget resets it — variation is the point."""
        if _posture.still_since is None or _posture.last_t is None:
            return 0.0
        return max(0.0, _posture.last_t - _posture.still_since)

    def verb(self):
        """[VERB, detail] once, when a motion episode settles — the body's
        movement history in words: MICRO_SHIFT (an adjustment inside a
        sit), SHIFT (the lean changed and STUCK; detail = new flavor),
        FULL_STRETCH (a big excursion that returned), MOVED_OFF (left the
        chair; detail = away time). Consumed on read."""
        f = _posture.verb_flag
        _posture.verb_flag = None
        return f

    def flavor(self):
        """The current lean as a hedged word: upright-ish / slumped-ish /
        reclined-ish / sideways-ish. Descriptive, never a verdict."""
        return _flavor(_posture.grav)

    def lean(self):
        """(fwd_deg, side_deg), anatomical: 0 = standing upright; bending
        FORWARD is positive (+90 = lying on the belly); bending BACK is
        negative (-90 = lying on the back); side is the lateral lean,
        same convention. None before the first gravity read. Unlike
        angle(), this assumes the mounting (up = X-) rather than the
        captured reference."""
        g = _posture.grav
        if g is None:
            return None
        return (round(math.degrees(math.atan2(g[2], -g[0])), 1),
                round(math.degrees(math.atan2(g[1], -g[0])), 1))

    def up_axis(self):
        """Which device axis gravity currently says is up, as "X+".."Z-" —
        the mounting check: worn and upright this must read "X-"."""
        g = _posture.grav
        if g is None:
            return None
        i = max(range(3), key=lambda k: abs(g[k]))
        return "XYZ"[i] + ("+" if g[i] > 0 else "-")


class _Tap:
    """Explicit feedback from the wearer: taps on the housing."""

    def burst(self):
        """[t_ms, count] once, ~0.5 s after a tap group ends — x1 a knock,
        x2+ deliberate. Consumed on read."""
        f = _taps.burst_flag
        _taps.burst_flag = None
        return f

    def last(self):
        """The most recent burst, kept for reading."""
        return _taps.last_

    def total(self):
        """Taps since the session started."""
        return _taps.total

    def peak(self):
        """Peak accel deviation (g) since the last peak() read — the
        calibration meter for TAP_G. Consumed on read."""
        p = round(_taps.peak_dev, 2)
        _taps.peak_dev = 0.0
        return p


class _PostureImu:
    def __init__(self, real):
        self._real = real
        self._acc = (0.0, 0.0, 1.0)

    def getAccel(self):
        a = self._real.getAccel()
        self._acc = a
        _taps.feed(a, time.ticks_ms() / 1000.0)
        return a

    def getGyro(self):
        g = self._real.getGyro()
        _posture.feed(self._acc, g, time.ticks_ms() / 1000.0)
        return g

    def getMag(self):
        return self._real.getMag()


def attach(scope):
    imu = scope["Imu"]
    if isinstance(imu, _PostureImu):
        imu = imu._real
    scope["Imu"] = _PostureImu(imu)
    scope["Posture"] = _Posture()
    scope["Tap"] = _Tap()
