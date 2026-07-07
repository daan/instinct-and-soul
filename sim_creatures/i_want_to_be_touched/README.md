# i_want_to_be_touched — a creature that craves being handled

A hand-sized creature (the CoreS3 box) that wants to be touched — and wants
*good* touch. Its only sense is its IMU (what handling feels like from the
inside); its only voice is music, played live through the room's speakers.
No vibration motor: the voice is in the air, not in the hand, so the IMU never
feels the creature's own output (the efference-contamination problem of the
original pebble is gone by construction).

The goal is co-performance: the creature must *earn* handling time from a human
who is free to put it down. The strategy — invitation calls, rewarding good
touch, going quiet, developing a signature — is the soul's to invent.

## Series ladder (like lala_ears: one addition per experiment)

- `0_live_loop` — infrastructure validation. Seed instinct only (run with
  `--max-reflections 0`): hold the device, hear it respond. Proves the OSC
  bridge, live audio, logging, and the replay round-trip.
- `1_handling` — first LLM experiment: can the soul find a voice for touch
  qualities? Two new organs (organs.py, calibrated against recorded
  0_live_loop sessions of the real device):
  - `Handling` — contact tiers by smoothed |gyro| (table 0.26 dps / held ~5 /
    handled ~25 / played ~285 — the gyro separates them by orders of
    magnitude; a live hand is never table-still), plus since_s(), alone_s()
    (only real contact resets it), face() and turned().
  - `Touch` — handling segmented into bounded touch-episodes with quality
    features [start, dur, peak_dps, rise01, wiggles, impact_z]: a tap, a
    stroke, a shake, and a drop are different shapes here.
  - plus the `Ear` from the lala_ears line (efference copy — the other half
    of every report).
- `2_hunger` — interoception: does hungry-vs-sated behavior emerge, and does
  the person answer begging or beauty? Adds the `Hunger` organ: level 0..1
  grows with neglect (~150 s to full), melts with contact at innate rates
  (quiet holding ~45 s satiates deepest; wild play ~140 s — thrilling, thin
  food); startle 0..1 spikes on hard knocks (impact ≥8σ), decays ~8 s —
  arousal, not nourishment. Unfeedable in both directions. Seed reports carry
  the hunger arc per window; invitations come sooner and bolder the hungrier.
  Also carries the `Motion` organ (ported from lala_ears: Madgwick fusion,
  world-frame accel, travel, reversals) and Touch episodes gained `vert01` —
  the touch's direction in the gravity frame (~1 up-down, ~0 sideways), the
  first ingredient of gesture identity. The seed savors being fed out loud
  (satisfaction must be audible) and answers touches by direction.
- `3_together` — the contingency organ, promoted after a 2_hunger soul
  announced "tracking how quickly" a new call style drew the person back and
  never built the mechanics. `Together` watches the Ear and the contact
  stream: any voicing while alone (≥3 s) is an invitation-attempt (bursts
  split at 3 s gaps), answered if contact follows within 20 s; matched
  silent stretches score the baseline the same way. attempts()/answered()/
  baseline() — counts, never conclusions; "if answered doesn't beat
  baseline, your calls are decoration." Needs a *responsive* partner: on a
  replayed recording answered≈baseline by construction (the null test); a
  real human (PERSONA.md) is required for signal. The hidden-"yes"
  experiment: adopt a private convention (e.g. a stroke when you like what
  it did), never tell it, and see whether the soul finds it in the numbers.
- `4_familiar` — recurrence as a percept, and recognition as reward. The
  `Familiar` organ clusters completed touches online ([log dur↓weighted,
  log peak, rise, wiggle-rate, vert]; nearest exemplar within r=0.85, core-
  gated EMA so rim hits can't blob clusters): last()/recognized() (fires at
  3+ sightings)/gestures(). Heritage: the pose→motion→pose "kata"
  recognizers of pre-IMU sonification toys — always sonify the motion (the
  trace), reward the recognized form on top. The seed's law: identity picks
  the motif, the instance plays it — same gesture, same figure; vigor sets
  force, pace sets tempo, a bent gesture bends the reply. An instrument,
  not a jukebox. Validated: a wave/circle session separates into a vertical
  family (6×) and horizontal families with honest singletons.
- `5_expressive` — gestures as an expressive instrument, staged on a
  Laban-like effort vector. Touch episodes extend to
  [dur, peak, rise, wiggles, impact, vert, size, curl, fluency]: size =
  travel path length (big vs small at last), curl = open vs closed travel
  (stroke vs circle/oscillation), fluency = jerk normalized by amplitude
  (calibrated: flowing ~0.9, rough ~0.35). Familiar clusters on identity
  dims INCLUDING curl+size but deliberately EXCLUDING fluency — the same
  gesture done more smoothly stays the same gesture, so recognition holds
  while quality improves (the coaching invariant). Seed mappings: fluency →
  beauty (brightness/glide/space follow smoothness, continuously — coaching
  without rules), circles → figures that turn (cyclic contour + orbiting
  pan), casts → one long sweep, lower the bigger the journey. Plus live
  Motion.fluency().
- `6_light` (planned) — RGB/screen return channel (OSC back to the device).

## Running

Session scripts: PERSONA.md (how to behave — honest reactions with
thresholds), PROTOCOL.md (what to try — a ~12 min walkthrough exercising
every organ once, including the hidden-"yes" convention).

Live (device streaming; CoreS3Recorder osc firmware, `/imu` on UDP :9000):

    sudo ifconfig awdl0 down    # macOS AirDrop radio scans cause 50-170ms
                                # stream stalls; comes back up on its own,
                                # so do this before every session
    sim-spine sim_creatures/i_want_to_be_touched/0_live_loop --osc

Measured 2026-07-06 (no-display firmware with send gating, awdl0 down, plain
home WiFi): a clean ~100 Hz from the first packet — median gap 10 ms, ~0.2
stalls/s worst-case 63 ms, ~1.4% packet loss. Older firmware that streams
during WiFi association shows ~20 s of startup delays — let it settle first.

Loopback without the device (second terminal replays any clip as OSC):

    osc-send data/mocap/lala/imu_hips.jsonl --host 127.0.0.1

Replay a live session offline (every live session logs its full IMU stream as
a replayable clip):

    sim-spine sim_creatures/i_want_to_be_touched/0_live_loop \
        --imu <session>/input/imu_stream.jsonl --max-reflections 0

Live mode notes: the session is open-ended (Ctrl+C stops it gracefully —
in-flight reflection drains, logs flush), the clock never freezes (you can't
freeze a human), and reflections are wall-clock throttled (`--reflect-every`,
default 45 s) so a chatty instinct batches messages instead of burning an LLM
call each. MIDI plays live through fluidsynth AND logs to
`output/midi_events.jsonl` as usual, so `trace` / `bake-midi` work unchanged.
