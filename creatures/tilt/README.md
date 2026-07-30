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

The explicit channel is also now the **button**, not the tap. Worn on a back,
walking clears `TAP_G`: a single walk to the coffee machine produced four
"taps" in one second and seventeen across a session, none deliberate. The
runtime detects the click edge (driver callback where available, falling back
to polling in `heartbeat()`) and latches it behind a `Button` module —
`Button.pressed()` is True once per press and consumed on read;
`Button.last_s()` is seconds since the last press, `None` if there has been
none, and NOT consumed. It is a module rather than a loose `button()`
function so every sense in scope is reached the same way; the ledger counts
`presses`, not `taps`, for the same reason — the soul reads that word.

A **flag, not a counter** (revised 2026-07-30): counting invited the reading
that two presses mean something other than one, which nothing has shown. Two
presses inside a single poll collapse to one `True`, which at the seed's 50 Hz
needs them closer together than a hand manages; a rewrite that wants to tell a
double from a single can time consecutive presses with `last_s()`. Dropping
the count also dropped the arbitrary `_BTN_MAX = 8` queue cap it needed.

The callback now tries **`WAS_PRESSED` before `WAS_CLICKED`**, so the doc's
"the moment it lands" is literally true — `WAS_CLICKED` waits for the button
to come back up. The BOOT line reports which edge is live as
`btn=cb:WAS_PRESSED | cb:WAS_CLICKED | poll:wasPressed | poll:wasClicked |
none`. **None of this has run on hardware yet** — the tuner's `button` recipe
is what confirms it, and that token is the first thing to read. Detection lives in `main.py`
deliberately: a callback registered by an instinct would outlive it, since
`swap_instinct` unregisters nothing and every rewrite would leak another
handler over a dead scope. Sampling is bounded by `M5.update()` at 20 Hz
either way — the callback fixes double-reads and slow pollers, not the 50 ms
window.

**`Tap` is gone from this arm entirely** (2026-07-30), organ and tuner recipe
both, rather than left in scope unused: a sense the embodiment does not
document is a sense the soul can only stumble into. It is not deprecated in
the lineage — walking on a *back* clears `TAP_G`, which says nothing about a
wrist or a shoulder — and the working implementation (`_TapState`, burst
grouping, the three `TAP_*` constants) is intact in
`condition_2/lib/organs.py` for whoever wants it.

### The organ is fed by the instinct (2026-07-30)

condition_1/training/condition_2 feed Posture by **interposing**: `attach()`
replaces `Imu` with a wrapper whose `getAccel()` secretly feeds `Tap` and whose
`getGyro()` secretly feeds `Posture`, using the accel stashed by the previous
call. It works, and it cost ~20 lines of embodiment describing an invisible
contract, an ordering rule (accel FIRST) that nothing enforced, and four silent
failure modes.

condition_3 makes it explicit. `Imu` is handed over untouched; the instinct
calls:

    Posture.feed(Imu.getAccel(), Imu.getGyro())     # Posture's only clock

Argument order makes the pairing structural — you cannot express the
gyro-then-accel bug. And a rewrite that stops feeding is a **missing line**
rather than a missing side effect, which matters here because the soul re-emits
its whole instinct at every reflection, so it reads its own loop back.

**The cost, recorded because it is real.** `still_s()` is now forgeable: a soul
can feed synthetic stillness or synthetic motion. For *this* character
("restless when they're frozen") stillness is the satisfaction percept, which
`ORGANS.md`'s unfeedability rule says must derive from a stream the instinct
cannot write — and `Pulse`'s entry records a predecessor that was feedable and
got gamed twice.

Interposing did not actually protect it either: `still_s()` returns
`last_t - still_since`, both organ-internal, so an instinct that simply stops
reading **freezes** the number. Reading only while the person moves pins it low
and buys contentment all day, with no fake data anywhere — just by choosing
when to look. Controlling the clock was always enough.

**The open alternative**, if that forgeability turns out to matter: give the
body a small loop of its own (~5 Hz is plenty for a *duration*) that owns
`rot_ema`/`still_since` and nothing else, on the pattern of
`sim_creatures/lala_revisited/organ/organs.py` — where `attach()` spawns one
`asyncio` pump that outlives every hot-swap and the soul gets a view with no
`update()`. That makes the percept genuinely unforgeable and removes the
feeding contract entirely, at the price of two failure modes worth pricing
first: a pump that dies takes the sense with it silently (fix: `try/except` +
journal through `main.py`'s `CRASH:organs:` path), and a starved pump serves
stale numbers that look fresh (fix: expose `age_s()`). A Madgwick would also
become affordable there — a signed world-frame vector rather than a gravity
low-pass — though on this board `getMag()` is `(0,0,0)`, so heading would drift
unmeasured.

### `Calc` narrowed to three tools (2026-07-30)

`calc.py` ships to every board but was written for the dancers: across all
device creatures, **0 of 226 soul-written instincts ever used it** (in the sim
creatures, 1406 of 2408 did). Rather than document eight classes nobody
reaches for, condition_3's `attach()` hands the instinct only `Running`,
`Onset` and `OneEuro`, and the embodiment describes those properly — with
`Running`/`Onset` framed as the way out of a fixed threshold, since every
constant in the organ is one guess made for nobody. `Madgwick`/`Pose` (no
compass on this board; would also mean a second orientation filter beside
`_PostureState.grav`), `Flow`, `Periodicity` and `AlphaBeta` are removed —
the same move `lala_revisited` makes when it withholds the Madgwick *class*
from its soul. A tool in scope is an invitation to use it.

### Bouts get a third dimension, and the roll-up loses its bucket (2026-07-30)

The transition line carried duration and peak rate. Two dimensions separate
the confound weakly: a shove of the chair is 5s/peak 30, a walk to the coffee
machine is 61s/peak 73 — the same kind of event at two sizes. The line now
also carries **turned**: `Posture.rot()` summed over the bout, in degrees, the
energy of the whole thing rather than its loudest instant. Measured on
synthetic bouts, that is 138° against 4474° — a 32x gap where duration and
peak gave 10x. It is a number, so it names nothing.

A fourth axis comes free: the lean the bout **started from** against the lean
it **ended on**. A stretch returns to the same lean; a repositioning lands
somewhere new. `lean +2,+0 -> +1,+0` versus `lean +0,+0 -> +19,+0`. That axis
answers "did this movement go anywhere", which none of the other three can.

Implementation note worth keeping: the "before" lean must be latched on the
RAW still→moving edge, not at either edge of the `MIN_STATE_S` debounce. Read
at the moving report and gravity (`GRAV_TAU_S = 1.0`) has already tracked
0.4 s into the movement it is supposed to precede; read at the stillness
report and it *is* the after-pose. Both were wrong in the first two attempts.

**`BREAK_S` is gone**, and with it the `breaks`/`h_breaks` counters. `BREAK_S =
8.0` declared what a "real departure" was before one had ever been measured —
a word in disguise, and the only thing it fed was that count. The roll-up now
carries a highlight reel instead: the three biggest bouts of the span by turn,
`biggest moves 61s/2400°, 9s/210°, 8s/180°`. Extremes preserve the shape of
the distribution without bucketing it, and buckets would be a grammar by the
back door. `ANSWER_MIN_S` keeps its own floor — answering a chirp and leaving
the chair were always two questions, and one threshold never served both.

The reels live in the ledger (`big` for the wearing, `h_big` for the span,
reset at roll-up). `flush()` stores a shallow `dict(led)`, so they are
rebuilt with `[list(x) for x in ...]` on restore or the stored ledger and the
working one would share the same list objects.

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
