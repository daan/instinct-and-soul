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
- `3_together` (planned) — the contingency organ: pairs the creature's own
  recent output (efference copy of MIDI) with subsequent handling on one
  timeline — did the invitation summon a touch? did purring prolong the hold?
  Baseline-corrected, reported with confidence. Needs a *responsive* partner:
  a replayed recording is non-contingent and must read ~0 (that's the organ's
  null test); a real human (see PERSONA.md) or a synthetic closed-loop
  fake-human is required for a positive signal.
- `4_light` (planned) — RGB/screen return channel (OSC back to the device).

## Running

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
