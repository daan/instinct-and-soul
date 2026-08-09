"""kata_sense — the Kata organ dissolved into three Calc.Gates + bookkeeping.

Written in the style it would take inside an instinct's run(): all judgments
are named constants at the top (they would move to the seed, provenance to
experience.md), all mechanism is Calc. This module exists to PROVE parity
with the organ's documented behaviors before the seed is rewritten; the test
file replays every scenario the organ's calibration history records.

The three gates over one speed01 signal:

  launch_g  low=REARM01  high=LAUNCH01  hold 0/0, refractory REFRACT_S
      Every strike is a rise — including chains, because the gate's own
      re-arm (a dip below REARM01) is exactly the organ's dip rule, and
      its hysteresis state lives in the gate across all phases, which is
      the structural fix for the 084354 lost-dip bug.
  flight_g  low=SPENT01  high=LAUNCH01  fall_hold LAND_HOLD_S
      Flight existence. Its fall IS the landing, and the fall's t_edge is
      the organ's land_since — so flight_ms comes out exact for free.
  set_g     low=QUIET01  high=SPENT01   fall_hold SET_DWELL_S
      Armed while fallen. The 0.20..0.30 dead band is NEW (the organ
      disarmed on a single threshold at QUIET01) and it matters: measured
      post-landing hover reads 0.20-0.27, so the organ's "landing
      stillness IS the next set pose" was disarmed one tick later by its
      own quiet test. The band lets the stated intent actually hold.
"""


def make_kata_sense(Calc, emit):
    """emit(kind, **info) receives: launch(from_set), chain, land(flight_s,
    peak_rot, face, off), overrun. Returns step(rot_dps, accel_g3, now_s)."""

    # ── judgments (seed constants; provenance -> experience.md) ──────────
    QUIET01 = 0.20        # below this, the hand reads as holding a pose
    SPENT01 = 0.30        # below this, a motion has collapsed
    REARM01 = 0.55        # a launch needs a dip below this since the last
    LAUNCH01 = 0.75       # above this, a swift motion opens
    SET_DWELL_S = 0.35    # stillness must hold this long to arm
    LAND_HOLD_S = 0.22    # collapse must hold this long to land
    REFRACT_S = 0.20      # min age of a flight before a chain may fire
    SET_LINGER_S = 0.25   # a launch counts as FROM the pose if the pose
                          # held within this long before it — the strike's
                          # own onset ramp breaks quiet a few ticks before
                          # the launch gate can confirm, and a pose held
                          # until the strike began must not be
                          # disqualified by its own strike. (The organ
                          # read set-ness instantaneously at launch, so
                          # its from_set was ~always 0 on real ramps —
                          # the untested half.)
    MAX_FLIGHT_S = 1.2    # longer than this above SPENT01 is waving
    ROT_FS = 600.0        # dps at speed01 = 1.0
    ACC_FS = 25.0         # m/s^2 at speed01 = 1.0
    SPEED_TAU_S = 0.04    # the speed sense's reflex time
    GRAV_TAU_S = 0.12     # the pose read at landing: fast, but not raw

    # ── mechanism (Calc) ─────────────────────────────────────────────────
    import math
    rot_ema = Calc.Ema(SPEED_TAU_S)
    acc_ema = Calc.Ema(SPEED_TAU_S)
    grav = Calc.Ema(GRAV_TAU_S)
    launch_g = Calc.Gate(REARM01, LAUNCH01, rise_hold_s=0.0,
                         fall_hold_s=0.0, refractory_s=REFRACT_S)
    flight_g = Calc.Gate(SPENT01, LAUNCH01, rise_hold_s=0.0,
                         fall_hold_s=LAND_HOLD_S)
    set_g = Calc.Gate(QUIET01, SPENT01, rise_hold_s=0.0,
                      fall_hold_s=SET_DWELL_S)

    st = {
        "hover_armed": False,  # the landing stillness counts as a pose
        "armed_t": -1e9,       # last moment a pose was held
        "flight_t0": None,     # None = no live flight (overrun kills it)
        "peak_rot": 0.0,
        "speed01": 0.0,
    }

    def step(rot_dps, a, now_s):
        # speed01: the louder of rotation and RAW shove — raw deviation
        # from 1 g, NOT Madgwick world accel, which leaked 11-14 m/s^2 of
        # phantom shove into a hovering hand after 1000+ dps strikes
        # (session 080305; the lesson that birthed the organs).
        dyn = abs(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
                  - 1.0) * 9.81
        r = rot_ema.update(rot_dps, now_s)
        d = acc_ema.update(dyn, now_s)
        g = grav.update(a, now_s)
        s = max(r / ROT_FS, d / ACC_FS)
        st["speed01"] = s

        le = launch_g.update(s, now_s)
        fe = flight_g.update(s, now_s)
        set_g.update(s, now_s)   # edges unused: armed derives from STATE,
                                 # because the gate boots by silent adoption
                                 # (born still = armed at once; the organ
                                 # waited one dwell after power-on, a
                                 # difference of 0.35 s once per boot)

        # armed: a confirmed still pose (set gate fallen), or the landing
        # stillness — measured hover reads 0.20-0.27, inside the set
        # gate's dead band, so only truly stilling (gate falls) or a stir
        # above SPENT01 can end the hover's claim to be a pose
        if st["hover_armed"] and s > SPENT01:
            st["hover_armed"] = False
        if (not set_g.state) or st["hover_armed"]:
            st["armed_t"] = now_s

        # a launch: opens a flight, or chains inside one
        if le is not None and le[0] == "rise":
            from_set = 1 if now_s - st["armed_t"] <= SET_LINGER_S else 0
            if st["flight_t0"] is None:
                emit("launch", t=le[1], from_set=from_set)
            else:
                # a new strike before the last concluded: the unconcluded
                # motion held no pose, so it was never a kata
                emit("chain", t=le[1])
                emit("launch", t=le[1], from_set=0)
            st["flight_t0"] = le[1]
            st["peak_rot"] = r
            st["hover_armed"] = False

        if st["flight_t0"] is not None:
            if r > st["peak_rot"]:
                st["peak_rot"] = r

            # landing: the flight gate's fall, its t_edge = collapse start
            if fe is not None and fe[0] == "fall":
                f, off = Calc.face(g)
                emit("land", t=fe[1],
                     flight_s=fe[1] - st["flight_t0"],
                     peak_rot=st["peak_rot"], face=f, off=off)
                st["flight_t0"] = None
                st["hover_armed"] = True   # the landing stillness IS the
                                           # next set pose

            # overrun: too long without collapsing — waving, not a kata
            elif now_s - st["flight_t0"] > MAX_FLIGHT_S:
                emit("overrun", t=now_s)
                st["flight_t0"] = None

        return s

    return step
