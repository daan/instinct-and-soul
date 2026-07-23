"""Organs of the kata-master: a Kata sense (the still->swift->still arc,
segmented live), Motion (orientation, travel, fluency), Handling (in-hand
vs set-down, aloneness, faces), and an Ear (the sense of one's own voice).

Inherited from the air_drum line with deliberate changes: Strike, Touch and
Familiar are absent (recurrence over completed katas arrives later in the
ladder), everything magnetometer is stripped (the StickS3 has no mag — this
body is YAW-BLIND: a forward cut and a sideways cut with the same wrist
pose are the same pose; the six distinguishable end-poses are the six
gravity faces), and the new Kata organ owns the gesture grammar: a pose
held still, one decisive motion, a pose held still again.

Mounting: the device rides the BACK of the hand, X toward the wrist,
display outward. So the six faces read as hand poses:
    Z+  palm down        Z-  palm up
    X-  fingers up       X+  fingers down (X points wrist-ward)
    Y+/Y-  hand blade vertical (chop pose), sign by which edge is up.

All senses are read-only from inside; state survives instinct hot-swaps;
fed by interposing on the instinct's own Imu reads (~100 Hz or stale).
"""
import math
import time

try:
    from instinct_and_soul.instinct_tools import Calc   # sim
except ImportError:
    from calc import Calc                               # device (lib/calc.py)

try:
    from instinct_and_soul.creature_sim.stethoscope import tap as _tap, probe as _probe
except ImportError:
    def _tap(kind, **payload):
        pass

    def _probe(name, value):
        pass


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

    def __getattr__(self, name):
        # anything the Ear doesn't record (all_off, master_volume, future
        # driver methods) passes straight through to the real synth
        return getattr(self._real, name)

    def program(self, ch, program):
        return self._real.program(ch, program)

    def control_change(self, ch, control, value):
        _cc_total[0] += 1
        return self._real.control_change(ch, control, value)

    def pitch_bend(self, ch, value):
        _cc_total[0] += 1          # counted like a controller, not recorded
        return self._real.pitch_bend(ch, value)

    def note_on(self, ch, note, velocity=80):
        _record([time.ticks_ms(), "on", ch, note, velocity])
        return self._real.note_on(ch, note, velocity)

    def note_off(self, ch, note, velocity=0):
        _record([time.ticks_ms(), "off", ch, note])
        return self._real.note_off(ch, note, velocity)

    def note(self, ch, note, ms, velocity=80):
        _record([time.ticks_ms(), "note", ch, note, velocity, ms])
        return self._real.note(ch, note, ms, velocity)


# ── Motion (orientation + travel; ported from the air_drum line, mag-free) ──

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
        # live fluency: jerk (rate of change of world accel) normalized by
        # the motion's own amplitude — smooth sweeps score high, rattly or
        # braced motion low, regardless of how big the movement is.
        self.prev_wacc = None
        self.last_gyro_t = None
        self.jerk_ema = 0.0
        self.amp_ema = 0.0
        self.fl01 = 1.0

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
        if self.last_gyro_t is not None:
            dt = now_s - self.last_gyro_t
            if 0 < dt < 0.1 and self.prev_wacc is not None:
                j = math.sqrt(sum((x - y) ** 2
                                  for x, y in zip(self.wacc, self.prev_wacc))) / dt
                amp = math.sqrt(sum(x * x for x in self.wacc))
                k = min(1.0, dt / 0.3)
                self.jerk_ema += k * (j - self.jerk_ema)
                self.amp_ema += k * (amp - self.amp_ema)
                ratio = self.jerk_ema / (6.0 + 10.0 * self.amp_ema)
                # quadratic in the ratio: spreads the scale so flowing motion
                # sits ~0.9 and rattling/braced motion ~0.35 (calibrated on
                # the 2026-07 gentle vs rough recordings)
                self.fl01 = max(0.0, min(1.0, 1.0 / (1.0 + 0.12 * ratio * ratio)))
        self.last_gyro_t = now_s
        self.prev_wacc = self.wacc


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

    def fluency(self):
        """0..1, live: how SMOOTH the current motion is — jerk normalized by
        the motion's own amplitude, so a small gentle sweep and a big gentle
        sweep both read high, while rattling, braced, or stop-start motion
        reads low whatever its size. ~0.7+ is flowing; ~0.3 is rough."""
        return round(_motion.fl01, 2)


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

        if self.rot_ema > _CONTACT_ROT:
            self.last_contact_t = now_s

        # tier with dwell hysteresis
        cand = self.tier_of(self.rot_ema)
        if cand == self.state:
            self.pending = None
        elif self.pending is None or self.pending[0] != cand:
            self.pending = (cand, now_s)
        elif now_s - self.pending[1] >= _DWELL_S:
            _tap("state", frm=self.state, to=cand)
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
                    _tap("turned", frm=self.face_, to=cand_face)
                self.face_ = cand_face


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


# ── Kata (the still -> swift -> still arc) ──────────────────────────────────

def _face_off(v):
    """Nearest orthogonal face of a gravity vector, and how far off it is:
    ("X+".."Z-", degrees between the vector and that axis), or (None, None)
    while gravity is unreadable (mid-flight, freefall)."""
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 0.5:
        return None, None
    i = max(range(3), key=lambda k: abs(v[k]))
    face = "XYZ"[i] + ("+" if v[i] > 0 else "-")
    off = math.degrees(math.acos(max(-1.0, min(1.0, abs(v[i]) / n))))
    return face, round(off, 1)


class _KataState:
    """The kata grammar as a body sense: a pose held STILL, one SWIFT motion,
    a pose held still again. Segmented by a composite speed01 — the louder of
    rotation (gyro) and linear shove against full-scale references — because
    a straight punch is mostly shove and a turning cut mostly rotation;
    either alone misses half the vocabulary.

    Shove is the RAW accel-magnitude deviation from 1 g, deliberately NOT
    the Madgwick world-frame linear accel: session 20260711_080305 showed
    the fusion's pose so corrupted after 1000+ dps strikes (worsened by
    wifi stall gaps) that gravity leaked 11-14 m/s^2 of phantom shove into
    a HOVERING hand — holding tones open, blocking the re-arm (a visible
    strike at 9.0 s never launched), and preventing landings. The raw
    deviation is orientation-free: a still hand reads ~0 whatever the
    fusion believes (measured on the same session: hover max 2.6,
    follow-through 8.9, strikes 79-85, casual handling 7.5 m/s^2 — the
    ACC_FS=25 scale holds).

    Calibrated 2026-07-11 against two labeled sessions, one negative, one
    positive. 20260711_072717 (~23 s moving about WITHOUT katas): speed01
    p50 0.28 / max 0.64 — the original 0.30 launch gate sat BELOW the
    median of ordinary handling and the swoosh ran ~45% of the time; at
    0.75 that session is silent. 20260711_073555 (real strikes): strikes
    read speed01 2.6-3.8 (rot 800-1200 dps, shove 65-95 m/s^2) — 3-5x
    above the gate — while inter-strike hover reads 0.20-0.27 and the
    stillest half-second in the session reads 0.17. That last number
    killed the original quiet rule (rot<35 dps AND acc<1.5): a hand
    NEVER reads that still, so no flight ever landed, every flight hung
    to the 1.2 s overrun with the sound hanging with it, and strikes
    thrown during the hang were swallowed. Everything now sits on the one
    speed01 scale, a monotone ladder with the measured gaps between its
    rungs:  QUIET01 0.20 < SPENT01 0.30 < REARM01 0.55 < LAUNCH01 0.75.
    A flight ends when the motion COLLAPSES (below SPENT01, briefly
    held), not when the hand is laboratory-still. Still owed: a session
    of deliberately HELD poses to place QUIET01 (set-arming) and to check
    the pose read at landing (2_tones' question).

    Phases: "loose" (moving, not set) / "set" (speed01 < QUIET01 held
    SET_DWELL_S: armed) / "flight" (one motion in the air). Any burst
    opens a flight — the swoosh must ride every swift motion — but only a
    flight launched FROM a set pose is a kata candidate; from_set rides
    the events so the seed can treat them apart. A flight ends by LANDING
    (speed01 below SPENT01 held LAND_HOLD_S — the motion collapsed), by
    OVERRUN (above SPENT01 past MAX_FLIGHT_S — waving, not a kata), or by
    a CHAINED launch: session 20260711_083509 (strikes every ~0.5-0.6 s)
    showed the follow-through dipping only to 0.35-0.5 between strikes —
    never below SPENT01 — so flights never ended and 29 of 52 peaks were
    swallowed mid-flight. Now a mid-flight dip below REARM01 re-arms:
    the next crossing of LAUNCH01 opens a NEW flight (launched() fires
    again; the unconcluded motion is discarded — chains hold no pose, so
    they can never be katas). Air_drum's dip-gated early re-arm, on the
    speed scale."""

    QUIET01 = 0.20        # speed01 below this reads as a held pose (the
                          # stillest measured half-second reads 0.17)
    SET_DWELL_S = 0.35    # stillness must hold this long to arm
    LAUNCH01 = 0.75       # speed01 above this opens a flight (strikes
                          # measured 2.6-3.8; casual handling max 0.64)
    REARM01 = 0.55        # ...and requires speed01 to have DIPPED below
                          # this since the last launch — ONE rule, tracked
                          # across phases (self.low). Without any dip rule,
                          # overruns relaunched the same burst 6 ms later
                          # (session 072717); when the dip memory lived only
                          # inside the flight, a dip before an overrun was
                          # forgotten at the phase boundary and a 3.46 peak
                          # right after the overrun went silent (084354,
                          # t=64.6). Follow-through rides 0.35-0.63 and
                          # must not re-arm; real inter-strike dips reach
                          # 0.2-0.34.
    SPENT01 = 0.30        # the motion has collapsed below this (inter-
                          # strike hover measured 0.20-0.27)
    REFRACT_S = 0.20      # min flight age before a chained launch may fire
    LAND_HOLD_S = 0.22    # collapse must hold this long to conclude a flight
    MAX_FLIGHT_S = 1.2    # above SPENT01 longer than this is waving, not a kata
    ROT_FS = 600.0        # dps at speed01 = 1.0
    ACC_FS = 25.0         # m/s^2 at speed01 = 1.0

    def __init__(self):
        self.last_t = None
        self.rot_fast = 0.0
        self.acc_fast = 0.0
        self.speed01 = 0.0
        self.grav_fast = None      # fast gravity EMA (~0.12 s): the pose read
        self.phase = "loose"
        self.quiet_since = None
        self.land_since = None     # first dip below SPENT01 within a flight
        self.set_since = None
        self.flight_t0 = 0.0
        self.from_set = 0
        self.low = 1e9             # lowest speed01 since the last launch —
                                   # tracked across phases; a launch needs
                                   # low < REARM01 (the dip proves a NEW burst)
        self.peak_rot = 0.0
        self.peak_acc = 0.0
        self.flu_sum = 0.0
        self.flu_t = 0.0
        self.launched_flag = None
        self.landed_flag = None
        self.overrun_flag = None
        self.last_ = None
        self.n = 0
        self._probe_t = -1e9
        self._speed_probe = 0.0

    def feed(self, a, g, now_s):
        if self.last_t is None:
            self.last_t = now_s
        dt = max(0.0, min(0.05, now_s - self.last_t))
        self.last_t = now_s
        k = min(1.0, dt / 0.04)

        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        dyn = abs(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
                  - 1.0) * 9.81
        self.rot_fast += k * (rot - self.rot_fast)
        self.acc_fast += k * (dyn - self.acc_fast)
        self.speed01 = max(self.rot_fast / self.ROT_FS,
                           self.acc_fast / self.ACC_FS)

        if self.grav_fast is None:
            self.grav_fast = list(a)
        kg = min(1.0, dt / 0.12)
        for i in range(3):
            self.grav_fast[i] += kg * (a[i] - self.grav_fast[i])

        quiet = self.speed01 < self.QUIET01
        self.low = min(self.low, self.speed01)

        self._speed_probe = max(self._speed_probe, self.speed01)
        if now_s - self._probe_t > 0.1:
            _probe("speed01_peak", round(self._speed_probe, 3))
            _probe("rot_fast", round(self.rot_fast, 1))
            _probe("acc_fast", round(self.acc_fast, 2))
            self._probe_t = now_s
            self._speed_probe = 0.0

        if self.phase == "flight":
            self.peak_rot = max(self.peak_rot, self.rot_fast)
            self.peak_acc = max(self.peak_acc, self.acc_fast)
            self.flu_sum += _motion.fl01 * dt
            self.flu_t += dt
            if (self.speed01 > self.LAUNCH01 and self.low < self.REARM01
                    and now_s - self.flight_t0 >= self.REFRACT_S):
                # a new strike before the last one concluded: chain — the
                # unconcluded motion held no pose, so it was never a kata
                _tap("chain", ms=int((now_s - self.flight_t0) * 1000))
                self.flight_t0 = now_s
                self.from_set = 0
                self.low = self.speed01
                self.peak_rot = self.rot_fast
                self.peak_acc = self.acc_fast
                self.flu_sum = 0.0
                self.flu_t = 0.0
                self.land_since = None
                self.launched_flag = [int(now_s * 1000), 0]
                return
            if self.speed01 < self.SPENT01:      # the motion collapsed
                if self.land_since is None:
                    self.land_since = now_s
                elif now_s - self.land_since >= self.LAND_HOLD_S:
                    self._land(now_s)
            else:
                self.land_since = None
                if now_s - self.flight_t0 > self.MAX_FLIGHT_S:
                    self.overrun_flag = int(now_s * 1000)
                    _tap("overrun", ms=int((now_s - self.flight_t0) * 1000))
                    self.phase = "loose"
                    self.quiet_since = None
            return

        # loose or set
        if self.speed01 > self.LAUNCH01 and self.low < self.REARM01:
            self.from_set = 1 if self.phase == "set" else 0
            self.phase = "flight"
            self.flight_t0 = now_s
            self.low = self.speed01
            self.peak_rot = self.rot_fast
            self.peak_acc = self.acc_fast
            self.flu_sum = 0.0
            self.flu_t = 0.0
            self.quiet_since = None
            self.land_since = None
            self.launched_flag = [int(now_s * 1000), self.from_set]
            _tap("launch", from_set=self.from_set)
            return
        if quiet:
            if self.quiet_since is None:
                self.quiet_since = now_s
            if self.phase == "loose" and now_s - self.quiet_since >= self.SET_DWELL_S:
                self.phase = "set"
                self.set_since = self.quiet_since
                _tap("set")
        else:
            self.quiet_since = None
            if self.phase == "set":
                self.phase = "loose"     # slow drift out of the pose: disarm

    def _land(self, now_s):
        flight_ms = int((self.land_since - self.flight_t0) * 1000)
        face, off = _face_off(self.grav_fast)
        flu = self.flu_sum / self.flu_t if self.flu_t > 1e-3 else 1.0
        ep = [int(now_s * 1000), flight_ms, int(self.peak_rot),
              round(self.peak_acc, 1), face, off, self.from_set,
              round(flu, 2)]
        self.last_ = ep
        self.landed_flag = ep
        self.n += 1
        _tap("kata", ep=ep)
        if off is not None:
            _probe("off_deg", off)
        # the landing stillness IS the next set pose: armed immediately,
        # so a chained kata can launch without re-earning the dwell
        self.phase = "set"
        self.set_since = self.land_since
        self.quiet_since = self.land_since
        self.land_since = None


_kata = _KataState()


class _Kata:
    """The kata grammar: stillness, one decisive motion, stillness."""

    def phase(self):
        """ "loose" | "set" | "flight" — set means still long enough that the
        next swift motion counts as launched from a pose."""
        return _kata.phase

    def speed(self):
        """Live composite speed, ~0 still .. ~1 a full-vigor motion (can
        exceed 1). The louder of rotation and linear shove against their
        full-scale references — the signal the swoosh should ride."""
        return round(_kata.speed01, 3)

    def motion(self):
        """[rot_dps, shove_ms2] — the two raw speeds behind speed(), smoothed
        fast (~40 ms). shove is the accel-magnitude deviation from 1 g
        (orientation-free — immune to fusion drift). For calibrating the
        blend: a straight punch is mostly shove, a turning cut mostly rot."""
        return [round(_kata.rot_fast, 1), round(_kata.acc_fast, 2)]

    def set_s(self):
        """Seconds the current set pose has been held (0.0 unless set)."""
        if _kata.phase != "set" or _kata.set_since is None:
            return 0.0
        return max(0.0, (_kata.last_t or 0.0) - _kata.set_since)

    def pose(self):
        """(face, off_deg) of gravity right now against the nearest
        orthogonal face — live, from the fast pose read (~0.12 s). Only
        meaningful while quiet; mid-flight it reads the whip, not a pose."""
        if _kata.grav_fast is None:
            return None, None
        return _face_off(_kata.grav_fast)

    def launched(self):
        """[t_ms, from_set01] once, the moment a swift motion opens — also
        for a CHAINED strike (a new burst mid-flight after a real dip).
        Consumed on read — start the swoosh NOW; a late swoosh is a lie.
        from_set01: 1 if it launched from a held pose (a kata candidate),
        0 if from loose motion or a chain (sonify; can't conclude a kata)."""
        f = _kata.launched_flag
        _kata.launched_flag = None
        return f

    def landed(self):
        """[t_ms, flight_ms, peak_rot_dps, peak_acc_ms2, face, off_deg,
        from_set01, fluency01] once, when the motion COLLAPSES and stays
        collapsed (~LAND_HOLD_S after it actually stopped — flight_ms
        measures to the stop, not the confirmation). Consumed on read —
        this is the tone moment. face/off_deg: the end pose against the
        nearest orthogonal, or None if gravity was unreadable; the hand
        is near-still but not frozen at the read, so precision is
        2_tones' question."""
        f = _kata.landed_flag
        _kata.landed_flag = None
        return f

    def overrun(self):
        """t_ms once, when a flight ran past MAX_FLIGHT_S without settling —
        waving, not a kata. Consumed on read — end the swoosh, no tone."""
        f = _kata.overrun_flag
        _kata.overrun_flag = None
        return f

    def last(self):
        """The most recent completed kata, kept for reading."""
        return _kata.last_

    def count(self):
        """Completed katas since the session started."""
        return _kata.n


class _KataImu:
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
        _motion.feed_gyro(g, now_s)          # fuse first: Kata reads wacc
        _handling.feed(self._acc, g, now_s)
        _kata.feed(self._acc, g, now_s)
        return g

    def getMag(self):
        return self._real.getMag()           # StickS3: always (0, 0, 0)


def attach(scope):
    synth = scope["Synth"]
    if isinstance(synth, _EarSynth):    # re-attach on hot-swap: don't double-wrap
        synth = synth._real
    scope["Synth"] = _EarSynth(synth)
    scope["Ear"] = _Ear()

    imu = scope["Imu"]
    if isinstance(imu, _KataImu):
        imu = imu._real
    scope["Imu"] = _KataImu(imu)
    scope["Handling"] = _Handling()
    scope["Motion"] = _Motion()
    scope["Kata"] = _Kata()
