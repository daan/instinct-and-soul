"""Known-answer tests for the Calc pocket-calculator tools.

The strategy: feed each tool a SYNTHETIC signal whose ground truth we know
(a known tempo, known onset times, a known step) and assert it recovers it
within tolerance. Run:  uv run python test/test_instinct_tools.py
"""

import math
import random
import statistics

from instinct_and_soul.instinct_tools import (
    OneEuro, Running, Onset, Periodicity, AlphaBeta)

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


def main():
    tests = [test_oneeuro_denoises_and_tracks, test_running_matches_known_stats,
             test_onset_finds_known_accents, test_periodicity_recovers_known_tempo,
             test_alphabeta_predicts_and_adapts]
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
