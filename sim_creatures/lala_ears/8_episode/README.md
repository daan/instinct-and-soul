# lala_ears / 8_episode

Arm 8: **the gesture becomes a sense, and the phrase becomes the voice** —
the last recommendation of the original techno2 analysis, delivered as the
triple.

Until now the lead sonified gestures as events (reversal-triggered notes with
contour). This arm sonifies them as ENVELOPES: the Episode organ segments the
body's motion energy into bounded happenings — begin, arc, land — and the
seed holds one lead note through each gesture, retargeting pitch at every
turnaround and releasing at the landing. Note duration now equals gesture
duration for the first time.

Deltas from `7_pulse`:

1. **organs.py — the Episode sense.** Hysteresis segmentation of motion
   energy (|world accel| + 0.1·|gyro|) against a SLOW (~8 s) relative
   baseline — this dancer never stops, so a gesture is a surge above "lately";
   the slow tau is deliberate anti-washout. Absolute floors keep stillness
   silent; sub-0.25 s surges are jitter and don't count. Calibrated on the
   real clip: ~30 gestures/min, median ~0.35 s, p90 ~1.8 s.
   API: started() / current() / ended() / last(), with duration, peak, and
   attack shape (rise01: struck vs swelled). One-shots consumed on read.
2. **seed_instinct.py** — the lead is an episode-phrase (note_on at gesture
   start, legato retargets at reversals, note_off at landing). The report
   gains `ep=<count>~<median dur>`; MISMATCH becomes gestural (gestures
   without voice trigger it even at moderate mean intensity).
3. **system_prompt.md** — Episode documented as a sense (with rise01 as
   attack shape). Subtraction: `Calc.Onset` leaves the vocabulary — an
   episode's start subsumes it, and the accent-only attractor it seeded in
   every early run loses its tool.

Questions: do lead note durations now track gesture durations (check
note_on→note_off spans vs ep durations)? Does the soul use current() to
shape sound THROUGH a gesture (the swell), and rise01 to articulate
(struck vs swelled)? With Onset gone, does the accent reflex disappear or
get rebuilt from Running?
