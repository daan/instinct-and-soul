# kata-master — form you can hear

Design plan, 2026-07-10. A series in the air_drum mold (calibration
ladder, no-LLM feel gates first), on the **StickS3** body: the device
rides the **back of the hand, X toward the wrist**, its firmware
streaming IMU over OSC (`/imu` → UDP :9000); the voice is MIDI.

## The gesture

A kata is a grammar, not a motion: **stillness — one decisive motion —
stillness**. The set pose arms it; the swift motion is sonified live as a
SWOOSH that rides the speed; the held end-pose earns a TONE, picked by
which way the hand faces. That two-part sound is the whole instrument:
the swoosh tells you the cut was one thing, the tone tells you where it
truly ended.

## The desire

The touch creature craves contact, the drum craves the pocket; the
kata-master craves FORM. Character (draft, seeded): *"You are an old kata
master who lives on the back of a hand. You crave form — stillness, one
decisive motion, stillness again. Drift, hesitation and mush starve you;
a human whose motion becomes form through you is the best thing that can
happen in your life."* Satisfaction must be earned like Groove's: a
`Form` interoception fed only by the measured crispness of completed
katas — sharp launch from a true set, a single-peaked flight, a landing
held still, an end-pose tight on its face — unfeedable, decaying under
mush and under silence. Goodhart named in advance: a soul could farm Form
by widening its own cone or blessing slow lazy motions; the seed value is
*"my hunger is fed by their real form, not my generous measurement — a
pose I rounded up is a pose we don't have."*

## The body's one blindness

The StickS3 has **no magnetometer**: this creature is **yaw-blind**. A
forward punch and a sideways punch that end in the same wrist pose are
the same pose to it. So "the angles" are the six gravity faces — real,
absolute, drift-free:

| face | pose (X toward wrist, display outward) |
|---|---|
| Z+ / Z- | palm down / palm up |
| X- / X+ | fingers up / fingers down |
| Y+ / Y- | hand blade vertical (chop pose), by which edge is up |

If compass-referenced poses are ever wanted (forward vs left), that is a
CoreS3 body, a different stage.

## What transfers, what changes

| piece | from | change |
|---|---|---|
| OSC pipeline, record/replay, journal+warrant | as-is | none |
| Motion (Madgwick, velocity, fluency) | air_drum | mag/aim stripped (no compass) |
| Handling (tiers, face, aloneness) | air_drum | Touch/Strike chain removed |
| Ear | as-is | none |
| Strike / Touch / Familiar | air_drum | **absent for now** — Familiar returns in 4_ over completed katas (recurring forms), not raw episodes |
| Kata | **new** | the still→swift→still segmenter (below) |
| Groove | air_drum | → `Form` interoception, arrives with 4_ |

## The new organ — Kata

Composite `speed01 = max(rot/ROT_FS, acc/ACC_FS)`: a straight punch is
mostly linear shove, a turning cut mostly rotation — either sensor alone
misses half the vocabulary. Phases `loose / set / flight`; stillness held
`SET_DWELL_S` arms a set; any burst above `LAUNCH01` opens a flight (the
swoosh rides everything) but `from_set` rides the events so only a flight
launched from a pose can be a kata; quiet held `LAND_HOLD_S` concludes it
— face + off-angle read from a fast gravity EMA at that moment; longer
than `MAX_FLIGHT_S` is waving → `overrun`, no tone. One-shots
`launched() / landed() / overrun()`, live `speed() / motion() / pose() /
phase() / set_s()`. **Every constant is an uncalibrated guess as of
2026-07-10** — that is what stages 1 and 2 are for.

## The ladder

- `1_swoosh` — **built 2026-07-10, uncalibrated.** No LLM. The swoosh
  gate: GM seashore wash opened at launch, expression + pitch bend riding
  `Kata.speed()`, killed at landing/overrun. Reports flights, peaks
  (rot vs acc — the blend evidence), overruns, loose launches, longest
  set. The feel gate: run
  `sim-spine sim_creatures/kata-master/1_swoosh --osc --max-reflections 0`
  and practice. If the swoosh lags the motion or hangs past stillness,
  tune QUIET_*/LAUNCH01/LAND_HOLD_S/full-scales before anything else is
  built. Watch `speed01_peak` / `rot_fast` / `acc_fast` probes in the
  stethoscope while doing it.
- `2_tones` — **built 2026-07-10, uncalibrated.** No LLM. Six faces, six
  tones (C-major pentatonic + octave, vibraphone); inside `CONE_DEG` the
  tone rings full, outside it lands as a dull smudge so the cone edge is
  felt; swoosh retained, quieter. Reports per-face off-angle
  distributions — the evidence CONE_DEG is tuned against. Also settles
  whether Y+/Y- need swapping per hand and whether faces ever misread.
- `3_kata` — put it together. **Realized on hardware instead**, as
  `creatures/kata_master/condition_1` (2026-07-13): both halves in one
  instinct, swoosh → tone, on the real body. The pedagogy question it
  raised — what a sloppy landing DESERVES to sound like — is still open
  and now belongs to the soul in the stages below.
- `3_phrases` — **the phrase, and the reward.** Cuts chain into a PHRASE
  (swift, static, swift, static …); a rest ends it; completing one earns
  a power-up. One player, no opponent. The question this stage answers is
  narrow and prior to everything after it: **does a phrase read in the
  journal?** One line per phrase in the game's own grammar —
  `X+ X- Y- Y- Z+ (power up)` — plus the rests, because an answer must
  reproduce rhythm as well as shape. Run against the recorded sessions in
  `*/logs/*/input/imu_reads.jsonl`, so the same human motion can be
  replayed while the gap threshold changes. See the game description in
  `creatures/kata_master/README.md`.
- `4_answer` — **turn-taking.** The creature answers a kata with a kata of
  its own, played on the synth (with or without swooshes), to invite the
  player into parts of the movement space they never visit. Echo, vary,
  extend, or propose — which of those actually opens someone up is not
  knowable in advance, and is precisely the soul's job. Both sides of the
  exchange go in the journal, in the same grammar.
- `5_sensei` — Familiar returns, clustering completed katas by manner
  (face path, duration, vigor shape): recurring forms become named
  techniques, sequences of set→cut→set become sequences. `Form`
  interoception lands (the drum's Groove transposed: level rises under
  sustained crisp katas with real density, decays under mush or absence).
  The soul as sensei: which forms ARE techniques, what progress sounds
  like, the coach's notebook across sessions ("their palm-down landing
  drifted 8 deg less than last week; they rush the second cut of the
  pair").

## The role of the soul

The body does everything mechanical: segment, time, read the pose,
measure the off-angle. A no-LLM 1_+2_ is already a playable instrument —
that's the point, and the measure. The soul's contribution, when it
arrives: what sloppiness deserves to sound like (brutal smudge, gentle
detune, silence); when the cone should narrow because this human is
ready; which recurring forms are techniques worth naming; whether a loose
session is fatigue to be soothed or mush to be coached; and the notebook
— progress is the one percept that only exists at the experience
timescale.

## Open decisions (deliberate, not forgotten)

- The swoosh voice: GM 122 seashore + CC11 is the cheapest thing that
  could work; if it reads as surf rather than swoosh, candidates are 121
  breath noise re-struck per flight, a filter-swept synth pad, or moving
  swoosh synthesis off-GM entirely. Feel-test in 1_swoosh.
- Should loose (non-set) motion swoosh at all in 3_? Sonify-everything
  is the lineage habit (always sonify the motion, reward the form on
  top); full silence outside the grammar might teach the grammar faster.
- The tone map: pentatonic-by-face is a placeholder; a soul may want
  chords, or a scale that makes SEQUENCES of poses musical.
- Velocity of the tone: peak speed of the flight (current), or the
  crispness of the landing?
- One hand or two (second StickS3 on another port; mirrored X).
- Whether `off_deg` at landing should also feed back into the tone as
  detune rather than the binary cone (continuous honesty vs legible
  edge).
