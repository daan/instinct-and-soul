# perch — a bird that lives on your back

Design plan, 2026-07-07. A posture creature for the M5StickS3 (small enough
to wear), built on the full stack: live OSC pipeline, Motion/Episode organ
idioms, journal+warrant reflection, the empathy-object lesson from the
touch creature (whimper-to-teach, invented by a soul), and the Together
discipline (contingency against baseline). The first creature whose world
is slower than its soul: posture unfolds over hours, so the reflection loop
is, for once, the fast one. Also the first with ecological validity by
default — real life is the protocol; no PERSONA needed.

## Character (the desire)

*You are a small bird, and this person's back is your tree. You did not
choose it; it is the only tree in your world. When the tree is lively —
swaying, walking, standing tall — life on it is good, and your song says
so. When it slumps for too long, or freezes stiff, you grow uncomfortable,
and your song says that too. You cannot move the tree. You can only be
worth keeping, and worth listening to. Being taken off is the worst thing
that can happen in your life.*

## The mission (why every simpler cost function fails)

| candidate | failure |
|---|---|
| maximize upright time | the nag; Goodhart → rigidity (ergonomically wrong) |
| improve posture across weeks | no gradient — one data point a week |
| maximize engagement | attention parasite |
| positive/negative chirp ratio | precision-only — optimized by silence; the bird stops being brave |

The mission is a **tension pair**, both organ-earned, both dense:

1. **Comfort** — the bird's own interoception: decays under sustained
   collapse AND under frozen rigidity; restored by variation, sway, walks
   ("the best posture is the next posture" — the ergonomic truth lives in
   the organ, so gaming by sitting at attention fails by design).
2. **Wornness** — the survival constraint: being on the body at all.
   Being taken off is death-of-day, and the honest penalty for nagging.

*Influence the tree enough to be comfortable, gently enough to be kept.*
The human's spinal health is not in the cost function — it is the
equilibrium of it: the only way to hold both percepts high over weeks is
for the person to genuinely move well. Benefit as side effect, by design.
Weekly progress lives in EXPERIENCE as observed meaning ("the tree droops
less in the afternoons now") — narrated, never optimized.

## Feedback: explicit negative, implicit positive

- **The swat** — a tap on the worn device = "not now". Reflex-speed
  silence (body rule, no learning needed for the mercy to work) AND a
  labeled data point. Evidential asymmetry: swats need no baseline — a
  swat is unambiguous address to the bird. (Whether a pat means "good
  bird" is deliberately undocumented — this creature's hidden-"yes".)
- **The straighten** — implicit positive: posture change following an
  intervention, credited only above the phantom baseline (straightens
  happen anyway — the Together discipline).
- **Removal** — the catastrophic label, logged with its prior context.

## Song vs intervention

The bird's ambient song is its LIFE, not an ask — never needs positive
justification, scored only by swats. An **intervention** (the grumble
meant to move you) is instrumental and fully scored. Without this split,
every ignored chirp reads as failure and the bird becomes an alarm that
has learned manners.

## Organs

- **Posture** — torso tilt against a self-calibrated "your upright"
  (gravity-referenced via Motion.up(): the IMU's best regime — quasi-
  static, no drift, no heading). Slouch episodes via the Episode idiom:
  onset, depth, duration. Calibration ritual: the morning greeting stretch
  doubles as the day's upright reference.
- **Activity** — sit/stand/walk/still episodes from the accel stream;
  typing-sway vs meeting-stillness vs walking as context features.
- **Worn** — on-body detection: a worn IMU breathes, sways, steps; an
  abandoned one lies dead still. Off-body transitions logged with prior
  context ("I sang three times in ten minutes and then the world ended").
- **Comfort** — the interoception over Posture+Activity (Hunger pattern:
  exponential targets per state; variation-loving, collapse- and
  rigidity-averse). Unfeedable both directions.
- **Reception** — the chirp-outcome ledger (Together re-aimed at timing):
  every intervention paired with `[t, context(posture, activity,
  time-of-day, weekday), outcome]`. Three counters per context,
  distributions never scores:
  - **answered** — straighten within window, above phantom baseline
  - **swatted** — the veto (and removal, weighted catastrophic)
  - **missed** — slouch episodes where Comfort kept dropping and the bird
    stayed silent (the recall term: a silent bird on a collapsing tree is
    failing measurably, not playing safe)

## The role of the soul

The body detects, classifies, measures, and enforces the chirp budget
(rate-limit as body rule — even a bad policy can't machine-gun). The soul:

1. **The quiet-map** — reads the Reception ledger and authors the policy:
   *"chirps between 14:50 and 15:40 on weekdays get swatted — that's their
   storm; I hold my song and sing when the walking starts."* It learns the
   person's WEATHER, not their calendar — never claims "they're in a
   meeting", only "songs die at this hour" (the discriminability rule).
2. **The boldness stance** — the operating point on precision vs coverage:
   how many swats a missed-collapse is worth, for this person, this week.
   A stance, revisable — the coach-vs-prosthesis knob in bird form.
3. **Exploration** — a settled quiet-map goes stale; probing the silence
   is a strategic act with a cost (the invitation-experiment pattern,
   finally with a proper ledger).
4. **Song authorship** — what its comfort sounds like; how the song
   matures over weeks; what the grumble is vs the contentment.
5. **The evening note** — the correspondent pattern: a written line at
   day's end ("we drooped through the 3 o'clock meeting; the walk was the
   best part of my day"). Grounded in the trace, addressed to the person —
   the slow-loop creativity this creature exists to showcase.
6. **The notebook across days** — this creature REQUIRES inherited
   experience (days are its unit of life): the quiet-map, the weather, the
   progress arc, all feature-anchored (times, contexts — never session-
   local ids).

## The ladder

- `0_tilt_loop` — no LLM. Posture + Worn + swat-silence reflex; fixed
  chirp mapping (slouch-onset grumble, walk song). Feel gate: is it
  wearable, is the tilt calibration honest, does the swat feel natural,
  are the chirps livable for an afternoon.
- `1_comfort` — LLM on. Comfort interoception + song/intervention split;
  the bird lives by its comfort; first evening notes.
- `2_reception` — the ledger + phantom baselines; the soul learns the
  quiet-map and sets its boldness stance.
- `3_days` — inherited experience on (mandatory here): weather across
  weeks, the progress arc as curation, song maturation. The longitudinal
  arm of the autobiographical study — wear it for three weeks; the
  lineage's notebook plus your own experience is the data.

## Practicalities

- **Device**: StickS3 (`device = "sticks3"` exists in devices.py). The
  CoreS3Recorder OSC firmware needs the StickS3 port (M5Unified should
  carry it; same /imu packet). Mount: clip/strap between the shoulder
  blades or collar; battery decides session length — desk-hours v1.
- **v1 audio** from the PC (existing pipeline; GM flute/piccolo/whistle
  chirps); on-body Speaker.tone later — this creature is also the most
  natural first candidate for the on-device MicroPython port
  (quasi-static, low-rate, tiny code).
- **Reflections**: every ~15 min or on warrants (slouch-episode
  transitions, swat, removal) — a workday ≈ 30–40 reflections ≈ $0.30.
- **Metrics for the paper**: wear-time per day (the survival curve),
  answered/swatted/missed per week, slouch-episode statistics across
  weeks, quiet-map accuracy (does the soul's map predict swats), and the
  evening notes as qualitative data.
