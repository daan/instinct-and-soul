"""Replays the organ's documented calibration scenarios against the
gate-based kata sense. Each test cites the session in the organ docstring
that made the behavior a requirement. Synthetic speed01 profiles are driven
through rot_dps only (accel held at 1 g) at 200 Hz, matching the seed loop.
speed01 = rot/600, so rot = speed01 * 600."""

import math
from calc import Calc
from kata_sense import KataSense

HZ, DT = 200, 0.005
G1 = (0.0, 0.0, 1.0)   # palm down, magnitude 1 g


def run_profile(segments, grav_fn=None):
    """segments: list of (duration_s, speed01). Returns (events, t)."""
    events = []
    ks = KataSense(Calc, quiet=0.20, spent=0.30, rearm=0.55, launch=0.75,
                   set_dwell_s=0.35, land_hold_s=0.22, refract_s=0.20,
                   max_flight_s=1.2, set_linger_s=0.25,
                   rot_fs=600.0, acc_fs=25.0,
                   speed_tau_s=0.04, grav_tau_s=0.12, act_tau_s=2.0)
    t = 0.0
    for dur, sp in segments:
        n = int(dur / DT)
        for _ in range(n):
            t += DT
            a = grav_fn(t) if grav_fn else G1
            rot = sp * 600.0
            ev = ks.step(a, (rot/1.8, rot/1.8, rot/1.8), t)
            if ev is not None:
                if ev[0] == "launch":
                    if ev[2]:
                        events.append(("chain", {}))
                    events.append(("launch", {"t": t, "from_set": ev[1]}))
                elif ev[0] == "land":
                    events.append(("land", {"t": t, "flight_s": ev[1],
                                            "face": ev[2], "off": ev[3]}))
                else:
                    events.append((ev[0], {}))
    return events, t


def kinds(evs):
    return [k for k, _ in evs]


# ── 1. casual handling stays silent ─────────────────────────────────────
# Session 072717: ~23 s moving about WITHOUT katas, speed01 p50 0.28 /
# max 0.64 — must produce no launches.
evs, _ = run_profile([(2.0, 0.28), (0.3, 0.64), (3.0, 0.28),
                      (0.2, 0.55), (2.0, 0.30), (0.4, 0.64), (2.0, 0.25)])
assert "launch" not in kinds(evs), evs
print("1. casual handling silent:", kinds(evs) or "no events")

# ── 2. a clean kata: set -> strike -> hover lands, from_set=1 ───────────
# Session 073555: strikes read 2.6-3.8, inter-strike hover 0.20-0.27.
evs, _ = run_profile([(1.0, 0.10),        # held pose: arms after 0.35 s
                      (0.15, 3.0),        # the strike
                      (0.30, 0.45),       # follow-through (above SPENT)
                      (1.0, 0.25)])       # hover: collapse -> land
k = kinds(evs)
assert k == ["launch", "land"], evs
assert evs[0][1]["from_set"] == 1, evs
land = evs[1][1]
# flight_s measured to COLLAPSE START (organ: land_since - flight_t0):
# strike 0.15 + follow-through 0.30 = 0.45 s of raw profile, plus ~1 tau
# of EMA lag on the collapse edge — the organ measured the same smoothed
# signal and carried the same lag.
assert 0.44 < land["flight_s"] < 0.53, land
assert land["face"] == "Z+" and land["off"] < 5.0, land
print("2. clean kata: from_set=1, flight {:.2f}s, face {} off {}".format(
    land["flight_s"], land["face"], land["off"]))

# ── 3. chained strikes every ~0.55 s ────────────────────────────────────
# Session 083509: follow-through dips only to 0.35-0.5 between strikes —
# never below SPENT01 — so the organ once swallowed 29 of 52 peaks. Each
# dip below REARM01 must re-arm; each spike must fire a NEW launch.
segs = [(0.6, 0.10)]
for _ in range(5):
    segs += [(0.10, 3.0), (0.45, 0.45)]   # strike, inter-strike dip 0.45
segs += [(1.0, 0.22)]                     # finally rest -> the last lands
evs, _ = run_profile(segs)
k = kinds(evs)
assert k.count("launch") == 5, k
assert k.count("chain") == 4, k           # strikes 2-5 chained
assert k.count("land") == 1, k            # only the concluded one lands
assert evs[0][1]["from_set"] == 1
assert all(e[1]["from_set"] == 0 for e in evs if e[0] == "launch"
           and e is not evs[0]), evs      # chains hold no pose
print("3. chains: 5 launches, 4 chains, 1 landing")

# ── 4. waving overruns, no tone ─────────────────────────────────────────
# Above SPENT01 longer than MAX_FLIGHT_S is waving, not a kata.
evs, _ = run_profile([(0.5, 0.10), (0.15, 1.0), (2.0, 0.40), (1.0, 0.22)])
k = kinds(evs)
assert "overrun" in k and "land" not in k, evs
print("4. waving: overrun, no landing")

# ── 5. the 084354 bug cannot recur ──────────────────────────────────────
# A dip below REARM01 during a flight that then OVERRAN was forgotten at
# the organ's phase boundary, and a 3.46 peak right after went silent.
# The launch gate's hysteresis lives in the gate across all phases.
evs, _ = run_profile([(0.5, 0.10),
                      (0.15, 1.0),        # launch
                      (0.6, 0.40),        # hover (below REARM01: dip seen)
                      (0.8, 0.40),        # ...past MAX_FLIGHT: overrun
                      (0.10, 3.46),       # the once-swallowed strike
                      (1.0, 0.22)])
k = kinds(evs)
assert k.count("launch") == 2, evs        # the 3.46 peak FIRES
assert "overrun" in k, evs
print("5. post-overrun strike fires (the lost-dip bug is structural now)")

# ── 6. the armed-at-landing intent actually holds ───────────────────────
# Organ comment: "the landing stillness IS the next set pose". Measured
# hover reads 0.20-0.27 — above QUIET01 — so the organ's single-threshold
# quiet test disarmed it one tick later. The set gate's dead band keeps
# it armed: a second kata launched from the hover must read from_set=1.
evs, _ = run_profile([(1.0, 0.10),
                      (0.15, 3.0), (0.30, 0.45), (0.8, 0.25),  # kata 1, hover 0.25
                      (0.15, 3.0), (0.30, 0.45), (0.8, 0.25)]) # kata 2 from hover
launches = [e for e in evs if e[0] == "launch"]
assert len(launches) == 2 and kinds(evs).count("land") == 2, evs
assert launches[1][1]["from_set"] == 1, launches
print("6. kata from post-landing hover: from_set=1 (organ intent, now true)")

# ── 7. face classification mid-scenario ─────────────────────────────────
# A strike that ends palm-up must sound Z-: gravity flips during flight.
def flip(t):
    return (0.0, 0.0, 1.0) if t < 1.2 else (0.0, 0.0, -1.0)
evs, _ = run_profile([(1.0, 0.10), (0.15, 3.0), (0.30, 0.45), (1.2, 0.25)],
                     grav_fn=flip)
land = [e for e in evs if e[0] == "land"][0][1]
assert land["face"] == "Z-", land
print("7. flipped landing reads Z- off {}".format(land["off"]))

# ── 8. Gate backward compatibility with Tilt ────────────────────────────
g = Calc.Gate(8, 14, 0.4)                 # positional min_hold_s, as Tilt
g.update(2, 0.0)
for i in range(1, 100):
    g.update(2, 0.02 * i)
for i in range(60):
    e = g.update(30, 2.0 + 0.02 * i)
    if e:
        assert e[0] == "rise" and e[1] == 2.0 and abs(e[2] - 2.0) < 1e-9
assert g.state is True and g.since == 2.0
print("8. Tilt's Gate(low, high, min_hold_s) unchanged")

print("\nall kata parity scenarios pass")
