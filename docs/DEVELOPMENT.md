# Development

This repo has three executables and two dev workflows.

## Executables

After `uv sync`, three console scripts are available:

- `spine creatures/<name>` — production: Claude reflects on board messages and rewrites instinct code.
- `tune creatures/<name>` — interactive tuner: you type recipe names, the tuner deploys instinct code by hand. Same WebSocket protocol as the spine; substitutes manual control for the LLM loop.
- `flash creatures/<name>` — copy `<name>/main.py` onto a USB-attached board and reset.

Plus the on-device `creatures/<name>/main.py` MicroPython runtime that connects to whichever laptop process is listening on port 8765 (spine or tuner).

The spine and the tuners are mutually exclusive — only one can hold port 8765 at a time. Switch by quitting one and starting the other; the board reconnects automatically.

## Workflow A: Direct flash

When to use:
- Bringing up a new body for the first time.
- Recovering a hung device that won't accept WebSocket commands.
- Updating the runtime itself (e.g. changing WiFi credentials in `main.py`).
- Pushing a self-contained one-shot test program that runs on-device.

```
flash creatures/touchy-pebble                          # auto-detects /dev/cu.usbmodem*
flash creatures/touchy-pebble --port /dev/cu.usbmodem1101
mpremote connect /dev/cu.usbmodem1101 repl             # interactive shell
mpremote connect /dev/cu.usbmodem1101 reset            # soft reset
mpremote connect /dev/cu.usbmodem1101 ls               # list files on board
```

`flash` copies `<creature>/main.py` to `:main.py` on the device and resets.

### Recovering a hung M5StickS3

`creatures/sticks3/main.py:34-44` includes a 3-second window at boot where holding **BtnA** drops the device into REPL instead of starting `main()`. Use this when the runtime hangs on a blocking call.

For other hardware lock-ups: hold the power button for ~6 seconds, short-press to power back on, then `mpremote connect /dev/<port> ls` immediately while the device is in its idle window.

###  M5 STICKS3 IMU stuck reading all zeros

If reflections show `accel x=0.0000 y=0.0000 z=0.0000` consistently, the IMU enumerated but its data path didn't come up. `M5.update()` ticks won't recover it; only a hard reset works (`mpremote ... reset`, or power-cycle). Full diagnostic + cause in `test/STICKS3/API.md` under the IMU section.

## Workflow B: Interactive tuner

The tuner is like spine without LLM, it uploads python code "recipe" that is exectuted on the board. This is usefull for interactive tuning sensors and actuators:
- Calibrating motor duty / IMU thresholds for a new body.
- Exploring instinct snippets without burning Claude API calls.
- Validating that a body responds correctly to a known input.

```
tune creatures/touchy-pebble
```

The tuner opens a textual UI on port 8765. Once the board connects, type a recipe:

```
heartbeat 400
pulse 80 250
sweep
imutune
```

Recipes live in `creatures/<name>/recipes.py` as a dict of `{name: {"args": [...], "code": "..."}}`. Each tuner has body-specific commands — `creatures/sticks3/tune.py` has `tone` and `chirp` (speaker), `creatures/touchy-pebble/tune.py` has `mix` and `ripple` (dual motors).

### Adding a recipe to an existing body

1. Add an entry to `creatures/<name>/recipes.py`:
   ```python
   "shiver": {
       "args": [("duty", int, 200)],
       "code": "async def run():\n    motor = PWM(Pin(0), ...)\n    duty = {duty}\n    ..."
   },
   ```
2. Wire the command into `creatures/<name>/tune.py`'s `on_input_submitted` — typically a 3-line `elif cmd == "shiver":` block calling `format_recipe(RECIPES["shiver"], duty=...)`.
3. Update the `PLACEHOLDER` string at the top of `tune.py` so the input field hint is current.

### Recipe template gotchas

- `{name}` placeholders are filled by `format_recipe(spec, name=value)` at dispatch time.
- `{}` and `{...}` patterns inside the recipe (e.g. for the runtime's own `.format()` calls) must be escaped as `{{}}` / `{{...}}` — Python's `str.format` collapses them on the way out.
- A recipe with no `args` is sent verbatim — `format_recipe` skips `.format()` entirely.

## Workflow C: Hardware probes (`test/<hw>/`)

Test is uploading firmwares with the sole purpose to debug sensors and actuators:
- Bringing up a new hardware platform before there's a creature for it.
- Discovering an unfamiliar M5/MicroPython API (what methods exist, what units they return, what gotchas hide where).
- Writing a focused single-purpose sketch you want to flash and forget.

Each test is a self-contained folder with a single `main.py`:

```
test/
├── test_llm_communication.py     # laptop-side python tests
├── test_spine.py
└── CORES3/                        # one folder per hardware platform
    ├── API.md                     # accumulated API reference for this platform
    ├── test_imu/
    │   └── main.py
    ├── test_display/              # add as you go
    │   └── main.py
    └── test_speaker/
        └── main.py
```

The `flash` script works against any folder containing a `main.py`, so:

```
flash test/CORES3/test_imu
```

### Reading serial output

After flashing, the device runs `main.py` automatically. Watch its `print()` calls:

```
mpremote connect /dev/cu.usbmodem... repl   # interactive
```

Or capture a fixed window non-interactively:

```
python -c "
import serial, time
s = serial.Serial('/dev/tty.usbmodem...', 115200, timeout=0.2)
t0 = time.time()
while time.time() - t0 < 3.0:
    chunk = s.read(4096)
    if chunk: print(chunk.decode('utf-8', errors='replace'), end='')
"
```

### Discovering an unknown API via mpremote

Probe live attributes without writing any files:

```
mpremote connect /dev/tty.usbmodem... exec "
import M5
M5.begin()
print('attrs:', sorted([a for a in dir(M5.Imu) if not a.startswith('_')]))
"
```

Inspect class methods without instantiating (avoids hangs from heavy constructors):

```
mpremote connect /dev/tty.usbmodem... exec "
import M5
print('Label methods:', sorted([a for a in dir(M5.Widgets.Label) if not a.startswith('_')]))
"
```

### `API.md` per platform

Each `test/<hw>/API.md` accumulates the verified API as you probe peripherals — methods, units, return types, example values, gotchas. This file is the source-of-truth for crafting `creatures/<hw>/system_prompt.md` once you start a creature on that hardware. Add a section per peripheral with a consistent template (chip/where, methods table, units, example resting values, gotchas).

`test/CORES3/API.md` is the canonical example.

## Adding a new creature

1. Create the folder: `creatures/<new-name>/`.
2. Required files:
   - `main.py` — MicroPython runtime. Easiest start: copy from a similar body (`creatures/touchy-pebble/main.py` for Xiao-class, `creatures/sticks3/main.py` for M5-class) and edit pin assignments, WiFi config, scope dict.
   - `system_prompt.md` — hardware truth Claude sees as system prompt.
   - `character.md` — one-line desire. e.g. `You like being touched.`
   - `seed_experience.md` — initial personality, written from the body's first-person view.
   - `seed_instinct.py` — initial `async def run()` coroutine. Usually a sensor-streamer with motors off.
   - `recipes.py` — start empty (`RECIPES = {}`), add as you tune.
   - `tune.py` — copy from a similar body and rename the class + `STATUS_LABEL`.
3. `spine creatures/<new-name>` will create `logs/` automatically on first run.

## Shared scaffolding

`src/instinct_and_soul/harness.py` provides `TuneAppBase` and `format_recipe`. Each creature's `tune.py` subclasses `TuneAppBase`, supplies a `compose()` and `on_input_submitted()`, and reuses the websocket server, heartbeat tracking, log panel, status bar, and command history for free.

## Smoke tests

After any change to the harness, recipes, or tuners:

```
uv run python -c "import ast; ast.parse(open('src/instinct_and_soul/harness.py').read())"
uv run python -c "import ast; ast.parse(open('creatures/touchy-pebble/tune.py').read())"
uv run python -c "import ast; ast.parse(open('creatures/sticks3/tune.py').read())"
uv run spine creatures/touchy-pebble --help
```

Recipe parity check (every recipe formats to valid Python):

```
uv run python -c "
import sys, ast
sys.path.insert(0, 'creatures/touchy-pebble')
from instinct_and_soul.harness import format_recipe
from recipes import RECIPES
for name, spec in RECIPES.items():
    defaults = {n: d for (n, t, d) in spec.get('args', [])}
    ast.parse(format_recipe(spec, **defaults))
print('all recipes parse')
"
```
