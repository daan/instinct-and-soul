# Organs — the perceptual bodies of the creature lineages

An organ is a sense compiled into the body: module-level state that survives
instinct hot-swaps, fed by interposing on the instinct's own Imu/Synth calls,
**read-only from inside** — the instinct can attend to it but never feed,
clear, or restart it. Admission is gated by the promote-to-organ test:
*a capability enters the body only when souls repeatedly almost build it and
fail on mechanics; what they never reach for stays out.* Descriptions follow
the measurement discipline: exact units, exact API, the minimum semantics
that make the construct legible — and never a musical consequence.

## Summary

| organ | senses | line | promoted because |
|---|---|---|---|
| **Ear** | the creature's own voice | dancer → touch | across ~230 versions, no soul ever recorded its own output |
| **Motion** | orientation, world-frame travel, reversals, fluency | dancer → touch | souls hallucinated fusion APIs and never got one working |
| **Pulse** | repetition in the body's movement (period/phase/confidence) | dancer → (air_drum) | predecessor was feedable and souls faked "perfect" regularity twice |
| **Episode** | motion as bounded gestures (surge segmentation) | dancer | souls kept groping toward gesture-as-envelope and failing |
| **Handling** | contact tiers, aloneness, which face is up | touch | founding organ of the series (calibrated on real recordings) |
| **Touch** | contact segmented into episodes with an effort-vector | touch | ditto; extended twice from session evidence |
| **Hunger** | appetite for touch; startle | touch | desire needs an earned, unfeedable satisfaction percept |
| **Together** | do my calls summon them, vs a silence baseline | touch | a soul announced "tracking how quickly" and never built it |
| **Familiar** | recurrence — "this shape of touch again" (+ in-flight guess) | touch → (air_drum) | recognition demanded mechanics (clustering) souls can't iterate blind |
| **Strike** *(planned)* | the hit, at hit-time | air_drum | Touch episodes close ~150 ms late — fatal for a drum |
| **Timing** *(planned)* | strike offsets vs the grid; adaptive tolerance window | air_drum | the coach's instrument; window is a bodily rule, not a knob |
| **Groove** *(planned)* | interoception over timing tightness | air_drum | the drum's hunger — fed only by the drummer's real precision |
| **Repertoire** *(candidate)* | the body's own phrases — named, performed identically | any (first: robot_dog / tilt) | not yet — admission waits on documented phrase-loss/drift (see entry) |

## Dancer line (lala_ears)

### Ear
The body records every note it voices, beneath the code.
`recent(n, ch)` → last events `[t_ms, kind, ch, note, …]` (~400 kept);
`cc_total()`. Control changes counted, not recorded; **programs neither —
the Ear is timbre-blind** (a soul can never hear that its voices converged;
distinctness must be architected, not perceived).

### Motion
Madgwick fusion fed by the instinct's own Imu reads; boots from first accel,
never resets. `up()` (tilt, absolute), `accel_world()` (gravity removed,
z = up), `velocity()` (leaky integral; trust direction and reversals over
magnitude), `reversal()` (one-shot turnaround), and in the touch line
`fluency()` (jerk normalized by amplitude; flowing ~0.9, rough ~0.35).
Honesty: yaw drifts (no mag in the fusion — yet); tilt degrades only during
sustained vigorous motion and recovers in ~1–3 s of calm.

### Pulse
Autocorrelation over smoothed rotation energy; nothing to feed.
`period()` (folded to a 0.4–0.9 s tactus), `bpm()`, `confidence()` (0..1,
**earned or zero** — a still body reads 0, meaning "no pulse", not "not yet
measured"), `phase()` (None without confidence). Goes stale if the Imu stops
being read. Its design law spread to the whole project: *trust and act in
proportion to earned confidence.*

### Episode
Hysteresis segmentation of motion energy into bounded gestures: a surge
above the body's own recent level (τ≈8 s baseline). `started()` (one-shot,
~0.25 s in), `current()`, `ended()` → `[start, dur, peak, rise01]` (rise01:
struck vs swelled), `last()`. Known misfit: absolute floors are tuned to a
dancing body; quiet bodies need gentler floors — organs are per-creature
files precisely so they can.

## Touch line (i_want_to_be_touched)

### Handling
Contact tiers from smoothed |gyro| — the gyroscope is the touch channel
(measured: table 0.26±0.07 dps, quiet hold ~5, gentle ~25, play ~285; the
accel magnitude carries a per-device bias and is never used for stillness).
`state()` → table/held/handled/played (0.35 s dwell), `since_s()`,
`alone_s()` (only real contact resets it), `face()`/`turned()` (settled
gravity face; one-shot on flip).

### Touch
Contact segmented into touch-episodes (start > max(3 dps, 1.6× recent);
end after 0.15 s below). Each completed touch carries the effort vector:
`[start, dur, peak_dps, rise01, wiggles, impact_z, vert01, size, curl01,
fluency01]` — direction in the gravity frame, extent of travel, open-vs-
closed path (a stroke vs a circle/oscillation), and how smoothly it was
performed. A gesture is currently a *bout of vigor between stillnesses*,
not a unit of form (mongrel bouts are a known limit; manner-change
splitting is the queued refinement).

### Hunger
Appetite as exponential approach per contact tier: alone → 1 over ~150 s;
held → 0 over ~45 s (quiet holding feeds deepest); handled ~60 s; played
~140 s (thrilling, thin food). Boots at 0.5 — wakes wanting. `level()`,
`startle()` (spikes on impact ≥8σ, decays ~8 s; arousal, not nourishment).
Unfeedable in both directions: can't fake satiation, can't bump neediness.

### Together
The one social question the body can measure: when I sing into an empty
room, do they come? Any voicing while alone (≥3 s) is an attempt (bursts
split at 3 s); answered if contact follows within 20 s. `attempts(n)`,
`answered()`, and `baseline()` — matched *silent* stretches scored by the
same rule. If answered doesn't beat baseline, the calls are decoration.
Counts, never conclusions.

### Familiar
Recurrence as a percept: completed touches cluster online in **manner
space only** — `[log peak, wiggle-rate, vert, curl]`; duration, size,
attack and fluency are deliberately excluded (chopping noise; and the same
gesture done more smoothly must stay the same gesture — identity holds
while quality improves, or coaching is impossible). Nearest exemplar within
r=0.95; exemplars learn only from core hits (rim assignments can't drag —
the anti-blob rule); clusters that converge reunify (older id survives).
`last()` → `[id, n, dist01]` (dist01: canonical vs bent), `recognized()`
(one-shot at 3+ sightings), `gestures()`, and `guess()` — **in-flight
recognition** of the unfinished touch, confidence = elapsed-evidence ×
decision-margin; a guess, not a fact. Ids are *this waking's names*: the
sense starts empty each session — anything worth remembering is recorded
in experience by shape, never by number.

## Air-drum line (planned)

### Strike
The hit at hit-time: fires on the impact spike *during* an open episode
(the swing's identity is committed before contact) → `[t, direction, vigor,
guess_id]`, soundable in ~35 ms. The completed episode refines identity for
the *next* hit — never retroactive correction.

### Timing
Strike offsets against Pulse's grid. `last()` → `[offset_ms, phase01,
inside]`, `spread()` → distributions (never scores), `window_ms()` — the
adaptive tolerance window, a bodily rule (narrows as the drummer tightens,
relaxes when they loosen; clamped). The organ owns measurement; what
inside/outside *sound* like is pedagogy — the soul's.

### Groove
Interoception over `Timing.spread()`: rises under sustained tight
distributions with real strike density, decays in chaos or absence. The
drum's hunger, fed only by the drummer's actual precision — a pocket the
creature manufactured is a pocket it doesn't have.

## Candidates (admission pending)

### Repertoire — the generative twin of Familiar
The one asymmetry in this document: every organ above is machinery around
the SENSES, none around generation (wiggle, sound). That was principled —
organs exist to solve a truth problem, and perception is where
confabulation and Goodharting live; generation has no truth problem (the
servos do what the code says) and expression is meaning, which belongs to
the soul. But generation has its own failure modes, and one is already on
record in this file: the Ear's timbre-blindness note — *a soul can never
hear that its voices converged; distinctness must be architected, not
perceived* — is a generative failure documented before any organ existed
to answer it. The other two are predicted, not yet documented: **phrase
loss** (expressive phrases live only inside instinct code and can die
silently in rewrites — tilt's UP/DOWN/TRILL tuples sit precariously in
`run()`) and **phrase drift** (the human learns the creature's lexicon
only if a greet stays recognizably the greet; nothing enforces that, and
no organ would notice it eroding).

The organ, if admitted: a body-side, hot-swap-surviving store of NAMED,
parameterized phrases. The soul defines `greet`, `sulk-wiggle`,
`chirp-up`; the instinct performs them by name with a manner/intensity
parameter; the body executes identically every time. What falls out of
the one primitive: phrases cannot die in a rewrite (the skill-library
gap vs Voyager, closed body-side); an act grammar's ACTION field becomes
a repertoire name, so per-phrase outcome statistics accumulate cleanly;
Efference gets structured input ("performing greet, 800 ms") instead of
raw servo writes, making the self-motion gate nearly free; and the Ear
is revealed as the Repertoire's already-built sensing half — perception
and action finally symmetric around the self. The honesty discipline
transfers as the identity-vs-manner invariant, mirrored: a named phrase
performed softer or bigger is the SAME phrase, so the partner's learned
lexicon holds while quality varies — the coaching invariant, outbound.

Boundary, stated in advance: the organ owns execution fidelity, never
composition or meaning. Which phrases exist, when to perform them, and
what they mean stays the soul's — a Repertoire that grows its own
vocabulary would be the body doing the mind's job.

**Admission condition** (the promote test, applied): build nothing until
instinct lineages show the failure. When the robot_dog or tilt soul
sessions run, diff the lineage for expressive phrases: if they survive
rewrites intact, the instinct is a sufficient home and this entry stays
a candidate; if they vanish or mutate unintentionally, that diff is the
admission ticket, and the organ gets built with the provenance in its
docstring like every organ above.

## Cross-cutting rules

- **Unfeedability** — every satisfaction-adjacent percept (Pulse confidence,
  Hunger, Together, Familiar counts, Groove) derives from streams the
  instinct cannot write. Confidence is earned or it is zero.
- **Identity vs manner** — recognition dims stay stable while quality dims
  (fluency, size, attack) vary: the coaching invariant.
- **One-shot events** are consumed on read (`reversal`, `started/ended`,
  `turned`, `recognized`) — one reader owns each.
- **Session-local names** — cluster ids and exemplars die with the session
  (body-side inheritance is a deliberate, per-creature choice; planned ON
  for the drum's kit, OFF for the touch creature's notes-only continuity).
- **Calibration provenance** lives in the organ file itself, citing the
  recordings that set each constant.
