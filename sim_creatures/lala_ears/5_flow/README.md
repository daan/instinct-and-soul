# lala_ears / 5_flow

Arm 5: **the first organ arm — travel through space, delivered as the triple**
(honest instrument + seed idiom + report percept).

Attacks the one pathology every analysis ranked as the musical core and no
ears arm could touch: pitch was always quantized *posture* (the gravity
up-vector), never *trajectory* — a conductor's sweep produced tilt-jitter
stutter instead of a phrase.

Deltas from `4b_cc_report`:

1. **Toolbox (global): `Calc.Flow`** — leaky integrator over Madgwick's
   world-frame acceleration → signed velocity (~m/s, world axes) +
   `reversal()`: a one-shot event when travel along the dominant axis turns
   around (the conductor's ictus). Honest by construction: the leak bounds
   drift, feeding gaps decay instead of integrating garbage, magnitude is
   documented as short-horizon. Mirrored into
   `creatures/midi_dancer/lib/calc.py` for device parity.
2. **Subtraction:** `Calc.AlphaBeta` removed from this creature's
   system_prompt (the class remains in the harness; the vocabulary is
   per-creature). Souls used every tool they were told about — the shelf is
   now smaller where it was most abused.
3. **seed_instinct.py** — the lead's tilt-bin trigger is gone: notes fire at
   `flow.reversal()` (swing turnarounds), pitch rides vertical velocity
   (rising travel sings higher), note velocity carries stroke speed, 420 ms
   notes with portamento. The report gains `rev=` (turnarounds per window),
   the body-side percept matching the new voice.
4. **system_prompt.md** — Flow documented in the Calc section, measurement
   register.

Questions: does reversal-triggered, contour-pitched lead survive rewrites the
way the report idiom did? Does `lead_gap` now sit at gesture rate (~0.5–1 s)
instead of jitter rate (0.10 s)? Do intents start speaking in travel terms
(sweeps, landings) rather than tilt zones? And does the soul keep `rev=`
against `lead=` honest — notes per turnaround ≈ 1?

Score as 4b, plus: lead notes per reversal, lead_gap distribution, and any
soul-initiated changes to the contour mapping.
