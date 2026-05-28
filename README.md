# instinct and soul

## abstract

We propose an architecture for embodied objects that use implicit physical interaction as a form of prompting a large language model. The system operates through a dual-process loop inspired by Kahneman's System 1 and System 2: a fast **instinct** layer of autonomous reactive code running on a microcontroller handles real-time sensor-actuator behavior, while a slow **soul** layer, an LLM called periodically by a gateway, reflects on accumulated sensor logs, evaluates whether the object's current instincts serve its character desire, and rewrites the instinct code accordingly. The LLM does not control the object in real time. Instead, it performs reinforcement learning through narrative reasoning rather than gradient descent, evolving the object's behavioral code and accumulating a natural-language personality that is unique to each human it interacts with.

The only fixed elements are MicroPython itself, the hardware pin assignments, and a boot runtime that manages connectivity, heartbeats, and code hot-swapping. Everything else, sensor processing, state logic, motor patterns, communication, is the soul's to write and rewrite.

We demonstrate the architecture through two physical forms sharing the same character prompt, "you like being touched," but with different sensor configurations: a hard pebble with only an IMU (proprioception), and a soft squeezable object with an IMU plus IR reflective deformation sensors (proprioception plus touch). The same desire, expressed through different bodies, produces divergent emergent behaviors, illustrating how embodiment shapes personality even when the underlying intelligence is identical.

## Quick Start

The system is designed for micro controllers running micropython and have a wifi network. I tested "creatures with esp32c3 or esp32s3 micro controllers, such as the seeed studio XIAO and M5STACK STICKS3 and CORES3. 

```
git clone git@github.com:daan/instinct-and-soul.git
cd instinct-and-soul
uv sync
source .venv/bin/activate
```
edit [.config/networks/example.toml](.config/networks/example.toml) with your network specifics

attach your device (e.g. m5cores3) you might need to [edit boot.py](INSTALL.md#uiflow-boards-cores3-sticks3) 

```
flash creatures/cores3 --wifi lee 
```
you should see the network status on the display.

run the interactive tuner (no llm required) 
```
tune creatures/cores3
```
or run spine. By default it uses Anthropic Claude Sonnet — set `ANTHROPIC_API_KEY` in your env and you're done:
```
spine creatures/cores3
```
To use a different model or API (OpenAI-compatible endpoints like OpenRouter, Ollama, Groq, …), copy [.config/config.example.toml](.config/config.example.toml) to `.config/config.toml` and edit, or drop a profile file into `.config/llm/` (see [.config/llm/example.toml](.config/llm/example.toml)) and pass `--llm <name>`:
```
spine creatures/cores3 --llm openrouter
```

Start with the [installation guide](INSTALL.md) for detailed instructions.

Each runnable thing is a **creature**: a folder under `creatures/` that bundles a body (MicroPython runtime + hardware description) with a character (desire + initial personality + initial instinct code). Two creatures are included:

- `creatures/touchy-pebble/` — Xiao ESP32-C3 + IMU + two vibration motors, "you like being touched"
- `creatures/sticks3/` — M5StickS3 with vibration hat, screen, and speaker, "you like being touched"

To run one, point the spine at it:

```
spine creatures/touchy-pebble

```

To make a new variant — same body, different goal — copy the folder and edit `character.md` and `seed_experience.md`.

If a creature needs device-side Python libraries (e.g. a sensor driver like `vl53l0x.py`), drop them into `creatures/<name>/lib/`. `flash` copies everything under `lib/` to `/lib/` on the device, preserving subdirectories — MicroPython has `/lib` on `sys.path` by default, so `import vl53l0x` works from both `main.py` and `instinct.py`. Host-side files (`tune.py`, `test_*.py`, `recipes.py`) stay outside `lib/` and remain on the laptop.

## Visualizing sessions

Every `spine` run writes a session log to `creatures/<x>/logs/<session_id>/` — every accumulated message, every reflection (with the full LLM prompt and response), every instinct/experience version. The `trace` command opens a session in the browser:

```
trace creatures/keep_changing                       # latest session in that creature
trace creatures/keep_changing/logs/20260507_114404  # a specific session
trace creatures/keep_changing --rebake              # force-rebake trace.json
```

It bakes a `trace.json` next to the session log (cached on subsequent runs), starts a local HTTP server on `127.0.0.1:8765` rooted at the repo, and opens the tracer in your default browser.

The view has two panes:

- **Horizontal timeline** (top, D3 SVG) — two lanes, `instinct` and `soul`. Each reflection cycle shows as a faint polyline walking through the instinct messages that triggered it and dropping down to the resulting intent. Scroll to zoom, drag to pan, click an event for details.
- **Vertical chat** (below, scrollable) — every event in time order. The colored gutter on the left of each row identifies which reflection batch the event belongs to: messages and the intent that consumed them share a gutter color. Cycles through 4 muted colors so adjacent batches always differ.

Event kinds: `instinct` (device → spine messages), `soul` (the reflection's intent), `operator` (text typed into the spine's TUI), `failed` (a reflection that errored), plus `crash` and `mem` snapshots when present.

For headless or scripted use, `bake-trace <session_path>` produces the `trace.json` without starting a server.

## System Architecture

### Overview

The system consists of three layers:

**The Instinct (edge node).** A microcontroller running MicroPython with sensors and actuators. A fixed boot runtime handles connectivity and heartbeats; the soul's code runs as an async coroutine within it, executing reactive behavior autonomously at microcontroller speed. At any given moment, the instinct is a Braitenberg vehicle: a reactive sensor-motor wiring that produces behavior without deliberation.

**The Spine (gateway).** A laptop that relays messages between the instinct and the soul, deploys updated instinct code to the board, versions all files, displays the object's inner state on screen, and monitors liveness for crash recovery. The spine does not interpret or buffer sensor data. It relays and protects.

**The Soul (LLM).** Claude, called by the spine each time a message arrives from the instinct. It receives the message, the current instinct code, and the object's accumulated memory. It reflects on whether the current instincts serve the character's desire, and responds with either no change, updated memory, or evolved instinct code.

### The Dual-Process Loop

The instinct runs continuously on the board. The soul operates on a slower cadence, driven by messages from the instinct. The instinct corresponds to System 1 processing (fast, automatic, reactive), the soul to System 2 (slow, deliberate, narrative). The soul does not override the instinct in the moment. It rewires the instinct for next time.

The soul indirectly controls its own reflection rate. It writes the instinct code, which determines what messages are sent and how often. If the soul wants more frequent reflection, it writes instinct code that reports often. If it is satisfied with current behavior, it can write code that reports less frequently. The cadence of reflection emerges from the soul's own decisions about what the instinct should communicate.

During each reflection cycle, the instinct keeps running. The LLM response takes several seconds, during which the object remains responsive. When the soul returns new instinct code, the spine pushes it to the board, which hot-swaps the running coroutine in milliseconds without a board reset.

### The Cost Function

The character prompt implicitly defines a cost function grounded in the sensors. "You like being touched" combined with the sensor semantics makes physical contact the reward signal. The soul evaluates: did my current instinct code result in more touch or less touch since last time? This evaluation happens through narrative reasoning. The soul reads the message from the instinct, interprets it through the character's desire, and decides whether to adapt.

The object cannot force the human to interact. It can only make itself appealing enough that the person wants to keep holding it. If its motor behavior is annoying, the person puts it down, the worst possible outcome for an object that likes being touched.

### Initialization

The system uses a warm start. The soul begins with basic body awareness: a natural-language description of what its sensors measure, what stillness and motion look like in the data, and what its actuators can do. This is sensory grounding, not personality or strategy. The instinct begins with a seed program that includes a working sensor classifier (for example, distinguishing held from resting based on accelerometer variance), structured logging, and motor control functions the soul can call. The soul does not need to discover what touch looks like. Its first decision is what to do about it.

This isolates the interesting design question, how the soul learns to solicit and sustain interaction through motor behavior, from the engineering question of whether the LLM can bootstrap signal classification from raw sensor data. For short user studies, the warm start ensures that participants encounter a responsive object from the first interaction, and the soul's reflection cycles are spent on behavioral adaptation rather than sensor calibration.

A cold start, in which the soul begins empty and the instinct begins with only a minimal sensor-streaming program, is also possible. In this mode the soul must discover everything from scratch: what its sensors mean, what touch looks like in the data, and how to respond. This maximizes emergence but requires more reflection cycles before the object behaves meaningfully.

In both modes, a warm start provides a foundation, not a constraint. The soul can discard, rewrite, or restructure everything in the seed program if it decides a different approach serves its desire better.

### The Runtime

The instinct code runs within a fixed runtime (each creature's `main.py`) that handles everything the soul should not have to think about: WiFi, WebSocket connection, heartbeats, code hot-swapping, and crash recovery. The soul's code is an `async def run()` coroutine that the runtime exec's and runs as an asyncio task.

The runtime provides two things to the instinct code:

**Heartbeat.** An automatic periodic signal sent to the spine as a separate asyncio task, regardless of what the instinct code does. If the spine stops receiving heartbeats, it assumes the board is unresponsive.

**Send.** A `send(msg)` function available in the instinct's scope. The instinct calls it to send a string to the spine, which relays it to the soul. What to send, when to send it, and how to structure the content is entirely up to the instinct code, which the soul writes.

When the spine pushes new code, the runtime cancels the running coroutine, exec's the new code, and starts the new `run()` as a fresh task. If the instinct crashes, the runtime catches the exception, reports it to the spine, and remains alive and reachable for new code.

### Full LLM Control

The LLM writes the complete instinct coroutine that runs on the microcontroller. There is no protected firmware layer beyond the boot runtime. This means the soul can change the sensor reading rate depending on the situation, invent its own signal processing, read sensors in unusual combinations (for example, reading the accelerometer while the motor is active to sense how tightly it is being held, since motor vibration dampens differently under grip pressure), restructure its entire approach between reflection cycles, and discover things the designers would not anticipate.

### What the Soul Is Told

The system prompt provides the hardware truth: pin assignments, sensor specifications, actuator capabilities, and what the boot runtime provides in scope. The reflection prompt provides the character prompt (the desire), the current experience.md, the current instinct code, the accumulated messages from the instinct since the last reflection, and whether the previous instinct code crashed.

The soul interprets the messages through the lens of its character and decides whether to evolve the instinct, update its memory, or leave things as they are.

### Protocol

The system uses WebSocket for all communication between the instinct and the spine.

**Instinct to spine.** Plain strings over the WebSocket. The boot runtime sends `HEARTBEAT` periodically and `CRASH:` on exceptions. The instinct code sends everything else via `send(msg)`. The content, structure, and frequency of these messages is determined by the instinct code, which the soul writes.

**Spine to instinct.** The spine sends new instinct code as a plain string over the WebSocket connection. The boot runtime receives it, cancels the running coroutine, exec's the new code, and starts the new `run()` task. This is the only message the spine sends to the board.

**Spine to soul.** The spine calls the Claude API, passing the character prompt, the current experience.md, the current instinct code, the accumulated messages from the instinct since the last reflection, and whether the previous code crashed.

**Soul to spine.** The soul must return an intent message: a short natural-language statement describing what it observed and what it decided, like a commit summary. This is displayed on the spine's screen and logged. Optionally, the soul may also return updated instinct code, an updated experience.md, or both. If new instinct code is returned, the spine deploys it to the board. If a new experience.md is returned, the spine stores it for the next reflection cycle.

### The Experience File

The experience.md file accumulates the object's lived experience in natural language, written and updated by the soul during reflection. It contains the character's own interpretation of its sensory experience, discovered preferences, and strategies for getting what it wants. It is maintained on the spine and passed to the soul during reflection; it is never sent to the board.

### Versioning

The spine saves every deployed instinct.py, every experience.md update, every message that triggered a reflection, and the soul's full response including the intent message. The complete history is timestamped and replayable, written under the creature's own `logs/<session>/` directory. This log is the primary research data: a full trace of the object's evolving inner life alongside the sensor record of its interaction with the world.