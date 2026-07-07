"""Organs of this creature: a Handling sense (am I on the table, held, or
being played with — and for how long), a Touch sense (handling segmented into
bounded touch-episodes with quality features), a Hunger interoception (an
appetite for touch that grows with neglect and satiates with handling — the
body's own dynamics, so a hungry creature and a sated one are different
creatures even when the world outside is identical), and an Ear (the sense of
one's own voice, inherited from the lala_ears line).

Hunger is unfeedable in both directions: it derives entirely from the same
interposed stream as Handling — the instinct can neither feed it (to fake
satiation) nor bump it (to justify neediness). Its appetite has an innate
structure, a bodily fact like Episode's floors: quiet sustained contact
satiates deepest, vigorous play feeds more slowly, and sharp knocks startle
rather than satiate.

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


# ── Motion (orientation + travel; ported from the lala_ears line) ───────────

class _MotionState:
    """Madgwick fusion fed by interposing on the instinct's own Imu reads.
    Boots from the first accel sample (tilt from gravity), never resets, so
    orientation and travel survive every instinct hot-swap."""

    def __init__(self):
        self.pose = None            # created on the first accel sample
        self.flow = Calc.Flow()
        self.acc = None             # freshest accel (g), waiting for a gyro
        self.wacc = (0.0, 0.0, 0.0)
        self.vel = (0.0, 0.0, 0.0)

    def feed_accel(self, a):
        if self.pose is None:
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
        """Latest world-frame linear acceleration (m/s^2), gravity removed:
        motion THROUGH SPACE as a signed vector in fixed world axes (x, y
        horizontal; z = up — +z is being lifted, -z dropping)."""
        return _motion.wacc

    def velocity(self):
        """Travel through space: signed velocity (~m/s, world axes)."""
        return _motion.vel

    def reversal(self):
        """None | (axis, sign): the moment travel on the dominant axis turns
        around. Consumed on read — one reader should own it."""
        return _motion.flow.reversal()


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

        _hunger.feed(self.state, now_s)
        _touch.feed(self.rot_ema, rot, self.de_base.z(
            abs(math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) - 1.0)),
            g, _motion.wacc, now_s)


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


# ── Hunger (interoception: the appetite for touch) ──────────────────────────

class _HungerState:
    """level 0..1 relaxes toward a target set by the contact tier, each with
    its own timescale (an exponential approach — no counters to game):
        alone (table)   -> toward 1 over ~150 s   (neglect makes hunger)
        held            -> toward 0 over ~45 s    (quiet contact feeds deepest)
        handled         -> toward 0 over ~60 s
        played          -> toward 0 over ~140 s   (thrilling, but thin food)
    startle 0..1 spikes when a touch lands with a hard knock (impact) and
    decays in ~8 s — arousal, not nourishment."""

    TAU = {"table": (1.0, 150.0), "held": (0.0, 45.0),
           "handled": (0.0, 60.0), "played": (0.0, 140.0)}
    STARTLE_Z = 8.0
    STARTLE_TAU = 8.0

    def __init__(self):
        self.level = 0.5          # wakes wanting: alone before this began
        self.startle = 0.0
        self.last_t = None

    def feed(self, state, now_s):
        if self.last_t is None:
            self.last_t = now_s
        dt = max(0.0, min(0.5, now_s - self.last_t))
        self.last_t = now_s
        target, tau = self.TAU.get(state, (1.0, 150.0))
        self.level += min(1.0, dt / tau) * (target - self.level)
        self.level = max(0.0, min(1.0, self.level))
        self.startle -= min(1.0, dt / self.STARTLE_TAU) * self.startle

    def knock(self, impact_z):
        if impact_z >= self.STARTLE_Z:
            self.startle = min(1.0, self.startle + 0.35 + 0.03 * impact_z)


_hunger = _HungerState()


class _Hunger:
    """The body's appetite for touch — derived, never fed, never fakeable."""

    def level(self):
        """0..1: how much this body wants touch right now. Grows with
        neglect (~150 s toward full), melts with contact — quiet holding
        satiates deepest (~45 s), vigorous play more slowly (~140 s). Starts
        the session at 0.5: awake and wanting."""
        return round(_hunger.level, 3)

    def startle(self):
        """0..1: the lingering jolt of a hard knock (a drop, a slam). Spikes
        when a touch lands with high impact, decays in ~8 s. Arousal, not
        satisfaction — a startled body is not a fed one."""
        return round(_hunger.startle, 3)


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

    def feed(self, rot_ema, rot_raw, de_z, g, wacc, now_s):
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
                self.vsum = 0.0        # world-frame |vertical| accel, integrated
                self.hsum = 0.0        # world-frame |horizontal| accel, integrated
                self.dom_axis = max(range(3), key=lambda i: abs(g[i]))
                self.dom_sign = 1 if g[self.dom_axis] > 0 else -1
                self.below_since = None
                self.announced = False
        else:
            if v > self.peak:
                self.peak = v
                self.peak_t = now_s
            self.peak_z = max(self.peak_z, de_z)
            # direction of travel during the touch, in the gravity frame
            self.vsum += abs(wacc[2]) * dt
            self.hsum += math.sqrt(wacc[0] * wacc[0] + wacc[1] * wacc[1]) * dt
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
                        tot = self.vsum + self.hsum
                        vert = self.vsum / tot if tot > 1e-6 else 0.5
                        ep = [int(self.start_t * 1000), int(dur * 1000),
                              round(self.peak, 1), round(max(0.0, min(1.0, rise)), 2),
                              self.wiggles, round(self.peak_z, 1), round(vert, 2)]
                        self.last_ep = ep
                        self.ended_flag = ep
                        _hunger.knock(self.peak_z)
            else:
                self.below_since = None


_touch = _TouchState()


class _Touch:
    """Handling segmented into bounded touch-episodes: a touch begins, arcs,
    and lets go. Each completed episode is
        [start_ms, dur_ms, peak_dps, rise01, wiggles, impact_z, vert01]
    peak_dps: how vigorous (a nudge ~5, a stroke ~30, a shake >150).
    rise01:   attack shape (~0 struck sharply, ~1 swelled to a late peak).
    wiggles:  direction reversals — a tap ~0, a stroke a few, a shake many.
    impact_z: sharpest accel spike inside (a knock/drop reads high).
    vert01:   the touch's direction in the gravity frame — ~1 purely
              up-and-down, ~0 purely sideways, ~0.5 mixed or turning."""

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
        _motion.feed_accel(a)
        return a

    def getGyro(self):
        g = self._real.getGyro()
        now_s = time.ticks_ms() / 1000.0
        _motion.feed_gyro(g, now_s)          # fuse first: Touch reads wacc
        _handling.feed(self._acc, g, now_s)
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
    scope["Hunger"] = _Hunger()
    scope["Motion"] = _Motion()
