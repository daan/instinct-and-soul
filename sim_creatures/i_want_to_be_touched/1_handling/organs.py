"""Organs of this creature: a Handling sense (am I on the table, held, or
being played with — and for how long), a Touch sense (handling segmented into
bounded touch-episodes with quality features), and an Ear (the sense of one's
own voice, inherited from the lala_ears line).

Calibration provenance: thresholds are grounded in recorded sessions of the
real CoreS3 (2026-07-06, sim_creatures/i_want_to_be_touched/0_live_loop/logs).
The gyroscope is the touch channel — |rot| separates the world by orders of
magnitude: on the table 0.26±0.07 dps; a quiet hold ~5; gentle handling ~25;
active play ~285. The accelerometer magnitude carries a device-specific bias
(~0.009 g at rest), so stillness detection never uses it; it serves only for
impact spikes (relative, self-baselined).

All senses are read-only from inside: the instinct can attend to them but
cannot clear, write, feed, or restart them. Fed by interposing on the
instinct's own Imu reads (keep reading ~100 Hz or the senses go stale).
State lives at module level, so it survives instinct hot-swaps.
"""
import math
import time

try:
    from instinct_and_soul.instinct_tools import Calc   # sim
except ImportError:
    from calc import Calc                               # device (lib/calc.py)


# ── Ear (verbatim from the lala_ears line) ──────────────────────────────────

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


# ── Handling ─────────────────────────────────────────────────────────────────

# Contact tiers by smoothed |rot| (dps). Boundaries sit in the empty decades
# between the measured clusters (0.26 / ~5 / ~25 / ~285), with hysteresis via
# a dwell: a new tier must persist DWELL_S before it is reported.
_TIERS = (("table", 0.0), ("held", 1.2), ("handled", 15.0), ("played", 80.0))
_DWELL_S = 0.35
_CONTACT_ROT = 1.2      # any live contact reads above this; the table never does


class _HandlingState:
    def __init__(self):
        self.rot_ema = 0.0
        self.de_base = Calc.Running(n=400)   # slow accel-magnitude baseline (bias)
        self.last_t = None
        self.state = "table"
        self.state_since = 0.0
        self.pending = None            # (tier, since) awaiting dwell
        self.last_contact_t = None     # None until first contact ever
        self.grav = None               # low-passed accel (face detection)
        self.face_ = None              # settled face, e.g. "Z+"
        self.face_cand = None          # (face, since) awaiting settle
        self.turned_flag = None        # one-shot: (from_face, to_face)

    def tier_of(self, rot):
        name = _TIERS[0][0]
        for n, lo in _TIERS:
            if rot >= lo:
                name = n
        return name

    def feed(self, a, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
            self.state_since = now_s
        dt = max(0.0, min(0.1, now_s - self.last_t))
        self.last_t = now_s

        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        self.rot_ema += min(1.0, dt / 0.25) * (rot - self.rot_ema)
        self.de_base.push(abs(math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) - 1.0))

        if self.rot_ema > _CONTACT_ROT:
            self.last_contact_t = now_s

        # tier with dwell hysteresis
        cand = self.tier_of(self.rot_ema)
        if cand == self.state:
            self.pending = None
        elif self.pending is None or self.pending[0] != cand:
            self.pending = (cand, now_s)
        elif now_s - self.pending[1] >= _DWELL_S:
            self.state = cand
            self.state_since = self.pending[1]
            self.pending = None

        # face: low-passed gravity; report a face only once it has settled 1 s
        if self.grav is None:
            self.grav = list(a)
        k = min(1.0, dt / 0.5)
        for i in range(3):
            self.grav[i] += k * (a[i] - self.grav[i])
        gx, gy, gz = self.grav
        mag = math.sqrt(gx*gx + gy*gy + gz*gz)
        if mag > 0.5:
            ax_i = max(range(3), key=lambda i: abs(self.grav[i]))
            cand_face = "XYZ"[ax_i] + ("+" if self.grav[ax_i] > 0 else "-")
            if self.face_cand is None or self.face_cand[0] != cand_face:
                self.face_cand = (cand_face, now_s)
            elif now_s - self.face_cand[1] >= 1.0 and cand_face != self.face_:
                if self.face_ is not None:
                    self.turned_flag = (self.face_, cand_face)
                self.face_ = cand_face

        _touch.feed(self.rot_ema, rot, self.de_base.z(
            abs(math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) - 1.0)), g, now_s)


_handling = _HandlingState()


class _Handling:
    """How this body is being handled right now — derived, never fed."""

    def state(self):
        """ "table" | "held" | "handled" | "played" — the current contact
        tier, smoothed and debounced (~0.35 s). "table" is dead stillness;
        a live hand never reads as table."""
        return _handling.state

    def since_s(self):
        """Seconds the current state has lasted."""
        if _handling.last_t is None:
            return 0.0
        return max(0.0, _handling.last_t - _handling.state_since)

    def alone_s(self):
        """Seconds since the last live contact. 0 while in contact; grows on
        the table. Never resets on its own — only a real touch resets it."""
        if _handling.last_t is None:
            return 0.0
        if _handling.last_contact_t is None:
            return max(0.0, _handling.last_t - _handling.state_since)
        return max(0.0, _handling.last_t - _handling.last_contact_t)

    def face(self):
        """Which body face gravity says is UP, as "X+".."Z-" (display face is
        Z+), or None before the first settled reading. Only changes once the
        new face has been stable ~1 s — mid-tumble it keeps the old answer."""
        return _handling.face_

    def turned(self):
        """(old_face, new_face) once, when the settled face changes — someone
        turned me over. Consumed on read."""
        f = _handling.turned_flag
        _handling.turned_flag = None
        return f


# ── Touch (episode segmentation of contact) ─────────────────────────────────

class _TouchState:
    """Hysteresis segmentation of the rotation stream into bounded touch
    episodes, with quality features. Starts above max(3 dps, 1.6x the recent
    level) so table noise (0.26 dps) can never open an episode; the relative
    gate lets strokes stand out inside an already-active handling session."""

    K_HI, K_LO = 1.6, 1.1
    FLOOR_HI, FLOOR_LO = 3.0, 1.5     # dps
    TAU_S = 8.0
    END_HOLD_S = 0.15
    MIN_DUR_S = 0.12                  # taps are short; below this is jitter

    def __init__(self):
        self.base = 0.0
        self.last_t = None
        self.in_ep = False
        self.start_t = 0.0
        self.peak = 0.0
        self.peak_t = 0.0
        self.peak_z = 0.0             # sharpest accel spike inside the episode
        self.wiggles = 0              # dominant-axis gyro sign reversals
        self.dom_axis = 0
        self.dom_sign = 0
        self.below_since = None
        self.announced = False
        self.last_ep = None
        self.started_flag = False
        self.ended_flag = None

    def feed(self, rot_ema, rot_raw, de_z, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
            self.base = rot_ema
        dt = max(0.0, now_s - self.last_t)
        self.last_t = now_s
        self.base += min(1.0, dt / self.TAU_S) * (rot_ema - self.base)
        hi = max(self.FLOOR_HI, self.base * self.K_HI)
        lo = max(self.FLOOR_LO, self.base * self.K_LO)
        v = rot_ema
        if not self.in_ep:
            if v > hi:
                self.in_ep = True
                self.start_t = now_s
                self.peak = v
                self.peak_t = now_s
                self.peak_z = de_z
                self.wiggles = 0
                self.dom_axis = max(range(3), key=lambda i: abs(g[i]))
                self.dom_sign = 1 if g[self.dom_axis] > 0 else -1
                self.below_since = None
                self.announced = False
        else:
            if v > self.peak:
                self.peak = v
                self.peak_t = now_s
            self.peak_z = max(self.peak_z, de_z)
            gd = g[self.dom_axis]
            if abs(gd) > 10.0:        # deadband: only count real reversals
                s = 1 if gd > 0 else -1
                if s != self.dom_sign:
                    self.dom_sign = s
                    self.wiggles += 1
            if not self.announced and now_s - self.start_t >= self.MIN_DUR_S:
                self.announced = True
                self.started_flag = True
            if v < lo:
                if self.below_since is None:
                    self.below_since = now_s
                elif now_s - self.below_since > self.END_HOLD_S:
                    dur = self.below_since - self.start_t
                    self.in_ep = False
                    if self.announced:
                        rise = (self.peak_t - self.start_t) / dur if dur > 0 else 0.0
                        ep = [int(self.start_t * 1000), int(dur * 1000),
                              round(self.peak, 1), round(max(0.0, min(1.0, rise)), 2),
                              self.wiggles, round(self.peak_z, 1)]
                        self.last_ep = ep
                        self.ended_flag = ep
            else:
                self.below_since = None


_touch = _TouchState()


class _Touch:
    """Handling segmented into bounded touch-episodes: a touch begins, arcs,
    and lets go. Each completed episode is
        [start_ms, dur_ms, peak_dps, rise01, wiggles, impact_z]
    peak_dps: how vigorous (a nudge ~5, a stroke ~30, a shake >150).
    rise01:   attack shape (~0 struck sharply, ~1 swelled to a late peak).
    wiggles:  direction reversals — a tap ~0, a stroke a few, a shake many.
    impact_z: sharpest accel spike inside (a knock/drop reads high)."""

    def started(self):
        """True once, ~0.12 s into a touch. Consumed on read."""
        f = _touch.started_flag
        _touch.started_flag = False
        return f

    def current(self):
        """[start_ms, dur_ms_so_far, peak_so_far] while a touch is happening
        NOW, else None — so you can shape sound THROUGH the touch."""
        if not _touch.in_ep or not _touch.announced:
            return None
        now = _touch.last_t or 0.0
        return [int(_touch.start_t * 1000),
                int((now - _touch.start_t) * 1000), round(_touch.peak, 1)]

    def ended(self):
        """The completed touch episode once, the moment it lets go.
        Consumed on read."""
        f = _touch.ended_flag
        _touch.ended_flag = None
        return f

    def last(self):
        """The most recent completed touch episode, kept for reading."""
        return _touch.last_ep


class _HandlingImu:
    def __init__(self, real):
        self._real = real
        self._acc = (0.0, 0.0, 1.0)

    def getAccel(self):
        a = self._real.getAccel()
        self._acc = a
        return a

    def getGyro(self):
        g = self._real.getGyro()
        _handling.feed(self._acc, g, time.ticks_ms() / 1000.0)
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
    if isinstance(imu, _HandlingImu):
        imu = imu._real
    scope["Imu"] = _HandlingImu(imu)
    scope["Handling"] = _Handling()
    scope["Touch"] = _Touch()
