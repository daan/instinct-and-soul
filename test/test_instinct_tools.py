"""Known-answer tests for the Calc pocket-calculator tools.

The strategy: feed each tool a SYNTHETIC signal whose ground truth we know
(a known tempo, known onset times, a known step) and assert it recovers it
within tolerance. Run:  uv run python test/test_instinct_tools.py
"""

import math
import random
import statistics

from instinct_and_soul.instinct_tools import (
    OneEuro, Running, Onset, Periodicity, AlphaBeta, Madgwick)

FS = 100.0
DT = 1.0 / FS


def test_oneeuro_denoises_and_tracks():
    """Reduces noise on a constant, and still tracks a step (low lag)."""
    random.seed(0)
    f = OneEuro(min_cutoff=1.0, beta=0.5)
    raw, out = [], []
    for i in range(int(3 * FS)):
        x = 1.0 + random.gauss(0, 0.5)
        raw.append(x); out.append(f.update(x, i * DT))
    r_std, o_std = statistics.pstdev(raw[100:]), statistics.pstdev(out[100:])
    assert o_std < r_std * 0.6, (o_std, r_std)           # denoises >40%
    f2 = OneEuro(min_cutoff=1.0, beta=0.5); y = 0.0
    for i in range(int(2 * FS)):
        y = f2.update(5.0, i * DT)
    assert abs(y - 5.0) < 0.1, y                          # tracks the step
    return f"noise {r_std:.2f}->{o_std:.2f}, step settles to {y:.2f}"


def test_running_matches_known_stats():
    r = Running(n=10)
    for x in range(1, 13):
        r.push(x)                                         # window = 3..12
    assert abs(r.mean() - 7.5) < 1e-9, r.mean()
    assert abs(r.std() - statistics.pstdev(range(3, 13))) < 1e-6
    assert abs(r.z(7.5)) < 1e-9                           # mean -> z 0
    return f"mean {r.mean():.1f}, std {r.std():.2f}"


def test_onset_finds_known_accents():
    """Impulses every 0.5 s on a noisy baseline -> detect them, on time."""
    random.seed(1)
    true = [round(k * 0.5, 3) for k in range(1, 8)]
    det = []
    od = Onset(win=60, refractory_ms=150)
    for i in range(int(4 * FS)):
        t = i * DT
        sway = 0.15 + 0.05 * math.sin(2 * math.pi * 0.6 * t)   # continuous body motion
        bump = sum(0.8 * math.exp(-((t - tt) ** 2) / (2 * 0.025 ** 2)) for tt in true)
        x = max(0.0, sway + 0.02 * random.gauss(0, 1) + bump)
        if od.step(x, t):
            det.append(t)
    assert abs(len(det) - len(true)) <= 1, (len(det), len(true))
    for d in det:
        assert min(abs(d - tt) for tt in true) < 0.06, d  # within 60 ms
    return f"detected {len(det)}/{len(true)} accents, all within 60 ms"


def test_periodicity_recovers_known_tempo():
    """The headline test: autocorrelation recovers a KNOWN period from a pulse."""
    out = []
    for period in (0.50, 0.46, 0.70):
        p = Periodicity(win_s=2.0, min_s=0.3, max_s=1.0, every_ms=100)
        for i in range(int(4 * FS)):
            t = i * DT
            ph = (t % period) / period
            x = (math.exp(-(ph ** 2) / (2 * 0.08 ** 2))
                 + math.exp(-((ph - 1) ** 2) / (2 * 0.08 ** 2)))
            p.push(x, t)
        est = p.period()
        assert abs(est - period) < 0.05, (period, est)    # within 50 ms
        out.append(f"{period*1000:.0f}->{est*1000:.0f}ms")
    return "recovered " + ", ".join(out)


def test_alphabeta_predicts_and_adapts():
    """Predict-and-correct: converge from a WRONG period, predict the next onset,
    and re-lock when the tempo changes (the anticipation claim)."""
    random.seed(2)
    ab = AlphaBeta(alpha=0.2, beta=0.2, gate=0.45)
    onsets = [round(k * 0.5 + random.gauss(0, 0.01), 4) for k in range(1, 40)]
    ab.correct(onsets[0], period_hint=0.40)               # bootstrap WRONG (0.40 vs 0.50)
    errs = []
    for j in range(1, len(onsets)):
        pred = ab.predict_next()
        if j > 14:
            errs.append(abs(pred - onsets[j]))            # one-step prediction error
        ab.correct(onsets[j])
    assert ab.period() == ab.period()  # not NaN
    assert abs(ab.period() - 0.50) < 0.05, ab.period()    # converged 0.40 -> ~0.50
    assert statistics.mean(errs) < 0.04, statistics.mean(errs)

    ab2 = AlphaBeta(alpha=0.2, beta=0.15)                 # tempo DRIFT 0.5 -> 0.65
    t = 0.0
    ab2.correct(t, period_hint=0.5)
    for k in range(70):
        per = min(0.65, 0.5 + 0.003 * k)                  # gradual, then hold (a dancer drifts)
        t += per
        ab2.correct(t)
    assert abs(ab2.period() - 0.65) < 0.04, ab2.period()
    return (f"period 0.40->{ab.period():.2f}, pred err "
            f"{statistics.mean(errs)*1000:.0f}ms, tracked drift to {ab2.period():.2f}")


def _ang(u, v):
    """Angle in degrees between two 3-vectors."""
    du = math.sqrt(sum(c * c for c in u)) or 1.0
    dv = math.sqrt(sum(c * c for c in v)) or 1.0
    d = sum(a * b for a, b in zip(u, v)) / (du * dv)
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def test_madgwick_recovers_static_tilt():
    """At rest, gravity 'up' should converge to the measured accel direction,
    and report ~no motion through space."""
    # sensor tilted 30 deg about x: gravity reads [0, sin30, cos30] in sensor frame
    g = (0.0, math.sin(math.radians(30)), math.cos(math.radians(30)))
    p = Madgwick(beta=0.2)
    wacc = (0, 0, 0)
    for i in range(int(4 * FS)):
        wacc = p.update(g[0], g[1], g[2], 0.0, 0.0, 0.0, i * DT)
    tilt_err = _ang(p.up(), g)
    motion = math.sqrt(sum(c * c for c in wacc))
    assert tilt_err < 2.0, tilt_err                      # recovers the 30 deg tilt
    assert motion < 0.05, motion                         # at rest -> no world motion
    return f"tilt recovered to {tilt_err:.2f}deg, residual motion {motion:.3f}g"


def test_madgwick_integrates_pure_yaw():
    """A constant yaw rate about gravity integrates to the right angle, and
    leaves tilt (up) unchanged."""
    rate = 90.0                                          # deg/s about world up (z)
    p = Madgwick(beta=0.05)
    secs = 2.0
    for i in range(int(secs * FS)):
        p.update(0.0, 0.0, 1.0, 0.0, 0.0, rate, i * DT)  # level, spinning in yaw
    # yaw from quaternion (rotation about z): angle = 2*atan2(z, w)
    w, x, y, z = p.quat()
    yaw = math.degrees(2.0 * math.atan2(z, w)) % 360.0
    expected = (rate * secs) % 360.0                     # 180 deg
    err = min(abs(yaw - expected), 360.0 - abs(yaw - expected))
    up_err = _ang(p.up(), (0.0, 0.0, 1.0))
    assert err < 5.0, (yaw, expected)                    # integrated yaw correct
    assert up_err < 1.0, up_err                          # yaw doesn't tilt 'up'
    return f"yaw integrated to {yaw:.0f}deg (exp {expected:.0f}), tilt held {up_err:.2f}deg"


def test_madgwick_world_accel_is_frame_stable():
    """The same world-frame push reads the same in world coords no matter how
    the sensor is rotated about gravity. Sensor yawed 90 deg; a push that is
    +x in the sensor frame must still come out along a consistent world axis."""
    # settle two poses: one level, one yawed 90 deg about z, both at rest
    level = Madgwick(beta=0.1)
    yawed = Madgwick(beta=0.1, q=(math.cos(math.radians(45)), 0, 0, math.sin(math.radians(45))))
    for i in range(int(2 * FS)):
        level.update(0, 0, 1, 0, 0, 0, i * DT)
        yawed.update(0, 0, 1, 0, 0, 0, i * DT)
    # a +y push in EACH sensor's own frame (accel = gravity + lateral)
    t = 2.0
    wl = level.update(0.0, 0.5, 1.0, 0, 0, 0, t)
    wy = yawed.update(0.0, 0.5, 1.0, 0, 0, 0, t)
    # level: +y sensor -> +y world. yawed 90 about z: +y sensor -> -x world.
    assert wl[1] > 0.4 and abs(wl[0]) < 0.1, wl
    assert wy[0] < -0.4 and abs(wy[1]) < 0.1, wy
    return f"level push -> world {tuple(round(c,2) for c in wl)}, yawed -> {tuple(round(c,2) for c in wy)}"


def main():
    tests = [test_oneeuro_denoises_and_tracks, test_running_matches_known_stats,
             test_onset_finds_known_accents, test_periodicity_recovers_known_tempo,
             test_alphabeta_predicts_and_adapts,
             test_madgwick_recovers_static_tilt, test_madgwick_integrates_pure_yaw,
             test_madgwick_world_accel_is_frame_stable]
    ok = 0
    for t in tests:
        try:
            msg = t()
            print(f"PASS  {t.__name__:42} {msg}")
            ok += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__:42} {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())
