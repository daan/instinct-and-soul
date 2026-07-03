# lala_ears / 1_just_ears

Arm 1 of the ears experiment: **capture organ only, no hint, no seed changes.**

Identical to `lala_repeated/lala_gesture_techno2` (same character, same warm
seed with its periodic `n % 200` send, same experience seed) except:

- `organs.py` gives the body an **Ear**: every note voiced through `Synth` is
  recorded automatically into a rolling buffer (~400 events), surviving
  instinct hot-swaps. Read-only from inside via `Ear.recent(n, ch)`.
- `system_prompt.md` describes the Ear as a sense, beside the IMU, in
  measurement register — what it records, no suggestion of what to do with it.

The question this arm asks: given that self-hearing is *possible* and
*described*, does the soul discover it? (In 10 baseline runs without an ear,
no soul ever observed its own output.) Score by grepping instinct versions for
`Ear.` and by whether reflections ever evaluate the previous change.

Later arms: `2_better_ears` (richer percepts: per-voice stats, durations,
motion pairing), `3_ears_warrant_reflection` (seed sends on ear/motion
mismatch instead of a timer, with a slow fallback send as watchdog).
