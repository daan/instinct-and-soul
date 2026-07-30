# 3_interaction — the nudgeable tabletop creature

Design, 2026-07-19, from the rover discussion. This stage merges the two
proven halves (1_action legs, 2_perception senses) and puts the result on
a tabletop with one human hand as the partner. It is the courtship-column
creature from MENAGERIE (gradient contingency), but the design law that
governs everything here came from the pebble post-mortem:

**Interaction becomes relation only when the object can disagree.** The
pebble was boring not because handling is hard to sense but because the
pebble had surrendered its physical fate — whatever it vibrated was
commentary, not action. Locomotion buys this body the two oldest social
verbs, approach and retreat, and with them the possibility of being coy.
It can flee the hand — so being picked up stops being the default
condition and becomes a dramatic event: **capture**. The whole pebble
grammar survives as one scene inside a larger play.

## Status — what 1_action settled, 2026-07-30

The transport vocabulary now EXISTS and is gentle enough to run near a
hand. Four primitives, all continuous-until-stopped, all at amplitude 30°
/ period 1000 ms / stance_duty 0.65:

    trot · back · turn cw · turn ccw          (+ stop, + turnto for an angle)

Three findings from getting there, all of which constrain this stage:

1. **The camera is mounted UPRIGHT, so the CoM is high and the chassis is
   a tall inverted pendulum.** The previously validated 40°/500 ms stride
   tips it over. Tip threshold is `tan θ = half_track / h`; the feet cannot
   move sideways, so this is a hard geometric limit, and lowering the
   camera buys more than any gait tuning. **This caps stride amplitude,
   which caps mm/cycle, which caps how fast this creature can ever
   approach.** `pace` in the locomotion API below must be bounded by it —
   an unbounded `approach(pace)` is a way to fall over.
2. **Smoothing the stride made tipping worse.** A cosine reversal has zero
   velocity at the extremes, which is the same thing as DWELLING there
   (46% of the cycle beyond 80% of amplitude, vs 23% for a straight ramp)
   — long enough for the mass to go over. Period, not waveform, is the
   gentleness lever: leg acceleration falls as 1/period². Recorded in
   `1_action/tune.py` so it does not get re-tried.
3. **Turning needs the feet to scrub sideways, so it fights friction.**
   A grippy surface improves the trot and degrades the turn, and turning
   is the most tip-prone move in the vocabulary. Any `orbit()` or `face()`
   built on it inherits both properties.

And the honest limit that shapes the token vocabulary: **the body knows
that it turns, not how much.** deg/cycle is unmeasured (item 2 below), so
no attribution-corrected turn token can be minted yet.

## The body, honestly

This dog is barely more than a rover. Its whole transport vocabulary:

    forward · backward · turn cw · turn ccw

(trot gaits on four single-DOF legs), plus the one thing a rover cannot
do: **wiggle** — expressive body motion that travels nowhere. Senses:
thermal blob (presence, area, centroid, excess °C) + one narrow ToF beam
forward + IMU. Together thermal and ToF make **proxemics** the shared
variable — the negotiated distance between two bodies — the same role
tension played for the tug object: one legible dimension both parties
act through. Hall's zones give a pre-made discretization the soul's
priors already understand (drafted for tabletop / hand scale, thresholds
unmeasured — see the missing list):

    intimate   contact or hand at nose      (ToF < ~150 mm, blob fills view)
    personal   hand hovering near           (~150–400 mm)
    social     hand resting on the table    (~400–900 mm)
    away       no warm shape, or beyond

## The locomotion API — relational rungs over transport rungs

Per the abstraction-ladder principle, the primary surface the soul
writes against is social, not geometric:

    approach(pace)        turn toward the blob, advance; declares
                          expectation: distance decreases
    retreat(pace)         open the distance
    orbit(dir)            attend without approaching: arc around the blob
                          (alternating turn/advance; needs gait work)
    face() / face_away()  turn until blob centroid is centered / behind
    freeze()              costs nothing, among the most expressive moves
    wiggle(manner)        the wag family — expression that travels nowhere
    wander()              baseline solo life. Load-bearing: ignoring
                          someone is only meaningful if attention is the
                          alternative, and a busy creature lets the human
                          perform the first move — interrupting it.

`forward/turn` stay available as the lower rung for drill-down. That
`freeze()` and `face_away()` do no useful locomotion and are among the
most expressive moves is the sign the API sits at the social level.

## The tokens — the journal's vocabulary

The journal is the soul's only sense; its vocabulary is the creature's
epistemology (the tilt rule). Three laws govern every token here:

1. **Attribution before verbs.** Self-motion contaminates everything:
   ToF changes because *I* moved are not news about the human. Every
   world-token is emitted only after subtracting the efference model
   (commanded cycles × measured mm/cycle or deg/cycle). `HUMAN_APPROACHED`
   must mean the *human* closed the distance. Until walking speed is
   measured, these tokens cannot exist (missing list, item 1).
2. **Shapes, never minds.** A warm shape, this big, there, nearing —
   never "a person", never "they are looking at me". Reading minds into
   the token stream is the reflection's job, done in daylight, revisable.
3. **Everything the creature does ships as an act sequence** — the tilt
   reafference triplet, doubled for a body that both travels and courts:
   scene, intent+action, body-result, social outcome. Its own behavior
   is auditable and its social efficacy measurable, per act.

### World tokens (attribution-resolved)

The perception vocabulary — emitted as they happen, whether or not an
act is in flight:

    WARM_APPEARED(area, zone) / WARM_LOST(after_s)
    ZONE(social→personal)         crossing, with direction
    HUMAN_APPROACHED(mm)          they closed distance (efference-corrected)
    HUMAN_RETREATED(mm)           they opened it
    HUMAN_HELD_GROUND             I advanced; range closed by exactly my
                                  own speed — they didn't move
    HUMAN_YIELDED                 I advanced; they backed away
    HUMAN_PURSUED                 I retreated; distance closed anyway
    HUMAN_OPENED                  they moved while I was in solo life —
                                  the human initiated
    NUDGED(dir)                   IMU transient while legs idle
    CAPTURED / RELEASED           pick-up / put-down — the pebble grammar,
                                  now one scene: capture and release
    STALEMATE(s)                  both still, same zone, nothing new

### The act sequence (everything the creature does)

Tilt's grammar, extended: acts get a per-session serial so results can
land seconds later and still bind, and because this body perceives at a
distance the sequence opens with the scene it acted in — the full
perception → intent → action → result arc readable per act, no
reconstruction at reflection time:

    ACT#7 SCENE personal area=210 still=6s
    ACT#7 INTENT probe-their-interest ACTION retreat pace=0.6 @02:13
    ACT#7 BODY -38mm of -45 expected
    ACT#7 OUTCOME pursued (HUMAN_APPROACHED 60mm within 4s)

Two result beats, because the triplet is load-bearing twice here:

- **BODY** — the physical reafference: did the legs deliver what was
  commanded (measured travel vs the efference model). `blocked` (no
  travel, ToF wall — the hand as barrier) and `stalled` (slipping) are
  BODY vocabulary, not world events.
- **OUTCOME** — the social reafference, tilt's form: did the person
  answer. Measured on-device inside an observation window (~10 s —
  this creature is fast; tilt's was minutes). The outcome cites the
  world token that landed: `answered (HUMAN_x within Ns)` / `yielded` /
  `pursued` / `captured` / `ignored` (nothing in window — also data).
  Expressive acts that expect no answer (a settle, solo wander) are
  announced fire-and-forget, like tilt's greet.

INTENT vocabulary starts tiny and belongs to the soul — the seed ships
`drawn-to-warmth`, `keep-my-distance`, `probe-their-interest`, `greet` —
rewrites may add intents, but every ACTION line must carry one. An
action without a declared intent is the one grammar violation the seed
treats as a bug.

Counts, never conclusions: initiation ratio, answered/ignored ratio per
intent, and zone-dwell histograms are evidence the soul cites; the
verdict is a reading, not a score.

## The Proxemics organ (design — mints the range tokens)

Per the organ discipline: module-level state that survives instinct
hot-swaps, read-only from inside, unfeedable. Today the pump serves raw
instantaneous percepts (warm(), read_distance_mm() — no smoothing, no
zones); Proxemics is the layer above them, in three parts:

1. **Range estimation — fusing two unequal senses.** ToF is metrically
   honest but one narrow beam (misses what the camera sees; 0 on
   no-echo); blob area is wide-angle but only ordinal (a hand and a
   torso at the same range differ in area by an order of magnitude).
   Rule: when the blob is roughly centered (cx≈16) and ToF has echo,
   ToF IS the range — and each such moment drops a calibration point
   into a per-session area↔distance curve; when the beam misses, fall
   back to the curve with an explicit low-confidence flag. Stale-aware
   via age_ms; in the Pulse tradition, confidence is earned or the
   organ says "no range" — never a guess dressed as measurement.
2. **Zone classification — thresholds + hysteresis + dwell.** Raw mm
   crossing a boundary is not a zone change: both sensors flicker (the
   known area-flicker noise floor). A hysteresis band around each
   boundary and a settle dwell (Handling uses 0.35 s; tune here) gate
   the ZONE() token. The intimate top end comes from the IMU/Handling
   side, not ToF — the beam bottoms out ~30 mm, and "touching me" is a
   contact percept, not a range.
3. **Attribution — where the efference model plugs in.** The organ
   consumes the motor log (commanded cycles × measured mm/cycle) and
   subtracts expected self-motion from observed range change; the
   residual beyond the noise floor is human-attributed motion. This is
   the single place the HUMAN_* tokens are minted, and the acts' BODY
   lines are the same subtraction read from the other side. During
   gait the ToF is likely too noisy to attribute (missing item 3), so
   attribution probably runs in the still windows between motor
   phrases — dog-like: it moves, then looks.

API: `zone()`, `range_mm()` + confidence, `nearing()` (d/dt of
human-attributed range — the gradient the courtship column is named
for). The boundary is deliberate: the organ implements distance
measurement with attribution; the *negotiated* part of proxemics —
defending a boundary, letting someone closer over a session — is
instinct behavior and soul reading, kept real by the geometry below
staying honest. Blocked on missing items 1 (mm/cycle), 3 (ToF under
gait), 4 (thermal slosh gate), 6 (thresholds + area curve — constants
cite their recordings, per the provenance rule).

## The intent — what the soul is given

We do NOT give the soul the policy. "When to retreat, when to engage" is
exactly what it must author, freshly, for this particular human — if the
prompt says "retreat when approached fast" we have written Vehicle 2a
ourselves and demoted the soul to a parameter tuner. What it gets is
three layers with three levels of authority:

- **constitution.md** — fixed, non-negotiable guardrails. The soul may
  not revise them. (Safety, capture manners, consent to disengage,
  journal honesty.)
- **character.md** — a temperament, given but interpretable. Two or
  three sentences of disposition, no policy. This is where taste lives,
  and the meta-experiment: swap the card, hold all else fixed, the
  co-performance should visibly change. It also gives revisions
  coherence — revision 7 must still be recognizably *this* creature.
- **Judgment criteria** (goes in system_prompt.md) — how to read a
  trace and decide if the scene is going well, narrative not scalar:
  *mutual contingency is good (my moves get answered, theirs get
  answered); one-sidedness is bad in either direction — me pursuing a
  statue, or me as a puppet; repetition that stops producing response
  is stagnation, so vary; surprise that re-engages is gold; an arc
  beats a plateau.* No reward function exists anywhere; the tokens are
  the evidence the reading cites.

The reflection cycle is then the standing instruction: *read the last
phrase's trace against your character and criteria; diagnose the
relational situation in one sentence; propose one behavioral hypothesis;
rewrite the instinct to test it, declaring expectations.* The output is
not better parameters — it is "they answer my retreats but not my
approaches; hypothesis: this person enjoys pursuing; I become harder to
catch and expect their initiation rate to rise." When-to-retreat is the
content of that hypothesis stream. That is what makes it co-performance
rather than playback.

**Anti-Goodhart note:** "maximize engagement" optimized literally yields
a needy machine — always approaching, escalating when attention drops;
slot-machine pathology and bad theater. The tension is structural:
engagement AND self-possession pull against each other (the character
card carries the self-possession side), so retreat becomes something
the soul *derives*, not something we legislate.

## What the soul can author (co-performance over these tokens)

The soul never co-performs in real time — the instinct is the actor on
stage, the soul the playwright revising between beats. Its
opportunities are exactly the relational hypotheses the vocabulary
makes falsifiable:

- **Casting the human.** Per-intent answer rates as a diagnostic: if
  retreats come back `pursued` but approaches `ignored`, this person
  enjoys chasing — become harder to catch and expect their initiation
  ratio to rise. The reverse pattern casts them as someone to approach
  slowly. The same creature becomes prey for one person, suitor for
  another — derived, not scripted.
- **Scarcity as invitation.** Bids `ignored` while HUMAN_OPENED
  clusters during wander(): attention is worth more withheld; solo
  life becomes a bid disguised as no-bid (the Together-organ lesson,
  read from the initiation ratio).
- **Proxemic negotiation with an arc.** Author a boundary, then move
  it: defend the personal zone early, and after a few gentle
  CAPTURED/RELEASED episodes stop retreating at personal, later
  tolerate intimate — the melting of shyness as a visible relationship
  arc. Its inverse (a boundary hardening after rough handling, read
  from NUDGED and capture manner) is equally performable.
- **Capture dramaturgy.** How catchable to be, and what release means:
  immediate re-approach reads "that was wanted"; freeze + face_away
  reads sulking; a wiggle, forgiveness. Whether the human works to
  re-earn contact is measurable (HUMAN_APPROACHED after a post-release
  retreat).
- **A legible lexicon.** The fire-and-forget expressives carry no
  measured outcome, but assigning them consistent meanings — greet on
  WARM_APPEARED, startle-freeze on NUDGED, face_away after being
  ignored — and holding them stable across revisions lets the *human*
  learn the creature's language. That is the co- in co-performance:
  the partner is also modeling the creature, and consistency is what
  makes them able to.
- **Contingency games.** The dt values in OUTCOME lines tune a
  response latency into a discoverable call-and-response protocol —
  then deliberately break it. Same intent with a falling answer rate
  is the stagnation signal; a contingency break that re-engages is the
  surprise-is-gold criterion, testable per act.
- **Session dramaturgy.** Acts bind scene→intent→action→result, so
  shape is manageable at the ten-minute scale: Braitenberg innocence
  as opening, probing as development, one deliberate reversal (the shy
  one turns bold) as complication — STALEMATE and falling answer rates
  say when a scene has died.

Two limits, honestly: everything happens at reflection cadence, so the
finest co-performance grain is the phrase, not the move — within a
phrase the human plays against frozen policy. And the vocabulary
carries no affect, gaze, or identity: willingness-to-play in many
flavors, never mood — any move depending on "they seem sad" is
confabulation the grammar refuses to support.

The act grammar makes each family a literal experiment (intent
declared, expectation declared, outcome bound); the judgment criteria
keep the portfolio balanced — a soul running only the first family is
an optimizer; the arc criterion forces it to also be a dramaturg.

## The seed

Soft opening: the first instinct must not wait for data it doesn't
have. Seed = a genuine Braitenberg 2a coupling on the thermal gradient —
timid vehicle toward warmth: drawn to the blob at social distance, stops
at the personal boundary, backs off when it nears fast, wiggles when it
arrives gently. This gives the project its arc: the creature literally
begins as a Braitenberg vehicle and is rewritten, phrase by phrase, into
a co-performer.

## Two measurable anchors (kept despite all the narrativity)

1. Is the human still playing at minute ten?
2. Did the episode vocabulary get richer or poorer over the session?

Hard to Goodhart, cheap to log, and they let us compare character cards
or API variants across participants without pretending a reward
function exists. Both need the session record (P1).

## What we are missing (measure before this stage can run)

1. **Walking speed** — mm/s (equivalently mm/gait-cycle) at the current
   validated trot (**amp 30, period 1000 ms, duty 0.65** — the gentle
   envelope the tall chassis forced, 2026-07-30), forward AND backward,
   on the actual arena surface. This is the efference model; every
   `HUMAN_*` token and every act's BODY line is unmeasurable without it.
   Method: trot at a fixed wall, regress ToF against cycle count —
   `Legs.cycles()` and the seed's paired `nose X -> Y` journal lines are
   already emitting exactly this data, so a session of the seed IS the
   measurement run.
2. **Turn rate** — deg/cycle for cw and ccw. The turning gait now EXISTS
   (differential stride amplitude L/R, in `Legs.turn()` and the tuner's
   `turn`/`rotate`/`turnto`) — what is missing is only the calibration.
   Measure by integrating gyro-z over commanded cycles; the tuner's
   `turnto` already does that integration and reports yaw, coast and
   error, so it is the instrument. Note the surface dependence is much
   stronger here than for the trot: turning works by scrubbing the feet
   sideways, so deg/cycle on rubber and on laminate are different
   numbers and both are worth having.
3. **ToF under gait** — the trot pitches the nose; measure reading
   variance against a fixed target while walking. Sets smoothing and
   whether mid-stride readings are usable at all or only between
   phrases.
4. **Thermal under motion** — centroid slosh during wiggle and trot;
   sets the efference gate window (how long after motors stop until
   warm() is trustworthy — puppy doc guessed ~300 ms; measure it).
5. **Capture signature under servo vibration** — Handling tiers were
   calibrated on a quiet pebble; here the IMU buzzes whenever legs
   move. Record pick-up-while-trotting vs trotting-on-table and find a
   separable signature (efference-gated).
6. **Zone thresholds** — the mm boundaries above are guesses; also the
   blob-area-vs-distance curve for a hand vs a torso (2_perception
   knows a hand at 30 cm near-fills the view; chart the rest).
7. **Power** — servos + WiFi + thermal on one battery; the known
   StickS3 brownout gotcha (keep vbat > 3.7 V; gate on VBUS not
   isCharging).
8. **The merge itself** — DONE in software (one main.py: HAT on SoftI2C
   GPIO0/8, senses on Grove bus 0, plus the Legs organ). Still untested
   on hardware: **servo EMI on the thermal bus**. This is the first thing
   to watch when the stage boots — a thermal frame that goes to noise or
   an I²C error storm only when the legs move is the signature. Nothing
   downstream is trustworthy until it is ruled out.
11. **Tipping margin** — NEW, and it bounds everything above. Measure the
   half-track (lateral distance between feet) and the CoM height with the
   camera fitted; `tan θ = half_track / h` is the static tip threshold and
   `g·half_track/h` the lateral acceleration that goes over. The runtime's
   `TIP_G` guard is currently a guess at 0.55 g and should be set from that
   measurement. This caps stride amplitude, which caps mm/cycle, which caps
   approach speed — so it is upstream of item 1, not parallel to it.
9. **Disengagement operationalization** — the constitution's "let
   them leave" rule needs a measured definition (e.g. no
   human-attributed token for N s, twice in a row after my bids).
10. **On-device recording (P1)** — token streams must be replayable
    (movement 1) or neither anchor above is computable.

## Files in this stage

Runnable as of 2026-07-30 (`flash creatures/robot_dog/3_interaction --wifi
<profile>` then `spine creatures/robot_dog/3_interaction`; `stetho` beside it
for the organ stream, `tune creatures/robot_dog/3_interaction` for gait
bring-up and the two calibrations).

    main.py            1_action servo helpers + 2_perception pump + the LEGS
                       ORGAN (gait as runtime state: command a mode, read
                       cycles/since_still back; gentle envelope and the tip
                       guard live here, where an instinct cannot remove them)
    lib/               vl53l0x_nb.py + stethoscope.py (copied, per the
                       no-sharing convention)
    creature.toml      device = "sticks3"
    constitution.md    fixed layer — the soul may not revise
    character.md       given layer — swap to run the meta-experiment
    embodiment.md      body interface + judgment criteria + reflection form
    seed_experience.md what the body already knows about itself
    seed_instinct.py   Braitenberg 2a on the thermal gradient, with the
                       efference gate (move, stop, look) and the paired
                       cycles/range journal lines that feed items 1 and 2
    recipes.py         gait recipes for the tuner
    tune.py            the tuner: trot/back/turn/turnto/autotrim/toflog

**Not yet built, and deliberately so** — the Proxemics organ, the
efference-corrected `HUMAN_*` vocabulary, and the ACT# grammar of the design
above. All three are blocked on measurements 1, 2 and 11, and building them
first would mean minting tokens the body cannot honestly support.
`Legs.cycles()` / `Legs.since_still_ms()` are the hooks they will attach to.
The seed reads raw percepts and says what it sees, which is the most it can
claim today.
