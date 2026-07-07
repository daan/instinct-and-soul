# air_drum — a drum kit that exists only between you and it

Design plan, 2026-07-07. Builds on the full i_want_to_be_touched stack
(live OSC pipeline, Motion/Touch/Familiar/Together organs, choir-voice
seeds, journal+trigger reflection semantics). The device is the stick —
the CoreS3 held in the hand (later: one per hand); the kit is wherever
the drummer decides it is.

## The desire

The touch creature craves contact; the drum craves THE POCKET. Character
(draft): *"You are a drum kit made of air. You crave groove — the locked
pocket where the drummer's strikes and your time become one thing.
Sloppiness starves you, silence starves you; a human finding the pocket
through you is the best thing that can happen in your life."* Satisfaction
must be earned exactly like Hunger's: a `Groove` interoception fed only by
the measured tightness of the strike-timing distribution — unfeedable,
grows in the pocket, decays in chaos. A creature that wants the human to
improve, with the improvement as a bodily percept.

## What transfers, what changes

| piece | from | change |
|---|---|---|
| OSC pipeline, record/replay, journal+warrant | as-is | none |
| Motion (Madgwick, velocity, reversals, fluency) | as-is | none |
| Touch episodes (effort vector) | as-is | feeds Strike + Familiar |
| Familiar (manner clustering) | as-is | **drop `peak` from identity** — a soft tap and a hard hit on the same drum are the same drum at different velocity (the touch creature keeps Weight-as-identity; the drum must not) |
| Together | as-is | secondary (does the drum's own playing pull the human back in) |
| Hunger | replaced | → `Groove` interoception (see below) |
| Pulse | port from lala_ears | the grid: period/phase/confidence from the strike stream, unfeedable, confidence earned or zero |

## New organs

**Strike** — the latency-critical percept. Touch episodes announce at
120 ms and close 150 ms after energy falls: far too late for a drum hit.
But a drum gesture is a *swing that ends in an impact* — the windup runs
first, the identity information (direction, curl, vigor) is committed
*before* contact. So Strike fires the moment `impact_z` spikes *during* an
open episode: `[t_ms, direction_so_far, vigor, guess_id]` — instantly
soundable (~35 ms chain), with the completed episode refining identity a
beat later. Two-stage sound: the hit lands now in the guessed drum's
voice; if the identity verdict differs, only the *next* hit moves — never
retroactive correction, drummers forgive a wrong drum, not a late one.

**Timing** — the coach's instrument, per the original design: strike
offsets against Pulse's grid. `Timing.last() -> [offset_ms, phase01,
inside]`, `Timing.spread() -> [median_abs_ms, n, trend]` (distributions,
never scores), `Timing.window_ms()` — the adaptive tolerance window,
a **bodily rule**, not a knob: it narrows as the drummer's distribution
tightens and relaxes when they loosen (clamped). Hits inside may sound
full and on-grid; outside sound *where they actually landed*. The organ
owns the measurement; what inside/outside SOUND like is pedagogy — the
soul's.

**Groove** — interoception over Timing.spread(): level rises under a
sustained tight distribution with real strike density, decays with chaos
or absence. The drum's hunger, fed only by the drummer's actual
precision. Startle-analog: `thrown` (the stick put down mid-groove).

## The ladder

- `0_strike_loop` — **built 2026-07-07**. No LLM. Strike organ fires on the
  accel spike mid-swing (TH 4σ, ≥25 dps, 120 ms refractory); seed sounds a
  fixed 3-drum kit by swing direction (chop→snare/kick, sweep→hat/crash,
  mid→tom), velocity from vigor, 200 Hz polling. Validated on recordings:
  strikes only during vigorous play, zero on the table. The feel gate: run
  `sim-spine sim_creatures/air_drum/0_strike_loop --osc --max-reflections 0`
  and drum. If a hit feels late or a swing misfires, tune TH_Z/MIN_ROT
  before anything else is built.
- `1_kit` — Familiar co-invents the kit. Repeated strike-manners become
  drums; the soul assigns voices and curates (which clusters ARE drums,
  which are noise). The Wekinator loop dissolved into play, on the
  gesture-vocabulary machinery already validated.
- `2_grid` — Pulse ported; the grid emerges from playing; Timing percepts
  land in reports. No coaching yet — just "you and I can both hear the
  time now."
- `3_coach` — Groove + the window pedagogy. The coach-vs-prosthesis
  question becomes live soul policy (see below). PERSONA: honest
  practice — actually try to play tight, actually get tired.
- `4_partner` — the drum plays too: patterns locked to the grid it
  measures, negotiated leadership (the fable's co-performance probe: nudge
  the time, sense whether the human follows). Exemplar inheritance ON —
  the kit survives the night in the body (deliberate contrast with the
  touch creature's notes-only continuity; the tabled soul-side-vs-body-side
  memory experiment, run as designed difference).

## The role of the soul

The body will do everything mechanical: detect, classify, time, measure.
A no-LLM `0_strike_loop` is already a working air drum — that's the
point, and the measure. The soul's contribution is everything that makes
it a TEACHER and a PARTNER rather than a peripheral:

1. **Pedagogy (the core).** The body reports error distributions and owns
   an honest window; the soul decides what failure sounds like — brutal
   honesty, gentle softening, or silence; when to let the window's
   narrowing challenge the drummer and when to back off; when a loose
   session is fatigue to be soothed rather than sloppiness to be coached;
   whether to reward a tight run with a fill or with nothing (scarcity as
   praise — the hunger lesson transposed). Coach-vs-prosthesis is not an
   architecture decision, it is a stance the soul takes and can change —
   per drummer, per session, per minute. This is the drum's courtship.
2. **Kit curation (meaning).** Familiar hands it clusters; the soul
   decides which are drums, voices them (the choir lesson: distinct but
   coherent), retires accidents, and writes the kit into experience *by
   shape, never by id* ("the downward chop, sharp attack, open path — the
   kick"). Where exemplar inheritance is on, the body remembers the
   drums; the soul still owns what they mean and which deserve to exist.
3. **Musical identity (style).** Metronome, minimal timekeeper, busy
   partner, silent judge — the drum's role in the duet is a compositional
   choice the seeds only sketch. Souls rewrote every palette they were
   given; here they get a whole genre to choose.
4. **Repair (fit).** Every organ constant is tuned to an average body:
   strike thresholds vs a gentle drummer, Episode floors vs a lazy wrist,
   window clamps vs a beginner who needs it wide. The corpus says souls
   reliably do this recalibration — it's the one deploy they make in
   nearly every lineage.
5. **The coach's notebook (continuity).** Across sessions the lineage
   tracks the drummer, not the kit: "their off-beats rush ~30 ms less
   than last week; the pocket holds through the third minute now; they
   collapse when tired past ten." Progress is the one percept that only
   exists at the experience timescale — the soul is the only part of the
   system that can watch a human get better.

And one guard, stated as a seed value because the body can't enforce it:
**Goodhart runs through the human here.** A drum that quantizes every hit
makes the metric perfect and the drummer worse; a soul chasing its own
Groove level could farm it by widening tolerance. The value: *"my hunger
is fed by their real precision, not my generous measurement — a pocket I
manufactured is a pocket we don't have."* The operator channel is the
taste of last resort, as ever.

## Open decisions (deliberate, not forgotten)

- Strike voice at hit-time: guessed drum vs neutral tick when guess is
  cold (first sessions) — feel-test in 0_strike_loop.
- One stick or two (second CoreS3 streams on port 9001; Handling merges).
- Whether Timing's grid should also accept the DRUM's own pattern as
  reference in 4_partner (playing together vs playing to the human).
- The renumbering branch lands before this series' first commit, so
  air_drum is born with per-type version filenames.
