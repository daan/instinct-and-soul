# lala_ears / 4_timed_ears

Arm 4 of the ears experiment: **the report gains a timing percept** (and the
toolbox stops lying about rhythm).

Arm 3 established adoption 2/2: the report-and-warrant seed idiom survives
every rewrite and turns reflections metrological. But run 2 exposed the blind
spot: the soul disciplines what its report lets it see (counts/dynamics) and
fantasizes in the dimension it can't (rhythm) — celebrating "perfect CV=0.00"
beat-locks at wandering periods. Fuel for the fantasy was a toolbox bug:
`Periodicity.cv()` returned 0.0 (= metronomic) when it had under 3 observed
intervals, i.e. no data read as perfection.

Deltas from `3_ears_warrant_reflection`:

1. **seed_instinct.py** — the window report adds `lead_gap=`: the median
   inter-onset interval of the lead notes actually voiced in the window
   ("-" under 3 notes). A rhythm the soul believes in becomes checkable
   against its own output.
2. **Harness fix (global, in `instinct_tools.py` and
   `creatures/midi_dancer/lib/calc.py`)** — `cv()` now returns 9.9 when
   under-observed: no data means unpredictable, not metronomic. Runs before
   2026-07-03 are not strictly comparable on periodicity behavior.
3. **system_prompt.md** — one clause documenting the new cv() semantics
   ("low cv is earned, never assumed").

Questions: does the false beat-lock attractor die with its fuel? Do rhythm
claims in intents start citing lead_gap? Does run-1-style calibration
discipline now replicate?

Score as arm 3, plus: rhythm-claim intents vs lead_gap evidence, and
Periodicity/AlphaBeta adoption rate.
