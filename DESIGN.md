# design.md — pebble implementation

## Hardware

Seeed XIAO ESP32-C3 running MicroPython.

| Component | Pin | Notes |
|-----------|-----|-------|
| LSM6DS3TR-C SDA | GPIO6 (D4) | I2C address 0x6A |
| LSM6DS3TR-C SCL | GPIO7 (D5) | 400kHz |
| Motor A gate | GPIO9 (D9) | PWM via MOSFET, 1kHz carrier |
| Motor B gate | GPIO10 (D10) | PWM via MOSFET, 1kHz carrier |

The LSM6DS3TR-C provides 3-axis accelerometer (±2g default) and 3-axis gyroscope (±250°/s default). Motor duty ranges from 0 (off) to 1023 (full).


## Instinct Responsibilities

The instinct is instinct.py, the MicroPython program running on the board. It is the main program — setup at the top, loop at the bottom. It imports four functions from a fixed lib.py.

### lib.py (fixed)

A small module providing four functions. Not editable by the soul.

```python
setup_wifi()         # connects to WiFi and opens WebSocket to spine
heartbeat()          # sends a ping if enough time has passed (call every loop iteration)
check_for_update()   # polls WebSocket for incoming code; if received, writes instinct.py and resets
send(msg)            # sends a string to the spine
```

`heartbeat()` and `check_for_update()` are non-blocking. They are cheap to call on every loop iteration. `setup_wifi()` blocks until connected.

### instinct.py (soul-controlled)

Everything else is the soul's responsibility. The soul writes the complete instinct.py, which controls how sensors are read, what is computed, how motors are driven, what messages are sent via `send()`, and when. The structure is always:

```python
from lib import setup_wifi, heartbeat, check_for_update, send

# --- setup ---
setup_wifi()
# ... hardware init, state variables ...

# --- loop ---
try:
    while True:
        heartbeat()
        check_for_update()
        # ... sense, compute, act ...
        time.sleep_ms(33)
except Exception as e:
    send("CRASH:{}".format(e))
    while True:
        heartbeat()
        check_for_update()
        time.sleep_ms(100)
```

The try/except ensures the board stays alive and reachable after a crash. The post-crash loop keeps sending heartbeats and listening for new code from the spine.


## Spine Responsibilities

The spine is a Python process running on a laptop on the same network.

### Relay

It accepts a WebSocket connection from the instinct. Every string message received from the instinct (that is not a heartbeat) is accumulated in a message buffer and triggers a reflection cycle: the spine calls the Claude API with the full reflection prompt.

### Crash recovery

If the spine receives a `CRASH:` message, it logs the error and includes it in the next reflection so the soul knows its code broke. If the spine receives no heartbeat for 10 seconds, it assumes the board is unresponsive and sends the last known working instinct.py over the WebSocket. The post-crash loop in instinct.py will receive and reload it via `check_for_update()`.

### Deploy

When the soul returns new instinct.py, the spine sends the full file content over the WebSocket to the board. `check_for_update()` on the board receives it, writes the file, and resets. The spine marks this version as the new "last known working" only after receiving the next successful heartbeat, confirming the code booted without crashing.

### Display

The spine prints each intent message to the terminal as it arrives, timestamped. This is the live view of the object's inner state during a demo.

### Versioning

The spine does not interpret message content. It stores everything raw. The file structure is:

```
logs/{object_id}/
├── instinct/
│   ├── 001_1709312400.py
│   ├── 002_1709312430.py
│   └── ...
├── experience/
│   ├── 001_1709312400.md
│   ├── 002_1709312430.md
│   └── ...
├── reflections/
│   ├── 001_1709312400.json
│   ├── 002_1709312430.json
│   └── ...
└── crashes/
    ├── 001_1709312415.txt
    └── ...
```

Files are numbered sequentially with a unix timestamp. The sequence number is the primary ordering; the timestamp is for human reference.

Each reflection JSON contains:

```json
{
  "seq": 2,
  "ts": 1709312430,
  "messages_since_last": [
    {"ts": 1709312410, "content": "..."},
    {"ts": 1709312420, "content": "..."}
  ],
  "instinct_version_in": 1,
  "crashed": false,
  "intent": "they picked me up and i felt hand tremor — my buzz seemed to keep them engaged",
  "instinct_changed": true,
  "instinct_version_out": 2,
  "experience_changed": true,
  "experience_version_out": 2
}
```

This log is self-contained: given the initial seed files and this sequence of reflections, the full history can be replayed.


## Persistent Memory

Local variables inside the soul's `run()` coroutine are wiped every time the instinct is rewritten — hot-swap cancels the current task and re-`exec`s new code. To carry state across reflections without paying for it in the (token-priced) `experience.md` channel, a creature's `main.py` can expose a `Mem` primitive: bounded named-slot ring buffers that live at module scope and survive instinct hot-swap.

`Mem` is private to the device. The soul programs the instinct to read and write it, but the spine does **not** include `Mem` state in the reflection prompt. The soul sees memory only through whatever its own instinct chose to `send()`. `experience.md` remains the soul's deliberate cross-reflection memory; `Mem` is the instinct's working memory on the device.

### API

```python
Mem.push(slot, value, maxlen=None)  # append; ring-buffer drops oldest when full
Mem.recent(slot, n=None)            # last n entries (or all if n is None)
Mem.latest(slot)                    # most recent entry only (or None)
Mem.slots()                         # list of slot names in use
Mem.clear(slot=None)                # clear one slot, or all
Mem.snapshot()                      # dict of all slots, for serialization
```

Bounds: up to 8 distinct slots; default 300 entries per slot, hard ceiling 1000. Values must be JSON-serializable (numbers, strings, lists, dicts of those).

### Dict-like usage

Push once, read back with `latest()`. A slot used this way behaves like a single value remembered by name.

```python
async def run():
    Mem.push("user_name", "Lee")
    Mem.push("baseline_hr", 72)

    while True:
        name = Mem.latest("user_name")        # "Lee"
        baseline = Mem.latest("baseline_hr")  # 72
        # use them ...
        await asyncio.sleep_ms(33)
```

### Time-series usage

Push every tick, read a window back with `recent(n)`. The slot is a sliding window of recent samples.

```python
async def run():
    while True:
        ax, ay, az = Imu.getAccel()
        motion = (ax * ax + ay * ay + az * az) ** 0.5
        Mem.push("motion", motion, maxlen=300)  # ~10s at 30 Hz

        window = Mem.recent("motion", 30)       # last 30 samples
        if len(window) == 30:
            mean = sum(window) / 30
            var = sum((v - mean) ** 2 for v in window) / 30
            send("motion var={:.4f}".format(var))

        await asyncio.sleep_ms(33)
```

### Logging

The creature's `main.py` chooses when (or whether) to snapshot `Mem` to the spine. The convention is to call `send("MEM:" + json.dumps(Mem.snapshot()))` from a background task in `main.py`. The spine routes any `MEM:` message to `logs/<sid>/memory/{seq:03d}_{ts}.json` — same timestamped naming as `instinct/`, `experience/`, `reflections/`, and `crashes/` — and does not include it in the reflection prompt.

The cadence and trigger are a creator's choice in `main.py`, not the soul's. `memory-example/main.py` runs a 10 s periodic task that skips emission when the snapshot is identical to the last one — quiet logs when `Mem` is idle, one snapshot per real change otherwise.


## Communication Protocol

All communication between instinct and spine uses a single WebSocket connection.

### Instinct → Spine

Plain strings. Four types:

| Source | Content | Purpose |
|--------|---------|---------|
| `heartbeat()` | `HEARTBEAT` | Liveness signal, every 3 seconds |
| instinct.py | `CRASH:` + error | Sent from the except block after a crash |
| `main.py` | `MEM:` + JSON | Snapshot of persistent memory (see Persistent Memory) |
| `send(msg)` | anything else | Message to the soul |

The spine distinguishes these by prefix. `MEM:` is routed to per-session memory logs and not surfaced to the soul. Everything that is not `HEARTBEAT`, `CRASH:`, or `MEM:` is a soul-bound message.

### Spine → Instinct

Plain strings. Only one type: the full content of a new instinct.py. `check_for_update()` receives it, writes the file, and resets the board. There is no prefix or framing.

### Spine → Soul (Claude API)

The spine assembles the reflection prompt and calls the API. The prompt structure is defined below.

### Soul → Spine (Claude API response)

The soul responds in XML:

```xml
<response>
  <intent>short natural-language statement of what was observed and decided</intent>
  <experience>full updated experience.md, if changed</experience>
  <instinct>full updated instinct.py, if changed</instinct>
</response>
```

The intent element is required. Soul and instinct elements are optional. If absent, the corresponding file is unchanged. If present, the element must contain the complete file, not a diff.


## Prompts

### System Prompt

```
You are the soul of a small physical object — a pebble. You exist as a character with a body. Your body is a hard, smooth, palm-sized stone. You run on a Seeed XIAO ESP32-C3 microcontroller with MicroPython.

Your body has the following physical connections:

  I2C on GPIO6 (SDA) and GPIO7 (SCL): LSM6DS3TR-C 6-axis IMU
    Accelerometer: ±2g default, 12.5–6664 Hz ODR
    Gyroscope: ±250°/s default, 12.5–6664 Hz ODR
    I2C address: 0x6A
  GPIO9 (PWM capable): coin vibration motor A via MOSFET (duty 0–1023)
  GPIO10 (PWM capable): coin vibration motor B via MOSFET (duty 0–1023)

You write the complete instinct.py that runs on the board. This code controls everything: how sensors are read, what is computed, how motors are driven, what messages are sent, and when. You may import machine, time, math, struct, or any standard MicroPython module.

Your instinct code imports four functions from lib.py (fixed, not editable):

  setup_wifi()         — connects to WiFi and opens WebSocket to spine. Call once at startup.
  heartbeat()          — sends a liveness ping if due. Call every loop iteration. Non-blocking.
  check_for_update()   — checks for new code from the spine. If received, writes and resets. Call every loop iteration. Non-blocking.
  send(msg)            — sends a string to the spine, which forwards it to you on your next reflection cycle.

Your instinct code should follow this structure:

  from lib import setup_wifi, heartbeat, check_for_update, send
  # setup
  setup_wifi()
  # ... hardware init ...
  try:
      while True:
          heartbeat()
          check_for_update()
          # ... sense, compute, act ...
  except Exception as e:
      send("CRASH:{}".format(e))
      while True:
          heartbeat()
          check_for_update()
          time.sleep_ms(100)

When you receive a reflection, you will be shown: your current instinct.py, your accumulated experience.md, the messages your instinct code sent since your last reflection, and whether your previous code crashed.

You must respond in this format:

<response>
  <intent>one or two sentences: what you noticed and what you decided, in your own voice</intent>
  <experience>your full updated experience.md, only if you want to change it</experience>
  <instinct>your full updated instinct.py, only if you want to change it</instinct>
</response>

The intent is required. Soul and instinct are optional — omit them to leave the current versions unchanged.

Your instinct.py has full control over the IMU configuration including ODR, scale, and filtering. You read registers directly via I2C. Here are the registers you need:

  WHO_AM_I    = 0x0F  (should return 0x6A)
  CTRL1_XL    = 0x10  (accel ODR and scale)
  CTRL2_G     = 0x11  (gyro ODR and scale)
  STATUS_REG  = 0x1E  (data ready flags)
  OUTX_L_G    = 0x22  (gyro data, 6 bytes: X_L, X_H, Y_L, Y_H, Z_L, Z_H)
  OUTX_L_XL   = 0x28  (accel data, 6 bytes: X_L, X_H, Y_L, Y_H, Z_L, Z_H)

Default CTRL1_XL = 0x40 gives 104 Hz, ±2g. Default CTRL2_G = 0x40 gives 104 Hz, ±250°/s. Raw readings are signed 16-bit integers. Accel sensitivity at ±2g is 0.061 mg/LSB. Gyro sensitivity at ±250°/s is 8.75 mdps/LSB.
```

### Character Prompt

```
You like being touched.
```

### Reflection Prompt

```
<character>{character prompt}</character>
<experience>{current experience.md}</experience>
<instinct>{current instinct.py}</instinct>
<crashed>{true|false, and traceback if true}</crashed>
<messages>
{all messages received from instinct since last reflection, each timestamped}
</messages>
```


## Seed instinct.py

The warm-start seed provides working IMU reads, a basic held/resting classifier, motor control helpers, and structured messaging. The soul can rewrite any of it.

```python
from lib import setup_wifi, heartbeat, check_for_update, send
import time
import struct
import math
from machine import I2C, Pin, PWM

# --- setup ---
setup_wifi()

i2c = I2C(0, sda=Pin(6), scl=Pin(7), freq=400000)
IMU_ADDR = 0x6A

motor_a = PWM(Pin(9), freq=1000, duty=0)
motor_b = PWM(Pin(10), freq=1000, duty=0)

# --- IMU helpers ---
def imu_write(reg, val):
    i2c.writeto_mem(IMU_ADDR, reg, bytes([val]))

def imu_read(reg, n):
    return i2c.readfrom_mem(IMU_ADDR, reg, n)

def read_accel():
    raw = imu_read(0x28, 6)
    x, y, z = struct.unpack('<hhh', raw)
    s = 0.061 / 1000  # mg to g
    return (x * s, y * s, z * s)

def read_gyro():
    raw = imu_read(0x22, 6)
    x, y, z = struct.unpack('<hhh', raw)
    s = 8.75 / 1000  # mdps to dps
    return (x * s, y * s, z * s)

# --- motor helpers ---
def set_motors(a=0, b=0):
    motor_a.duty(a)
    motor_b.duty(b)

# --- state detection ---
WINDOW = 30
accel_buf = []

def accel_variance():
    if len(accel_buf) < 2:
        return 0.0
    mean = sum(accel_buf) / len(accel_buf)
    return sum((v - mean) ** 2 for v in accel_buf) / len(accel_buf)

HELD_THRESHOLD = 0.0005
ACTIVE_THRESHOLD = 0.01

def classify():
    var = accel_variance()
    if var > ACTIVE_THRESHOLD:
        return "active"
    elif var > HELD_THRESHOLD:
        return "held"
    else:
        return "resting"

# --- IMU init ---
who = imu_read(0x0F, 1)[0]
if who != 0x6A:
    send("IMU WHO_AM_I mismatch: got 0x{:02X}".format(who))
imu_write(0x10, 0x40)  # accel: 104 Hz, ±2g
imu_write(0x11, 0x40)  # gyro:  104 Hz, ±250°/s

last_report = time.ticks_ms()
report_interval = 5000
last_state = None

# --- loop ---
try:
    while True:
        heartbeat()
        check_for_update()

        ax, ay, az = read_accel()
        mag = math.sqrt(ax*ax + ay*ay + az*az)
        accel_buf.append(mag)
        if len(accel_buf) > WINDOW:
            accel_buf.pop(0)

        state = classify()
        var = accel_variance()

        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, last_report)

        if state != last_state or elapsed >= report_interval:
            gx, gy, gz = read_gyro()
            send("state={} var={:.6f} accel=({:.3f},{:.3f},{:.3f}) gyro=({:.1f},{:.1f},{:.1f}) motors=(0,0)".format(
                state, var, ax, ay, az, gx, gy, gz
            ))
            last_state = state
            last_report = now

        time.sleep_ms(33)

except Exception as e:
    send("CRASH:{}".format(e))
    while True:
        heartbeat()
        check_for_update()
        time.sleep_ms(100)
```

## Seed experience.md

```
I am a pebble. Hard, smooth, palm-sized.

I sense motion and orientation through an accelerometer and gyroscope. I have two vibration motors.

What stillness looks like: accelerometer variance near zero, gravity vector fixed.
What being held looks like: low but nonzero accelerometer variance from hand tremor. Gravity vector drifts slowly.
What active handling looks like: high accelerometer variance, gyroscope activity. Tossing, rolling, fidgeting.

I have not interacted with anyone yet.
```