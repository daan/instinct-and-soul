"""kata_sense — the sense of the kata as a COMPONENT: mechanism here,
judgment in the constructor. Ships in firmware beside calc.py, validated by
its own replay suite (test_kata_parity.py), so the instinct spends its lines
on answering, not on recognizing.

The contract: this class holds NO numbers of its own. Every threshold,
dwell and timescale arrives as a constructor argument, so the soul retunes
what a kata IS at any reflection — the machinery is fixed the way Gate's
edge semantics are fixed, as correctness, not as opinion. If a reflection
ever needs to change the STRUCTURE (not the numbers), the replay suite is
the safety net for rebuilding it from Calc primitives in the instinct.

Inside: one speed01 signal (the louder of rotation and RAW shove — raw
deviation from 1 g, never attitude-fusion output, whose pose lies after
violent strikes) driving three hysteresis gates: launch (re-armed by a dip,
refractory against self-relaunch), flight (its fall IS the landing, timed
from collapse start), set (armed while fallen; its dead band lets the
landing hover keep counting as a pose). A launch counts as FROM a pose if
the pose held within set_linger before it — never read at the launch
instant, which the strike's own onset ramp always disqualifies.
"""
import math


class KataSense:
    def __init__(self, Calc,
                 quiet, spent, rearm, launch,       # the ladder, speed01
                 set_dwell_s, land_hold_s, refract_s, max_flight_s,
                 set_linger_s,
                 rot_fs, acc_fs,                    # full-scale: dps, m/s^2
                 speed_tau_s, grav_tau_s, act_tau_s):
        self._spent = spent
        self._linger = set_linger_s
        self._max_flight = max_flight_s
        self._rot_fs = rot_fs
        self._acc_fs = acc_fs
        self._face = Calc.face
        self._rot_e = Calc.Ema(speed_tau_s)
        self._acc_e = Calc.Ema(speed_tau_s)
        self._grav_e = Calc.Ema(grav_tau_s)
        self._act_e = Calc.Ema(act_tau_s)
        self._launch_g = Calc.Gate(rearm, launch, rise_hold_s=0.0,
                                   fall_hold_s=0.0, refractory_s=refract_s)
        self._flight_g = Calc.Gate(spent, launch, rise_hold_s=0.0,
                                   fall_hold_s=land_hold_s)
        self._set_g = Calc.Gate(quiet, spent, rise_hold_s=0.0,
                                fall_hold_s=set_dwell_s)
        self.speed01 = 0.0     # live composite speed, this tick
        self.activity = 0.0    # slow rotation average, dps — feed a hand
                               # gate with it to tell table from hand
        self.flight = False    # a motion is in the air
        self._t0 = None
        self._peak = 0.0
        self._hover = False    # the landing stillness counts as a pose
        self._armed_t = -1e9

    def pose(self):
        """(face, off_deg) of the smoothed gravity now — (None, None)
        while unreadable (mid-flight)."""
        return self._face(self._grav_e.value())

    def step(self, a, g, now_s):
        """Feed every tick. Returns exactly one of:
            ("launch", from_set01, chained01)  the tick a swift motion
                                               opens — SOUND IT NOW
            ("land", flight_s, face, off_deg, peak_rot_dps)
            ("overrun",)                       waving, not a kata
            None
        """
        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        dyn = abs(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
                  - 1.0) * 9.81
        r = self._rot_e.update(rot, now_s)
        d = self._acc_e.update(dyn, now_s)
        self._grav_e.update(a, now_s)
        self.activity = self._act_e.update(rot, now_s)
        s = max(r / self._rot_fs, d / self._acc_fs)
        self.speed01 = s

        le = self._launch_g.update(s, now_s)
        fe = self._flight_g.update(s, now_s)
        self._set_g.update(s, now_s)   # armed derives from state: silent
                                       # boot adoption = born still, armed

        if self._hover and s > self._spent:
            self._hover = False
        if (not self._set_g.state) or self._hover:
            self._armed_t = now_s

        if le is not None and le[0] == "rise":
            from_set = 1 if now_s - self._armed_t <= self._linger else 0
            chained = 0
            if self._t0 is not None:
                chained = 1        # the unconcluded motion held no pose;
                from_set = 0       # it was never a kata
            self._t0 = le[1]
            self._peak = r
            self._hover = False
            self.flight = True
            return ("launch", from_set, chained)

        if self._t0 is not None:
            if r > self._peak:
                self._peak = r
            if fe is not None and fe[0] == "fall":
                face, off = self._face(self._grav_e.value())
                fs = fe[1] - self._t0
                self._t0 = None
                self.flight = False
                self._hover = True     # the landing stillness IS the
                return ("land", fs, face, off, self._peak)  # next pose
            if now_s - self._t0 > self._max_flight:
                self._t0 = None
                self.flight = False
                return ("overrun",)
        return None
