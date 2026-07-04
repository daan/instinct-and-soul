# lala_ears / 4b_cc_report

Arm 4b: **the last unsensed output dimension, plus the cadence backport.**

Arm 4 (2 runs) showed the pattern holding both ways: sensed dimensions get
disciplined (note density, rhythm honesty), unsensed ones don't — both runs
still poured ~100k control changes while every note pathology got fixed.

Deltas from `4_timed_ears`:

1. **organs.py** — the Ear counts control changes (`Ear.cc_total()`,
   cumulative; notes stay buffered as before).
2. **seed_instinct.py** — the window report adds `cc=` (control messages
   poured out this window). Prediction: the CC flood gets disciplined within a
   few reflections, the same way note spam was.
3. **seed_instinct.py** — cadence backport: `last_report_t` persists in `Mem`,
   so a rewrite no longer resets the report clock (run A of arm 4 discovered
   and fixed this itself; the seed now ships the fix). First boot still
   reports early.
4. **system_prompt.md** — Ear section documents `cc_total()`.

Score as arm 4, plus: CC count per window over the run, and whether any
intent cites `cc=`.
