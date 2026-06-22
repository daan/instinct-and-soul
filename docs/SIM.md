# sim.md — simulation & experiment harness

This document covers the **offline** side of the project: synthesizing sensor
input from motion capture, replaying a creature's instinct against it in CPython,
and recording the same kind of trace from the *real* device so the two can be
compared. `DESIGN.md` covers the live production loop (instinct ↔ spine ↔ soul);
this is its lab bench.

> Status: parts of this exist today (marked ✅), parts are decided-but-unbuilt
> (marked ☐). The point of this doc is to make the deferred decisions — file
> formats, the session schema, the archive boundary — explicitly, since the
> simulator originally landed as code in one commit with no design step.

## Why a simulator

The research data is the creature's evolving behavior. To study it we want to
run the **same instinct** under **varied parameters** against a **reproducible
input** — something a live human-in-the-loop session can't give us. The
simulator feeds a fixed IMU stream through the instinct in CPython, captures
every sound/display/message it produces, and does it deterministically, so two
runs differ only by the parameter we changed.

The companion question is fidelity: does the simulated creature behave like the
real one? That's the real-vs-simulated comparison (M2 below), and it's why the
real device must produce a trace in the *same format* the simulator does.

## The pipeline

```
  AMASS .npz  or  BVH                                 ┌─ viewers/skeleton/ (3D body + IMU charts)
  (mocap; BVH e.g. stitched                           │      ▲ skeleton_view.json
   loops from ../bvh-stitch)                          │      │
     │  bake-mocap                                    │      │
     ▼                                                │      │
  data/mocap/<clip>/  ───────────────────────┬────────┴──────┘
   source.bvh|.npz   (regen root)            │
   skeleton_view.json  (viewer)              │  imu_<wrist>.jsonl (g & deg/s)
   imu_left/right.jsonl  (sim) ──────────────┤
   clip.json  (manifest)                     ▼
                                   imu stream (jsonl) ─► creature-sim / sim-spine ─► session/
                                             ▲                                          │
                                             │                                   trace / bake-audio
   real device ── recorder ──► session/ ─────┘                                          │
   (same schema)                                                                        ▼
                                                                          compare: body + sound + display
```

`bake-mocap <clip.bvh|raw.npz>` writes a self-contained **clip directory** under
`data/mocap/<clip>/`: the input copied in as `source.*` (the regeneration root),
the full-rate per-wrist `imu_left/right.jsonl` the simulator reads, a
stride-decimated `skeleton_view.json` for the viewer, and a `clip.json` manifest.
The heavy full-rate skeleton is **not** written by default — re-bake from source
with `--full` if you need it (`bake-mocap data/mocap/<clip>/source.bvh --full`).

**Source clips.** The salsa BVH captures (`Stefanos_Salsa-01_x4`,
`Vasso_Salsa_Shines-01_x4`) come from the University of Cyprus **Dance Motion
Capture Database** (https://dancedb.eu) — download the raw motions there — and are
looped/stitched to ~4× their original length (the `_x4` suffix) with the
`bvh-stitch` tool. The raw `.bvh`/`.npz` are large and licensed by their archives,
so `data/mocap/` is gitignored; bake the clip bundles locally with `bake-mocap`.

Two halves, now in one repo:

| Half | Lives in | Role |
|---|---|---|
| **Data factory** | `src/instinct_and_soul/mocaplib/` + `viewers/skeleton/` | mocap → skeleton + synthetic IMU JSON; 3D viewer ✅ |
| **Harness** | `src/instinct_and_soul/creature_sim/`, `sim_spine.py` | run instinct in fake-M5 CPython, capture behavior ✅ |

The boundary between them is **one file format**: the IMU stream. Get that right
and the factory, the harness, and the real device never need to know about each
other's internals.

## Decision 1 — units and rate are the device's

Measured on a real CoreS3 BMI270 (`test/CORES3/calibrate_imu`, 2026-06-05):

- accelerometer in **g** (gravity ≈ +1 g along one axis at rest),
- gyroscope in **deg/s**,
- effective **ODR ≈ 96 Hz** (100 Hz default) — distinct samples cap there; the
  poll rate (~8 kHz) is irrelevant.

Everything speaks these units. `mocaplib.synthesize_imu` outputs g + deg/s,
low-passed at 12 Hz and clamped to the chip's ±8 g / ±2000 deg/s full scale, so
synthetic data sits in the same range a real sensor can actually report. Synthetic
clips should target **fps ≤ ~96**; mocap sources finer than that (e.g. 120 fps)
are fine — the sim interpolates.

## Decision 2 — jsonl is the interchange format

The simulator originally read IMU from an `.npz` but wrote its output logs as
jsonl. That split was incidental, not designed. We unify on **jsonl** for every
time-series the harness reads or writes:

- it appends line-by-line, so the **real recorder** can stream to it live (an
  `.npz` must be buffered and written whole);
- it's the format the sim already uses for output;
- it's greppable and diff-able, which matters for research traces;
- at 96 Hz a minute of IMU is ~0.5 MB — size is a non-issue.

The IMU stream uses the **same line schema** the sim already emits for sampled
reads:

```json
{"t": 12.5, "ax": 0.004, "ay": -0.005, "az": 1.001, "gx": 0.1, "gy": -0.2, "gz": 0.0}
```

`t` in ms; `ax/ay/az` in g; `gx/gy/gz` in deg/s. `.npz` may survive as an
internal fast-cache, but it is **not** the contract — the contract is jsonl.

The trade-off is small and one-sided. jsonl runs ~2–3× larger on disk (~0.5 MB
vs ~0.2 MB per minute) — nothing at these sizes. **Interpolation is unaffected**:
the format only changes how samples load into memory; once they're numpy arrays
the cursor-walk interpolation is identical. What `.npz` buys (slightly smaller,
faster load) doesn't matter here; what jsonl buys (live append for the recorder,
one format across the harness, grep/diff) is exactly what this project needs.

## Decision 3 — one session schema, identical for real and sim

A run — simulated or real — produces a **session directory**:

```
session/
  meta.json                  # what produced this run (see below)
  input/
    imu_reads.jsonl          # the IMU the instinct actually sampled  {t, ax..gz}
  output/
    audio_events.jsonl       # Speaker.tone/begin/end/setVolume/stop  {t, kind, …}
    midi_events.jsonl        # Synth MIDI commands (note/program/CC)  {t, kind, …}
    display_log.jsonl        # M5.Display.* calls                     {t, kind, …}
  comms/
    sent.jsonl               # messages to the soul                   {t, content}
```

The IMU record is **`imu_reads.jsonl` — the sampled reads** (what the instinct
read, when it read it), not a dense stream. This is deliberate: the sampled reads
are the **one artifact real and sim both produce**. The real device *only* has
sampled reads — it polls the IMU at its loop rate, there is no dense ground truth.
The sim samples its dense source at the same cadence and logs the same file. So
`imu_reads.jsonl` is the symmetric, directly-comparable record. (The sim already
writes it ✅.)

The dense mocap stream that *drove* a sim run is **referenced, not copied** —
`meta.json.source` names the clip directory. It's regenerable (deterministic bake
from the source clip), so embedding it would just duplicate data across every
session in a sweep. `meta.json`:

```json
{
  "kind": "sim",
  "creature": "sim_creatures/dancer",
  "source": "data/mocap/Stefanos_Salsa-01_x4",
  "wrist": "left",
  "fps": 120.0,
  "duration_ms": 106025,
  "params": {},
  "created": "2026-06-05T13:26:00Z"
}
```

`kind` is `"sim"` or `"real"` (a real session's `source` is `"real"` — there's no
clip); `params` holds the experiment knobs varied across a sweep. Aligning the
harness to write `meta.json` is a small task ☐; an opt-in `--embed-source` can
copy the driving stream in for standalone archival if ever needed.

Because both kinds share this schema, **a real recording can be replayed through
the simulator** — feed its `imu_reads.jsonl` back in as the input stream (the sim
interpolates between samples) and, if the instinct is deterministic, you get back
the same sounds the device made live. That replay *is* the fidelity test.

## Decision 4 — the mocap↔sim boundary is per-wrist IMU in the clip dir ✅

The harness wants one sensor's dense stream to interpolate. Rather than strip a
rich skeleton JSON down at sim time, `bake-mocap` **pre-writes** both wrists'
streams into the clip directory:

```
data/mocap/<clip>/imu_<wrist>.jsonl    {t, ax..az, gx..gz}   # g & deg/s, t = i/fps*1000
```

So `creature-sim <creature> --from-mocap data/mocap/<clip>/ [--wrist left]` just
reads `imu_<wrist>.jsonl` directly — no bridging step. `--from-mocap` also accepts
a `clip.json` or a raw `.bvh/.npz` (baked first).

Because `bake-mocap` always pre-writes both wrists' full-rate streams beside the
skeleton, there is no separate "skeleton JSON → IMU" step: the standalone
`bake-imu` bridge was removed. `sim_in/` is no longer used for mocap-derived
streams — it's free for external or real-replay inputs.

## The real recorder

To get a `"real"` session, the device must log IMU + sound + display the same way
the sim captures them. Mirror the sim's approach: in the creature's `main.py`,
**tee** every `Imu` read / `Speaker` call / `Display` call to a recorder that
streams compact records over the existing WebSocket; the laptop writes the
session directory. This is infrastructure (sampling cadence, wiring), so it lives
in `main.py`, not the instinct — the instinct stays identical to the one the sim
runs, which is what makes the comparison valid. ☐

## Visualization

Three views, all driven from a session (or the mocap JSON):

| View | Tool | Shows |
|---|---|---|
| the body | `viewers/skeleton/` (three.js) ✅ | mocap skeleton + IMU charts (the *input*) |
| the behavior | `viewers/tracer/` (`trace`) ✅ | instinct messages / soul intent timeline |
| the sound | `bake-audio` ✅ | `audio_events.jsonl` → WAV |

The M2 comparison view is these on one clock: the **skeleton dancing** beside the
creature's **baked audio + display timeline**, so a video of a real interaction
can be lined up against the simulated replay and the soundtracks checked against
each other. ☐

## Status & next steps

| | Component | State |
|---|---|---|
| ✅ | `bake-mocap`: mocap → skeleton+IMU JSON (g/deg/s, low-pass, clamp) | done |
| ✅ | `skeleton`: 3D viewer | done |
| ✅ | `creature-sim` / `sim-spine`: run instinct, capture output jsonl | done |
| ✅ | `bake-audio`, `trace` | done |
| ✅ | `creature-sim --from-mocap <clip>` reads the clip's pre-baked `imu_<wrist>.jsonl` | done |
| ✅ | sim reads the jsonl stream (`JsonlImuSource`); `--imu` takes `.npz` or `.jsonl` | done |
| ✅ | session layout: `creature-sim` writes `meta.json`; `imu_reads.jsonl` is the IMU record | done |
| ☐ | real recorder: `main.py` tee-wrappers → session dir | M2 |
| ☐ | comparison view: body + audio + display on one clock | M2 |
