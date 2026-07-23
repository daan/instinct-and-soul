# ARCHITECTURE — the three data movements

Written 2026-07-08, after the step-back. When the project feels like it is
overcomplicating itself, check the feeling against this document.

A creature is a body (instinct + organs on some substrate), a soul (LLM,
reached through a gateway), and a person. Between them there are exactly
**three data movements**, and every piece of infrastructure belongs to one:

## 1 · The record
Everything the creature lives — input, output, organ events, journal,
reflections — captured on **one clock** for later playback and analysis.
This is the research instrument. Artifacts: the session directory
(store_format 2), `trace` (the playback instrument), bake-* tools.
Rule: the record is always authoritative; live views never are.

## 2 · The reflection loop
Journal up, code down. Slow, reliable, small. Artifacts: journal + trigger
semantics (rhythm / warrant / crash), the reflection store, experience
lineage.

## 3 · The live window (development only)
A view into what the body feels that the person cannot hear or feel — the
creature's EEG. Artifacts: the stethoscope (organ events + slow levels over
UDP-OSC, ~10–20 msg/s), its TUI. Never a data pipeline; never load-bearing;
lossy by contract because movement 1 holds the truth.

## The temporary condition (name it to contain it)

The body currently runs on the PC while its senses run on the device. That
split — not the project — is what created the OSC sensor streaming, the
asyncio/time patching, and the clock-sync concerns. They are scaffolding
for the split, not architecture. When the body runs where the sensors are
(the on-device era), movement 1 becomes local recording + download, the
clock problem collapses to one `ticks_ms` plus one wall-time anchor, and
streaming shrinks to movement 3.

The PC simulator then remains what it secretly always was: the
**accelerator** — virtual time, fast reflection cycles, cheap soul
experiments — not the destiny of the runtime.

## Core vs scaffolding

| core (keep investing) | scaffolding (feature-frozen) |
|---|---|
| session format (store_format 2) | OSC IMU streaming pipeline |
| organs (MicroPython-portable by construction) | sim clock-freeze machinery |
| instinct contract, journal/trigger semantics | live PC synth (until on-device sound) |
| tracer as playback instrument | full wire-protocol spec (drawer) |
| the stethoscope (movement 3, minimal) | web trajectory scope, hot-reload tuner |

Known debt, deliberately unpaid for now: per-creature `organs.py` files are
copies (the per-creature-body principle is right; the copying is not) — a
shared organ library with per-creature composition is the eventual fix.

## Priorities (2026-07)

1. **P2 — the stethoscope** (movement 3): organ events + slow levels,
   UDP-OSC + `organ_events.jsonl`, TUI dashboard. Days.
2. **P1 — on-device recording** (movement 1 completed): input, output, and
   organ events recorded on the device in the standard session schema;
   download drops it into `logs/`. Device `ticks_ms` is the session clock;
   one boot→wall offset line anchors it. Perch is the natural first
   tenant. The tracer gains the organ-event lane (schema proven sim-side
   by P2 first).
3. **P3 — video overlay** (movement 1 meets the paper): film the
   interaction, sync by clap (a sharp accel spike findable in both the
   record and the footage), `bake-overlay` renders intent messages
   chat-log style (plus organ events) onto the video.

## Transport doctrine (settled 2026-07)

- Streams whose value is freshness (sensors, probes): **UDP-OSC** — a
  retransmitted sample is a stale sample; TCP's in-order guarantee turns
  rare loss into frequent latency (measured: ~1.5% loss → ~200 ms stalls).
- Payloads whose value is completeness (journal, instinct code): reliable
  transport (TCP-framed OSC when the on-device era needs it) — never UDP.
- The spine may relay anything to tool-facing UDP-OSC subscribers; tools
  never care where the body runs.
- At stethoscope rates (~10–20 msg/s) UDP costs nothing and buys
  statelessness and universal tooling; the jsonl record makes loss
  harmless by contract.
