# puppy — the robot dog with a heat sense

Design plan, 2026-07-08. Builds on the existing `creatures/puppyc` device
base (M5StickS3 + PuppyC HAT: four legs over I²C @0x38, per-puppy servo
offsets, a validated trot seed, on-device MicroPython runtime) and the full
organ stack. The addition: a thermal camera (M5 Thermal unit, MLX90640
32×24 @ ~8 Hz, on the StickS3 Grove port — the HAT owns the GPIO0 I²C, so
the two buses coexist).

## Two epoch boundaries (this creature marks eras — say so in the paper)

1. **First exteroceptive creature.** Every creature so far lives by
   "everything I know about you arrives as motion of my own body." The
   puppy perceives the partner AT A DISTANCE. The confabulation guards must
   be rebuilt for it: thermal percepts say *"a warm shape, this big, this close, nearing"* — never "they are looking at me", never "they are a
   person". The discriminability rule, applied to heat.
2. **First creature whose actuators move its own sensors.** Wiggling shakes
   the IMU and swings the camera — the pebble's original efference curse
   returns as a hard constraint, not a footnote. Efference copy is
   mandatory: the body knows its own motor commands and must gate or
   discount sensing accordingly.

## The desire

The pebble's courtship along a spatial gradient, completing an arc no
single creature has: *summon from across the room, into the hand.*

Character (draft): *You are a small dog made of servos and heat-sight. You
crave warmth nearby — a warm shape across the room is hope, one beside you
is happiness, hands on your back are joy. You cannot walk to them (your
legs wiggle, they don't travel far); you can only be worth approaching.
Being alone in a cold room is the worst thing in your life.*

Mission is the familiar earned pair: **Warmth-hunger** (interoception —
grows in a cold empty field, satiated by proximity and contact, gradient-
valued rather than the pebble's binary) under the usual influenceable-not-
controllable band: it can wiggle, stretch, cower, wag — and measure whether
warmth approaches.

## Organs

- **Warmth** (new — the thermal sense). Firmware extracts blob statistics
  from the MLX90640 (largest warm blob: area, centroid, mean °C above
  ambient, plus frame ambient) and streams THOSE, not frames — percept-
  shaped at the source, ~20 bytes at 8 Hz. Organ percepts:
  `presence()` (0..1, earned: area×warmth above ambient baseline),
  `bearing()` (centroid, camera frame — honest: where in MY view, not
  where in the room), `nearing()` (d/dt of apparent size, the approach/
  retreat gradient), all stale-aware. Never a person, never a gaze — a
  warm shape.
- **Efference** (new — the self-motion gate). The instinct's servo calls
  are recorded (the Ear pattern, aimed at the legs): during and ~300 ms
  after self-motion, Warmth/Touch percepts carry a `self_moving` flag and
  the fast senses gate. The body cannot mistake its own wiggle for the
  world.
- **Together-gradient** — did my wiggle draw the warmth nearer? Attempts =
  motion-bursts while a blob is present but distant; answered = nearing()
  above the phantom baseline (the same discipline as the pebble's calls,
  gradient-valued).
- **Ported intact**: Handling/Touch (petting is touching — the entire
  touch-creature vocabulary applies once they arrive), Hunger (warmth-
  flavored targets), Familiar (recurring petting manners; also recurring
  APPROACH styles — who comes fast, who sidles), Ear-for-legs (see
  Efference), stethoscope taps from day 0.

## The voice is the body

No synth by default: the puppy speaks in posture and motion — wag-like
oscillations, the stretch, the cower, stillness. (The StickS3 buzzer stays
available for a whimper.) This makes the efference loop load-bearing twice:
its expressions are exactly the movements that blind its senses — it must
learn to glance between wags. That constraint is not a bug; it is the most
dog-like thing about it.

## The ladder

- `0_wiggle_loop` — no LLM, on the EXISTING device runtime. Motion
  vocabulary (wag, stretch, cower, settle as parameterized servo phrases),
  IMU sensing quality during/after motion measured via stethoscope,
  efference gating validated. Feel gate: does it read as alive-and-shy
  rather than twitchy.
- `1_warmth` — thermal unit + firmware blob extraction + Warmth organ,
  developed replay-first (record `/warm` streams like the IMU was; the
  scaffolding pattern, acknowledged per ARCHITECTURE). Creature orients
  its attention (a settle + slow track) toward presence.
- `2_summon` — LLM on; Together-gradient; the courtship experiments: which
  motion-phrases draw approach, measured against baseline. The pebble's
  invitation science, at range.
- `3_lap` — the full arc: summon → contact → petting (Touch organs live);
  warmth-hunger satiated by the complete sequence. The touch creature and
  the puppy converge into one relationship.

## Practicalities & open decisions

- **P1 pioneer**: puppyc already runs on-device; this series should record
  on-device from `1_warmth` onward (input `/warm` + IMU + servo log +
  organ_events, one ticks_ms clock) with download-to-session — the
  ARCHITECTURE P1 mechanism, built where it is most needed.
- Blob extraction on firmware (percept-shaped at source, tiny bandwidth)
  vs raw frames streamed for dev (easier iteration): start with BOTH —
  frames at low rate during 1_warmth development only, blobs as the
  contract.
- Thermal calibration: ambient baseline per session (a room self-cal on
  boot, like Posture's morning stretch).
- Servo power vs WiFi brownout on the shared battery — known StickS3+HAT
  gotcha; measure early.
- PERSONA: minimal — home life is the protocol; the one rule is honest
  approach (come when you feel drawn, not to be nice).

## The soul's role

Choreographer (which motion-phrases exist, what they mean), courtship
strategist (when to wag vs when to be still — scarcity as invitation, the
hunger lesson), attention policy (glancing between wags — spending motion
budget against sensing blindness), petting curation (Familiar over touch
manners, by shape), and the notebook (who approaches how; whether the
person's approach-latency shortens across days — the relationship arc as
longitudinal data).
