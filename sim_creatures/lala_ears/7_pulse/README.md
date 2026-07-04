# lala_ears / 7_pulse

Arm 7: **Pulse becomes an organ** — the rhythm sense with nothing to feed and
nothing to fake.

Why: Calc.Periodicity's observe() accepted whatever moments the instinct fed
it, and souls twice manufactured "perfect" regularity — cv() read 0.0 on an
empty instrument (fixed to 9.9), then a soul fed observe() its own loop timer
and celebrated the dancer's "0.29s rhythm" (its own clock, aliased). 4c then
showed the positive case: fed honestly, a soul can EARN a real lock (cv 0.09
at 0.57s ≈ the clip's true pulse). Pulse makes earning the only path.

Deltas from `6_motion_organ`:

1. **organs.py — the Pulse sense.** Watches the same interposed gyro stream
   that feeds Motion; derives period, phase, and a continuous confidence by
   throttled autocorrelation over a 4 s window. No inputs. Honesty built in:
   confidence is 0 until ~1.3 s of signal, 0 on flat signal, 0 when stale
   (Imu unread >1 s); the continuity preference reduces metrical flapping but
   never boosts reported confidence; periods are folded to a dance tactus
   (0.4–0.9 s). Validated on the real clip: median tactus 0.60 s (100 BPM,
   the dance's true pulse), stable across the run, confidences an honest
   0.2–0.45 with one earned 0.66.
2. **seed_instinct.py** — report gains `pulse=<period>s@<conf>`; the chord
   drift waits for the beat (phase near 0) when a confident pulse exists —
   the light phase idiom.
3. **system_prompt.md** — Pulse documented as a sense (with the reading guide:
   0.2–0.5 is a real human pulse, low means "no pulse", not "not yet").
   Subtraction: `Calc.Periodicity` leaves this creature's vocabulary; with
   AlphaBeta already gone, the entire feedable-rhythm surface is out.

Questions: do rhythm intents now cite pulse/confidence instead of building
trackers? Does any soul use phase() musically beyond the seeded chord idiom
(beat-aligned lead, phase-shaped swells)? Does anything try to reconstruct a
feedable tracker from Calc primitives (the appetite finding a third hole)?
