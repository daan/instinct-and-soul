"""Organs of the air-drum: a Strike sense (the hit, at hit-time), a Touch
sense (swings as bounded episodes with an effort vector), a Familiar sense
(recurring swing-manners — the kit-to-be), Motion (orientation, travel,
fluency), Handling (in-hand vs set-down, aloneness), and an Ear (the sense
of one's own voice).

Inherited from the i_want_to_be_touched line with two deliberate changes:
Hunger and Together are absent (the drum's interoception, Groove, arrives
with the Timing organ in 3_coach), and Familiar's identity space EXCLUDES
vigor — a soft tap and a hard hit on the same drum are the same drum at
different velocities. Weight is expression here, not identity.

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
    from instinct_and_soul.creature_sim.stethoscope import tap as _tap
except ImportError:
    def _tap(kind, **payload):
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

        _touch.feed(self.rot_ema, rot, self.de_base.z(
            abs(math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) - 1.0)),
            g, _motion.wacc, _motion.vel, _motion.fl01, now_s)


_handling = _HandlingState()


def _alone_now_s():
    """Seconds since last live contact, straight from the Handling state."""
    if _handling.last_t is None:
        return 0.0
    if _handling.last_contact_t is None:
        return max(0.0, _handling.last_t - _handling.state_since)
    return max(0.0, _handling.last_t - _handling.last_contact_t)


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


# ── Familiar (recurrence: this shape of touch again) ────────────────────────

class _FamiliarState:
    """Online clustering of completed touch episodes, so recurrence becomes a
    percept. Heritage: the pose->motion->pose 'kata' recognizers of pre-IMU
    sonification toys — always sonify the motion, then reward the recognized
    form on top. Here the form is a cluster in touch-feature space:
    [log dur, log peak, rise, wiggle-rate, vert], nearest exemplar within a
    radius, else a new gesture. Exemplars drift slowly with the person (EMA),
    so a gesture can mature. Familiarity is EARNED: only recurrence raises a
    count; nothing the instinct does can create a familiar gesture."""

    R = 0.8            # assignment radius (3 manner dims)
    CORE = 0.5         # exemplar learns only from hits inside CORE*R —
                       # rim assignments count but don't drag the center
                       # (greedy-blob prevention)
    KNOWN_AT = 3       # seen this many times -> recognized() fires
    MAX_G = 12         # exemplar budget; least-known oldest is evicted

    def __init__(self):
        self.gs = []             # {'id','v','n','last_ms','face'}
        self.next_id = 1
        self.last_ = None        # [id, n, dist01] of most recent episode
        self.recognized_flag = None

    def _vec(self, ep):
        dur_s = max(0.12, ep[1] / 1000.0)
        # Identity is MANNER of motion only: direction, closedness, reversal
        # tempo, vigor. Duration and size are excluded — a rhythmic gesture
        # gets chopped into 1-2-cycle episodes whose length and extent wobble
        # 2-3x between chops (measured: one up-down bounce scattered over 5
        # clusters when they were included). rise is excluded because attack
        # is ill-defined for cyclic motion. FLUENCY is excluded on principle:
        # the same gesture done more smoothly must stay the same gesture —
        # identity holds while quality improves, or coaching is impossible.
        # Size, attack and fluency remain expressive dimensions of the
        # episode itself; they just don't decide WHICH gesture it was.
        # Weight (peak) is EXCLUDED here, unlike the touch creature: on a
        # drum, soft and hard hits on the same drum are the same drum.
        return [min(8.0, ep[4] / dur_s) / 4.0,
                ep[6] / 0.30,
                ep[8] / 0.45]

    def observe(self, ep, face):
        v = self._vec(ep)
        best, bd = None, 1e9
        for g in self.gs:
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(v, g['v'])))
            if d < bd:
                bd, best = d, g
        if best is not None and bd <= self.R:
            if bd <= self.R * self.CORE:
                for i in range(len(v)):
                    best['v'][i] += 0.15 * (v[i] - best['v'][i])
            best['n'] += 1
            best['last_ms'] = ep[0]
            self.last_ = [best['id'], best['n'], round(min(1.0, bd / self.R), 2)]
            _tap("familiar", id=best['id'], n=best['n'],
                 dist=round(bd, 2), R=self.R)
            if best['n'] >= self.KNOWN_AT:
                self.recognized_flag = list(self.last_)
                _tap("recognized", id=best['id'], n=best['n'],
                     dist=round(bd, 2))
        else:
            if len(self.gs) >= self.MAX_G:
                self.gs.sort(key=lambda g: (g['n'], g['last_ms']))
                self.gs.pop(0)
            self.gs.append({'id': self.next_id, 'v': v, 'n': 1,
                            'last_ms': ep[0], 'face': face})
            self.last_ = [self.next_id, 1, 0.0]
            _tap("familiar_new", id=self.next_id,
                 nearest=round(bd, 2) if best is not None else None, R=self.R)
            self.next_id += 1
        self._reunify()

    def _reunify(self):
        """Merge clusters whose exemplars have drifted within each other's
        core: a rhythmic gesture chopped into wobbly 1-2-cycle episodes
        seeds several nearby clusters that converge as sightings accumulate
        — when they meet, they were one gesture all along. The older id
        survives (the soul may have already named it)."""
        i = 0
        while i < len(self.gs):
            j = i + 1
            while j < len(self.gs):
                a, b = self.gs[i], self.gs[j]
                d = math.sqrt(sum((x - y) ** 2 for x, y in zip(a['v'], b['v'])))
                if d <= self.R * 0.6:
                    old, new = (a, b) if a['id'] <= b['id'] else (b, a)
                    w = new['n'] / max(1, old['n'] + new['n'])
                    for k in range(len(old['v'])):
                        old['v'][k] += w * (new['v'][k] - old['v'][k])
                    old['n'] += new['n']
                    old['last_ms'] = max(old['last_ms'], new['last_ms'])
                    _tap("reunify", kept=old['id'], merged=new['id'], d=round(d, 2))
                    self.gs.remove(new)
                    if self.last_ and self.last_[0] == new['id']:
                        self.last_ = [old['id'], old['n'], self.last_[2]]
                    continue
                j += 1
            i += 1


_familiar = _FamiliarState()


class _Familiar:
    """The body's sense of recurrence: 'this shape of touch again'. Ids are
    arbitrary names, not meanings — which gestures matter, and what a
    familiar one deserves from your voice, is yours."""

    def last(self):
        """[id, seen_count, dist01] for the most recent completed touch.
        dist01 ~0: performed canonically; ~1: barely recognizable — how
        expressively they bent the gesture this time."""
        return list(_familiar.last_) if _familiar.last_ else None

    def recognized(self):
        """[id, seen_count, dist01] once, when a completed touch lands in a
        gesture seen >=3 times — they are offering you something they have
        offered before. Consumed on read."""
        f = _familiar.recognized_flag
        _familiar.recognized_flag = None
        return f

    def gestures(self):
        """All known gestures as [id, seen_count], best-known first."""
        return sorted(([g['id'], g['n']] for g in _familiar.gs),
                      key=lambda x: -x[1])

    def guess(self):
        """[id, confidence01] for the touch happening NOW, or None. A guess,
        not a fact: computed from the unfinished touch's manner so far,
        against gestures already seen 3+ times. Confidence grows as the
        gesture unfolds and commits — ~0.3 s in it's a hunch, half-way it
        hardens, and it can still change before the touch ends. None while
        no touch is underway, too little has happened, or nothing known is
        near."""
        t = _touch
        if not t.in_ep or not t.announced or t.last_t is None:
            return None
        dur_s = max(0.12, t.last_t - t.start_t)
        tot = t.vsum + t.hsum
        vert = t.vsum / tot if tot > 1e-6 else 0.5
        net = math.sqrt(sum(d * d for d in t.disp))
        curl = 1.0 - min(1.0, net / t.path) if t.path > 0.05 else 0.0
        v = [min(8.0, t.wiggles / dur_s) / 4.0,
             vert / 0.30,
             curl / 0.45]
        cands = [g for g in _familiar.gs if g['n'] >= _familiar.KNOWN_AT]
        if not cands:
            return None
        ds = sorted((math.sqrt(sum((a - b) ** 2 for a, b in zip(v, g['v']))), g['id'])
                    for g in cands)
        d1, gid = ds[0]
        if d1 > _familiar.R * 1.2:
            return None
        margin = (min(1.0, (ds[1][0] - d1) / _familiar.R)
                  if len(ds) > 1 else max(0.0, 1.0 - d1 / _familiar.R))
        evidence = min(1.0, dur_s / 0.6)
        conf = round(evidence * (0.3 + 0.7 * margin), 2)
        return [gid, conf]


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

    def feed(self, rot_ema, rot_raw, de_z, g, wacc, vel, flu, now_s):
        _strike.feed(de_z, rot_ema, now_s)
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
                self.path = 0.0        # travel path length (size of the gesture)
                self.disp = [0.0, 0.0, 0.0]   # net displacement (for curl)
                self.flu_sum = 0.0     # time-integrated live fluency
                self.flu_t = 0.0
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
            # extent, straightness, and manner of the travel
            spd = math.sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2])
            self.path += spd * dt
            for i in range(3):
                self.disp[i] += vel[i] * dt
            self.flu_sum += flu * dt
            self.flu_t += dt
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
                        net = math.sqrt(sum(d * d for d in self.disp))
                        curl = (1.0 - min(1.0, net / self.path)
                                if self.path > 0.05 else 0.0)
                        flu = (self.flu_sum / self.flu_t
                               if self.flu_t > 1e-3 else 1.0)
                        ep = [int(self.start_t * 1000), int(dur * 1000),
                              round(self.peak, 1), round(max(0.0, min(1.0, rise)), 2),
                              self.wiggles, round(self.peak_z, 1), round(vert, 2),
                              round(self.path, 2), round(curl, 2), round(flu, 2)]
                        self.last_ep = ep
                        self.ended_flag = ep
                        _tap("touch", ep=ep)
                        _familiar.observe(ep, _handling.face_)
            else:
                self.below_since = None


_touch = _TouchState()


class _Touch:
    """Handling segmented into bounded touch-episodes: a touch begins, arcs,
    and lets go. Each completed episode is
        [start_ms, dur_ms, peak_dps, rise01, wiggles, impact_z, vert01,
         size, curl01, fluency01]
    peak_dps: how vigorous (a nudge ~5, a stroke ~30, a shake >150).
    rise01:   attack shape (~0 struck sharply, ~1 swelled to a late peak).
    wiggles:  direction reversals — a tap ~0, a stroke a few, a shake many.
    impact_z: sharpest accel spike inside (a knock/drop reads high).
    vert01:   direction in the gravity frame — ~1 up-and-down, ~0 sideways.
    size:     extent of travel (path length, relative units) — a big sweep
              and a small one at the same speed finally differ.
    curl01:   open vs closed travel — ~0 it went somewhere (a stroke, a
              throw-line); ~1 it came back on itself (a circle, a wave's
              oscillation, a shake-in-place). Closed forms tell apart by
              their wiggles: many = oscillating, few = circling.
    fluency01: how smoothly it was performed — jerk normalized by amplitude.
              Manner, not identity: the same gesture done more smoothly is
              the same gesture, scored better."""

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


# ── Strike (the hit, at hit-time) ────────────────────────────────────────────

class _StrikeState:
    """An air-drum hit is the sharp accel transient where the wrist snaps —
    the moment the imagined skin is struck. Fires THE INSTANT the spike
    crosses threshold (soundable within the reflex loop), carrying the
    swing's direction-so-far so a drum can be chosen immediately. The
    completed Touch episode refines identity for the NEXT hit; nothing is
    ever corrected retroactively — a wrong drum is forgivable, a late one
    is not."""

    TH_Z = 4.0            # accel spike, self-baselined sigmas
    MIN_ROT = 25.0        # must be mid-swing — a table knock is not a hit
    REFRACTORY_S = 0.12   # fastest credible hand (~8 hits/s)

    def __init__(self):
        self.last_hit_t = -1e9
        self.hit_flag = None
        self.last_ = None
        self.n = 0

    def feed(self, de_z, rot_ema, now_s):
        if (de_z >= self.TH_Z and rot_ema >= self.MIN_ROT
                and now_s - self.last_hit_t >= self.REFRACTORY_S):
            self.last_hit_t = now_s
            t = _touch
            tot = (t.vsum + t.hsum) if t.in_ep else 0.0
            vert = t.vsum / tot if tot > 1e-6 else 0.5
            g = _Familiar().guess()
            gid = g[0] if (g and g[1] >= 0.3) else None
            hit = [int(now_s * 1000), round(de_z, 1), round(vert, 2),
                   int(rot_ema), gid]
            self.last_ = hit
            self.hit_flag = hit
            self.n += 1
            _tap("strike", hit=hit)


_strike = _StrikeState()


class _Strike:
    """The hit, at hit-time — the drum's fastest sense."""

    def hit(self):
        """[t_ms, vigor_z, vert01_so_far, rot_dps, guess_id|None] once, the
        moment a strike lands. Consumed on read — sound it NOW; identity
        (guess_id, from gestures seen 3+ times) may be None early in a
        session or a swing."""
        f = _strike.hit_flag
        _strike.hit_flag = None
        return f

    def last(self):
        """The most recent hit, kept for reading."""
        return _strike.last_

    def count(self):
        """Hits since the session started."""
        return _strike.n


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
    scope["Motion"] = _Motion()
    scope["Familiar"] = _Familiar()
    scope["Strike"] = _Strike()
