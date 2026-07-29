# tilt — a small animal near your neck

An M5StickS3 worn on the upper back near the neck. Character (set
2026-07-16): *"You are a small animal that lives near this person's neck.
You get restless when they're frozen and content when they move. You are
easily hushed and hold no grudges."* It measures posture lean against a
CAPTURED upright and how long the body holds still; prolonged frozenness
makes it sing, softly, until the person moves — or hushes it with a tap.
Awareness by indirection, never a nag: the perch concept from
MENAGERIE.md, first hardware incarnation.

The body is a PLAIN StickS3 — internal speaker and IMU, nothing attached.
The voice comes from the built-in speaker, quiet (the animal lives at
the edge of attention). The radio sleeps between 15-minute journal syncs
(batch mode); a summons — urgent journal entry, crash, deliberate
double-tap — wakes it early.

## The grammar — journal tokens (implemented in the seed 2026-07-16)

The journal is the soul's only sense, so its vocabulary IS the creature's
epistemology. Two rules govern every token:

1. **Verbs about movement, never judgments about form.** The device never
   says "you're sitting wrong"; it says "you've been a statue." Posture
   words are descriptive, hedged, and purely DIRECTIONAL (`forward-ish`,
   `level-ish`) — flavors of where gravity sat, with no pole named as the
   good one. (The vocabulary was `slumped-ish`/`upright-ish` until
   2026-07-28; "slumped" was the one pejorative in an otherwise neutral
   set, and it fired most often, so the journal's commonest form-word
   carried exactly the judgment this rule forbids.) What any of it MEANS —
   when stillness is a problem, when it's a person concentrating and
   best left alone — is the soul's judgment, revisable at reflection.
2. **Everything the creature DOES ships as a reafference triplet** —
   intent, action, outcome — so its own behavior is auditable and its
   social efficacy is measurable. The triplet is load-bearing here in
   social form: the outcome is not "did my sensor confirm my motion" but
   "did the person answer."

### Movement verbs (the body's history)

    STATIC(22min, forward-ish)     a stillness stretch, reported at
                                   milestones (10/20/40min...) and at its
                                   end; flavor from the lean at the time
    MICRO_SHIFT                    a small adjustment inside a sit — weight
                                   shift, fidget; brief, posture unchanged
    SHIFT(level-ish)               a posture change that STUCK (new lean
                                   flavor held after the motion)
    FULL_STRETCH                   a big excursion that returned — arms,
                                   arch, roll; seconds long, large angles
    MOVED_OFF(3min)                left the sedentary state for n minutes
                                   (walked, stood, fetched coffee); gait
                                   detection may later refine to WALKED
    POSTURE_VARIETY(low, this hour)  hourly summary: how much the posture
                                   distribution moved — low / ok / lively.
                                   A statistic, not a scold.

Flavors (from Posture.lean(), coarse on purpose): `level-ish` (within
~8 deg of the MOUNTING zero), `forward-ish`, `backward-ish`,
`sideways-ish`. Numbers stay out of the flavor words; the raw angles
ride along only in the hourly summary.

The zero is the MOUNTING, not the wearer: `_flavor()` reads raw gravity
in the device frame and ignores the captured upright, so a body whose
natural neck-mount sits a few degrees forward reads `forward-ish`
permanently, and `setref` does not move it. A flavor that never changes
carries no information to the soul — see "the flavor zero" below.

### Feedback and body tokens

    TAPPED(x1) / TAPPED(x2)        the explicit channel. ANY tap near a
                                   call = hush (count semantics kept soft
                                   — see clock/tap note below); bursts
                                   elsewhere are journaled, none summon
    WOKE(boot|timer|urgent|lowbat) each radio wake, with cause
    BATTERY(3400mV, falling)       at wakes and milestones

### The reafference triplet (everything the creature does)

Actions get a per-waking serial so the outcome can land minutes later and
still bind:

    ACT#7 INTENT invite-movement ACTION cricket-up lvl2 @14:40
    ACT#7 OUTCOME moved (SHIFT within 40s)

Outcome vocabulary, measured inside an observation window (~5 min):

    hushed (tap x1 within 5s)      they heard me and asked for quiet —
                                   honored immediately, grace ~30 min,
                                   no grudge held (escalation resets)
    moved / stretched / stood      the invitation worked, graded by what
                                   followed and how soon
    ignored (nothing in 4min)      also data — maybe the level is too
                                   subtle, maybe they're deep in something
Outcomes are observed ON-DEVICE, so radio naps never truncate a window
(only a reboot does). Outcome watching applies to invite-movement acts;
greet and acknowledge are announced but fire-and-forget.

INTENT vocabulary starts tiny — `invite-movement`, `greet` (the hello
trill), `warn-battery` — and belongs to the soul: rewrites may add
intents, but every ACTION line must carry one. An action without a
declared intent is the one grammar violation the seed treats as a bug.

The hush rule, structurally: a TAPPED(x1) within ~5 s of any ACTION is
consumed as that action's outcome (`hushed`) — not forwarded as a
separate feedback event — and silences the animal for the grace period.
"Easily hushed, no grudges": the next stillness stretch starts the
escalation from level zero.

### The clock — spine-supplied time (implemented 2026-07-16)

Grammar tokens want wall time (`@14:40`, `this hour`, quiet evenings),
but the device clock is boot-relative ticks. Resolution: the spine sends
`TIME:<unix>:<gmtoff_s>` (laptop clock + timezone) to batch-announcing
devices right after their BOOT; the device sets its RTC, which carries
across radio naps within a boot; every connect re-syncs. The creature
reads the hour via time.localtime(); subsequent BOOT lines carry a
`clock=HH:MM` token (at the END — the spine matches startswith("BOOT:")).
Verified live: instinct-read localtime matched the laptop within sync
granularity. NTP and spine-side-stamping were considered and dropped —
a day-scale animal should FEEL dusk; quiet hours are its manners, not an
operator-side filter.

Tap-count semantics (2026-07-16): deliberately SOFT for now — any tap
near a call will hush; all bursts journal as TAPPED(xN); none summon.
Promoting x2 to a summons waits for worn evidence (tuner `tap` test)
that count discrimination through a strap is reliable.

## Structure

Same convention as kata_master: every condition is a complete,
self-contained creature — runtime + organs + mind + tuner in one
directory, no sharing between conditions unless made explicit.

    creatures/tilt/condition_1/    the baseline: cricket-on-slouch
      main.py, lib/                runtime + the Posture organ
      organs.py -> lib/organs.py   (internal symlink for the sim bench)
      seed_instinct.py + prompts   the mind
      tune.py, recipes.py          audition + calibration tools
    creatures/tilt/condition_2/    the overhaul (2026-07-28): NO GRAMMAR.
      seed_instinct.py             the organ reports numbers, the soul
                                   interprets — see below.
    creatures/tilt/condition_3/    the legible arm (2026-07-29): the journal
                                   names BODY / LINK / INSTINCT separately and
                                   never lets one imply another — see below.
                                   Ships condition_2's worn values and its
                                   promoted experience.
    creatures/tilt/training/       condition_1 with the instinct TEMPO
                                   (FROZEN_AFTER_S, CALL_EVERY_S, OUTCOME_S,
                                   HUSH_WINDOW_S, HUSH_GRACE_S) hoisted into
                                   organs.py and joined to the tuner's `set`
                                   TUNABLES — the whole clock retunable live,
                                   mid-session. Ships at bench tempo (statue
                                   after 2 min). Tune here; wear condition_1
                                   (write winning values into its seed).

## Bring-up order

    flash creatures/tilt/condition_1 --wifi <profile>
    tune  creatures/tilt/condition_1

1. `cricket 1..5 [vol]` — audition the five chirp designs, each looping
   every 4 s. The test is inverted from an instrument: pick the one you
   can IGNORE. (1 tick, 2 cri-cri, 3 trill, 4 sweep, 5 low.)
2. Worn: `setref` while sitting the way you mean it, then `posture` —
   sit well, slouch, lean, walk; calibrate SLOUCH_DEG and the stillness
   threshold against what the numbers actually do on a real back.
3. `deploy baseline` — live-run the seed from the tuner, no spine.

Then sessions: `spine creatures/tilt/condition_1 [--max-reflections N]`.

## condition_2 — moving the interpretation boundary down

condition_1 pre-digests: the organ names motion (`SHIFT`, `FULL_STRETCH`)
and the instinct names its own acts (`ACT#7 INTENT invite-movement`), so
by the time a sitting stretch reaches the soul it has already been called
"a statue". condition_2 stops doing that. The journal carries a
timestamp, numbers, and the few things that happened:

    17:29 chirped, soft — still 4.0m | lean +4,+1
    17:31 tap (nothing of mine was open)
    17:56 moved 82s, peak rot 126 | now still again | lean -2,-2
    18:00 hour: still 58m of 60m, longest 29.8m, 3 breaks, 6 chirps, 2 taps

What changes:

- **The zero is the wearer, not the strap.** The seed calls
  `set_upright()` after the first 20 s of stillness and journals
  `lean_ref()` — degrees from the upright THEY gave it. (condition_1's
  flavors are measured from the mounting, which on a neck mount sits
  ~15-20 deg forward, so its wearer read `slumped-ish` permanently no
  matter how they sat. `Posture.lean()` still reports the raw strap
  angle; `lean_ref()` is the one to journal.)
- **`Posture.rot()` is exposed** — the smoothed gyro magnitude in dps
  that `still_s()` is derived from. The soul sees the measurement, not
  only the verdict.
- **One tap, no counting.** `Tap.tapped()` fires once per tap. The
  burst/x2 machinery still exists and is unused.
- **Two timescales.** A hint after ~4 min of stillness, and an hourly /
  daily ledger so reflection can reason about a day rather than the last
  ten minutes.
- **Hints back off.** Each unanswered chirp doubles the wait (capped at
  30 min), reset by any real break or a hush. Without this the flat
  3-minute spacing produced 15 chirps in the first simulated hour — a
  nag, not an animal. If they aren't answering, asking oftener is the
  wrong reply.
- **The verb/flavor layer survives, unused.** `Posture.verb()` and
  `flavor()` still work; the embodiment tells the soul it is free to
  ignore them. Removing the mandate, not the capability.

`character.md` is unchanged — the desire is the same animal; only what it
notices and how it reports changed.

## condition_3 — three lifecycles, named

A whole afternoon of bring-up (2026-07-29) kept stalling on one question:
*"there was a BOOT at 14:51 — did the instinct restart?"* It is hard to answer
because three independent lifecycles were reported under one word. The runtime
sends a line beginning `BOOT:` on EVERY websocket connect, and its `cause=` is
`machine.reset_cause()` read once at import — so it describes a reset that may
be hours old and never changes. `uptime=` is the only field that distinguishes
them, and the creature's own wake line could not tell a real rewrite from a
re-push of identical code.

condition_3 names them:

    BODY awake — new ledger, battery 3892mV
    INSTINCT v3 — replaced v2. I kept living: worn 91m, still 68m, ...
    my code was re-pushed unchanged (still v2) — nothing about me is different

The creature distinguishes them from two facts it already has: **Mem is wiped
by a power cycle and by nothing else**, and **`IV`** (new in this condition's
`main.py`) is the version of the instinct it is running, compared against the
version stored in its ledger. Only a BODY wake greets with the trill.

The device announce also gained `wake=poweron` / `wake=reconnect down=14s`,
and the spine now logs the outcome rather than the mechanism — `reconnected —
board up 46m, instinct v2, creature NOT restarted` vs `sent instinct v3 —
creature RESTARTED (board had v2)`. That spine change is shared, not
condition-scoped, so condition_1 and training get it too.

Also in this arm: worn values restored (`HINT_AFTER_S` 240, `SAMPLE_EVERY_S`
300) after condition_2's bench session, and `ANSWER_MIN_S = 1.0` — a floor on
what counts as answering a chirp. The soul's own fix in condition_2 correctly
made *any* motion an answer (their reply is a 3-6 s shift, well under
`BREAK_S`), but with no floor a 0.4 s twitch scored as a reply; rejected
twitches are journalled so the floor can be tuned from data.

## The percept ladder (later conditions)

The baseline is FORM-BLIND by design: it sings on frozenness alone
(still > 20min), and the captured-upright angle is unused (the organ
keeps set_upright()/angle() for a form-aware condition_2). The menagerie sketch goes further — a `Comfort` interoception
where the best posture is the NEXT posture: comfort decays under
sustained collapse AND under frozen rigidity, restored by variation,
sway, walks (the Goodhart guard: sitting rigidly at attention fails by
design). That, plus the soul's day-scale work (when to be audible at
all, the evening note), is what conditions 2+ are for.
