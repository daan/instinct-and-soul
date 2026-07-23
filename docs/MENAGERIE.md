# The Menagerie — co-performance roles as a design space

A creature is admitted to the menagerie the only way this project allows:
a **desire** plus an **earned satisfaction percept** — influenceable but not
controllable, unfeedable by the creature's own code, with its Goodhart
failure named in advance. Everything else (organs, seeds, voices) follows.

## The axes

- **Leadership** — who sets the time: follow · lead · negotiate · oppose.
- **Target of change** — the human's motion · the human's state · the
  creature's state · a shared artifact.
- **Temporal coupling** — synchronous · turn-taking · historical
  (across sessions).
- **Evaluative stance** — supportive · neutral · critical.

Every role below is the same architecture — Together (directional
influence) + Familiar (recurrence) + Pulse (entrainment) + an interoception
tuned to the role's hunger — with the desire rotated and the contingency
arrow re-aimed.

## The periodic table

**The entrainment triangle** (one percept, three arrows):

| creature | arrow | status |
|---|---|---|
| dancer | creature follows human | done (lala_ears) |
| air_drum / coach | human follows the grid | 0_strike_loop built |
| **muse** | human follows the creature | proposed |

**The courtship column** (contact → distance → inversion):

| creature | contingency | status |
|---|---|---|
| pebble / touch creature | binary: touched or not | series live |
| **robot dog (thermal)** | gradient: warmth approaching/retreating | proposed |
| **audience** | inverted: the human courts the creature | proposed |

**The state-movers** (the partner's inside as the truth-teller):

| creature | sense | satisfaction | status |
|---|---|---|---|
| breathing coach | breath belt (a Pulse variant) | breath follows the pacer | planned |
| **tai-chi** | heart rate (`/hr` stream, `Heart` organ) | calm **during** flow — HR down / HRV open *while fluency high*; the conjunction is the Goodhart guard (calm-while-still is napping; flowing-while-stressed is performance) | proposed |

## Sketches

### Muse
Desire: *to be imitated.* Satisfaction: the human's motion entrains to
material the creature introduced — Together inverted (my Ear's rhythm ×
their Pulse). Leads to inspire, never to correct. Completes the entrainment
triangle; nearly free (both organs exist). Goodhart: seeding only trivially
imitable material — guarded by requiring novelty in what gets imitated.

### Robot dog (thermal camera)
The pebble's desire along a spatial gradient: wants proximity/attention,
acts through body language (wiggle, posture), measures approach — Together
gradient-valued instead of event-valued. **Marks an epoch: the first
exteroceptive creature.** Every prior creature lives by "everything I know
about you arrives as motion of my own body"; the dog perceives the partner
at a distance, and the confabulation guards must be rebuilt for it (organ
reports say "a warm shape, this big, nearing" — never "they are looking at
me"). The pebble's efference curse returns hard: its own wiggling shakes
its own IMU and swings its own camera — efference copy mandatory.

### Audience (the reversed pebble)
Desire: *to be entertained.* The human courts the creature. The organ layer
is honest about **variety** (rate of new Familiar clusters, feature entropy,
prediction error); **taste — which variety matters — is the soul's layer**:
the first creature whose soul-role is critic, not composer. Boredom must be
visible and genuine (interest decays exactly as the organ's surprise does —
PERSONA turned into a constitution). Measurable outcome nobody scripts:
does the human's gestural repertoire diversify across sessions (Familiar
statistics)? The coach narrows the human's distribution; the audience
widens it — an inverse pair. Goodhart: rewarding raw novelty trains random
flailing; the critic-soul exists to prevent exactly this.

### Tai-chi (heart rate)
Soother-teacher hybrid: teaches form with the fluency→beauty machinery
(proven in 5_expressive), but hungers for the **calm the form produces**,
verified by the student's own heart. `Heart` organ: bpm, trend vs session
baseline, confidence from beat regularity; new `/hr` OSC stream in the
`/mag` pattern. Distinct from push-hands sparring (opposition, flow-channel
percept: keep the human at challenge ≈ skill), which is a different
creature.

### Perch (the shoulder bird — posture, all day)
A back-worn IMU (clipped between the shoulder blades) and sparse chirping.
The timescale inversion: posture unfolds over hours, so the reflection loop
is FASTER than the phenomenon for the first time — the soul's cadence fits
natively. Desire by indirection, not coaching: *a bird lives on a tree
(your spine); it sings when the tree suits it, grumbles and shifts when
the tree droops.* Your posture is expressed as ITS comfort — the creature
never scolds, you infer (the empathy-object pattern; cf. Breakaway; also
what the rough-session soul invented on its own with whimper-to-teach).
`Comfort` interoception with the ergonomic truth as Goodhart guard: the
best posture is the NEXT posture — comfort decays under sustained collapse
AND under frozen rigidity, and is restored by variation, sway, walks. So
gaming it by sitting at attention fails by design. Organs: Posture (tilt
vs a self-calibrated upright — gravity-referenced, so the IMU's best
regime: no dynamics, no heading), Activity episodes (sit/stand/walk),
Comfort. Soul's day-scale work: WHEN to be audible at all (office!), which
indirection moves this person (Together: does my grumble precede a
straighten?), the evening note (the correspondent pattern: "we drooped
through the 3pm meeting; the walk was the best part of my day"), and a
song that evolves over days. First creature with ecological validity by
default — real life is the protocol; no PERSONA needed. v1 practical:
desk-hours via the existing OSC→PC pipeline; on-body speaker later.

### Others on the shelf
Trading partner (turn-taking integrity: phrases interlock, silence is
honored), accompanist (stability as the gift; satisfaction = their fluency
over my ground), witness (recognition across sessions as the star —
lineage memory), apprentice (the human teaches; Wekinator as a character),
soother/hype (arousal moved to a target, Together on state).

## Where this matters (application horizons, HCI)

Nearest neighbors: Voyager (skill library grown from an agent's failures —
our promote-to-organ test is that, with an admission bar) and
Code-as-Policies (LLM writes policy code against perception APIs — our
instinct against organ APIs). The difference that makes this HCI rather
than robotics: those systems optimize task success in worlds with ground
truth; here the only ground truth is a particular human staying, changing,
or leaving — relationship, not task.

The considerability test for any application: *would a fixed, well-tuned
mapping (a Wekinator patch) do the job?* If yes, the creature is
decoration. The creature earns its keep only where the right mapping is
(a) unknowable in advance, (b) different per person, (c) drifting over
time — and where (d) the adaptation must be **auditable** (every change
ships with a written intent and an inspectable diff — explainable
adaptation by construction).

Domains that pass the test: personalized assistive & rehabilitation
interfaces (ability-based design: the instrument fits itself to a tremor,
a spasticity, a residual limb — and keeps fitting as the body changes);
skill-practice instruments (music pedagogy, sport technique, physio
adherence — the coach's-notebook progress percept is the product);
somaesthetic technology (breath, balance, body awareness — the felt-quality
mappings this community already values); relational artifacts for
isolation and dementia care (the courtship column, with the desire-honesty
discipline as the answer to the fake-empathy critique); and the
meta-design layer itself as a design tool (Pd with a tenant: designers
stage organs, a resident completes the mapping with the user in the loop).
