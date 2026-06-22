# recorder_test

A **plumbing probe**, not an artistic creature. It exists to verify the
record → playback pipeline end-to-end with **no LLM cost**, by exercising all
three M5 capture channels in `seed_instinct.py`:

| Channel | API used | Recorded to | Playback |
|---|---|---|---|
| IMU | `Imu.getAccel` / `getGyro` | `input/imu_reads.jsonl` | replay through the sim (deterministic) |
| Sound | `Speaker.tone` | `output/audio_events.jsonl` | `bake-audio` → `.wav` |
| Display | `M5.Display.fillScreen/fillRect/fillCircle` | `output/display_log.jsonl` | `playback` viewer (canvas + synced audio) |

The behaviour is a pure function of the IMU, so replaying the recorded
`imu_reads.jsonl` reproduces byte-identical audio + display logs.

## Run (no LLM)

```bash
# record against a mocap clip (short duration keeps logs small)
creature-sim sim_creatures/recorder_test --from-mocap data/mocap/out/Vasso_Happy_01_stageii.json --wrist left --duration 10

# play the display back in the browser (auto-bakes audio.wav and syncs it)
playback sim_out/recorder_test

# verify determinism: replay the recorded IMU, logs should be identical
creature-sim sim_creatures/recorder_test --imu sim_out/recorder_test/input/imu_reads.jsonl -o /tmp/recorder_replay
```

`playback` (no arg) opens the most recent run under `sim_out/`. It renders the
display log on a canvas with a scrubbable timeline and plays the baked audio in
sync (baking `audio.wav` on the fly if it's missing).
