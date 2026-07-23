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
   words are descriptive and hedged (`slumped-ish`, `upright-ish`) —
   flavors of where gravity sat, not verdicts. What any of it MEANS —
   when stillness is a problem, when it's a person concentrating and
   best left alone — is the soul's judgment, revisable at reflection.
2. **Everything the creature DOES ships as a reafference triplet** —
   intent, action, outcome — so its own behavior is auditable and its
   social efficacy is measurable. The triplet is load-bearing here in
   social form: the outcome is not "did my sensor confirm my motion" but
   "did the person answer."

### Movement verbs (the body's history)

    STATIC(22min, slumped-ish)     a stillness stretch, reported at
                                   milestones (10/20/40min...) and at its
                                   end; flavor from the lean at the time
    MICRO_SHIFT                    a small adjustment inside a sit — weight
                                   shift, fidget; brief, posture unchanged
    SHIFT(upright-ish)             a posture change that STUCK (new lean
                                   flavor held after the motion)
    FULL_STRETCH                   a big excursion that returned — arms,
                                   arch, roll; seconds long, large angles
    MOVED_OFF(3min)                left the sedentary state for n minutes
                                   (walked, stood, fetched coffee); gait
                                   detection may later refine to WALKED
    POSTURE_VARIETY(low, this hour)  hourly summary: how much the posture
                                   distribution moved — low / ok / lively.
                                   A statistic, not a scold.

Flavors (from Posture.lean(), coarse on purpose): `upright-ish` (within
~8 deg), `slumped-ish` (forward past the slouch band), `reclined-ish`
(backward), `sideways-ish`. Numbers stay out of the flavor words; the
raw angles ride along only in the hourly summary.

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

## The percept ladder (later conditions)

The baseline is FORM-BLIND by design: it sings on frozenness alone
(still > 20min), and the captured-upright angle is unused (the organ
keeps set_upright()/angle() for a form-aware condition_2). The menagerie sketch goes further — a `Comfort` interoception
where the best posture is the NEXT posture: comfort decays under
sustained collapse AND under frozen rigidity, restored by variation,
sway, walks (the Goodhart guard: sitting rigidly at attention fails by
design). That, plus the soul's day-scale work (when to be audible at
all, the evening note), is what conditions 2+ are for.
