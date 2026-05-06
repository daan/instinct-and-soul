# CORES3 — M5 MicroPython API

Source: live introspection on a physical CORES3 running UIFlow MicroPython (firmware reports `MicroPython v1.27.0-dirty` on `esp32`).

This file is the source-of-truth for crafting `creatures/m5cores3/system_prompt.md` once that creature exists. Add a section per sensor/actuator as you probe it.

## Module structure

After `import M5` and `M5.begin()`:

| Attribute | What it is |
|---|---|
| `M5.BOARD`, `M5.getBoard()` | Board identification |
| `M5.Imu` | 6/9-axis IMU |
| `M5.Speaker`, `M5.Mic` | Audio out / in |
| `M5.Display`, `M5.Lcd`, `M5.Displays`, `M5.UserDisplay` | Screen |
| `M5.Touch` | Touch input |
| `M5.BtnA`, `M5.BtnB`, `M5.BtnC`, `M5.BtnEXT`, `M5.BtnPWR` | Buttons (some virtual on CORES3) |
| `M5.Power` | Battery / power management |
| `M5.Widgets` | High-level UI widgets |
| `M5.Als` | Ambient light sensor |
| `M5.Led` | Onboard LED |
| `M5.update()` | Call in your main loop for input + audio polling |

## IMU

Chip: **BMI270** (`M5.Imu.getType() == 6 == M5.Imu.IMU_TYPE.BMI270`).

| Method | Returns | Units |
|---|---|---|
| `M5.Imu.isEnabled()` | `bool` | |
| `M5.Imu.getType()` | `int` | Compare with `M5.Imu.IMU_TYPE.*` |
| `M5.Imu.getAccel()` | `(x, y, z)` tuple of floats | g (1 g ≈ 9.81 m/s²) |
| `M5.Imu.getGyro()` | `(x, y, z)` tuple of floats | deg/s |
| `M5.Imu.getMag()` | `(x, y, z)` tuple of floats | µT (raw, uncalibrated) |

`IMU_TYPE` enum: `NULL=0, UNKNOWN=1, SH200Q=2, MPU6050=3, MPU6886=4, MPU9250=5, BMI270=6`.

Example resting reading: `accel=(+0.012, -0.005, +1.005)` (z = gravity ≈ +1g), `gyro=(+0.12, +0.06, -0.06)` (small drift), `mag=(-248.5, +174.0, -76.4)`.

## Display (LCD)

Resolution: **320 × 240**. Module: `M5.Display`.

Drawing methods (selection): `clear`, `drawPixel`, `drawLine`, `drawCircle`, `drawRect`, `drawEllipse`, `drawArc`, `drawString`, `drawCenterString`, `drawRightString`, `drawJpg`, `drawPng`, `drawBmp`, `drawQR`, `width()`, `height()`.

For higher-level layout use `M5.Widgets`.

## Widgets

```python
lbl = M5.Widgets.Label(text, x, y, scale, fg, bg, font)
lbl.setText("new text")     # update without flicker
lbl.setColor(fg, bg)
lbl.setCursor(x, y)
lbl.setFont(font)
lbl.setSize(scale)
lbl.setVisible(True)
```

Other widget classes: `Circle`, `Rectangle`, `Line`, `Triangle`, `Image`, `Title`, `QRCode`.

Module helpers: `Widgets.fillScreen(color)`, `Widgets.setBrightness(0-255)`, `Widgets.setRotation(n)`.

### Fonts (`M5.Widgets.FONTS.<name>`)

DejaVu: 9, 12, 18, 24, 40, 56, 72.
Montserrat: 12, 14, 16, 18, 24, 40, 44, 48.
ASCII7.
CJK: AlibabaPuHuiTiCN24, AlibabaSansJA24, AlibabaSansKR24, EFontCN24, EFontJA24, EFontKR24.

### Colors (`M5.Widgets.COLOR.<name>`)

BLACK, WHITE, RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA, ORANGE, PINK, PURPLE, NAVY, MAROON, OLIVE, DARKCYAN, DARKGREEN, DARKGREY, LIGHTGREY, GREENYELLOW.

Or 24-bit RGB hex literals: `0xFF0000` = red, `0x000000` = black.

## ALS — ambient light + proximity

Module: `M5.Als`. On CORES3 this exposes the LTR-553ALS-WA combo sensor (ambient light + proximity).

| Method | Returns | Units |
|---|---|---|
| `M5.Als.getLightSensorData()` | `int` | raw counts (room light ≈ 77; covered finger ≈ 35) |
| `M5.Als.getProximitySensorData()` | `int` | raw counts; ~0 when far, climbs as something approaches the front face |

No init call needed — `M5.begin()` is sufficient.

Example resting reading (CORES3 face-up on a desk, normal room light): `light=77, prox=0`.

## Speaker

Module: `M5.Speaker`. Already enabled after `M5.begin()` (`isEnabled() == True`), but `setVolume()` may need to be called or no audio is heard.

| Method | Notes |
|---|---|
| `M5.Speaker.begin()` | Initialize. Already-on after `M5.begin()` but call again is safe. |
| `M5.Speaker.end()` | Deinit; silences the amplifier idle hiss. Call when you stop using audio. |
| `M5.Speaker.setVolume(0..255)` | Master volume. `128` is comfortable; `255` is piercing. |
| `M5.Speaker.setVolumePercentage(0.0..1.0)` | Same, 0..1 scale. |
| `M5.Speaker.getVolume()` | Returns int (0..255). Default after `M5.begin()` was `64`. |
| `M5.Speaker.getVolumePercentage()` | Returned `0.0` in the probe even with `getVolume()=64` — likely tracks a per-channel mix level rather than the master setting. Don't trust it. |
| `M5.Speaker.tone(freq_hz, ms)` | Play a tone. Returns immediately — playback runs in the background. Sleep for `ms` (or longer) before issuing the next call. |
| `M5.Speaker.stop()` | Stop current playback. |
| `M5.Speaker.isPlaying()` | bool |
| `M5.Speaker.isEnabled()` | bool |

Other (not probed): `playWav`, `playWavFile`, `playRaw`, `setChannelVolume`, `getChannelVolume`, `setAllChannelVolume`, `setPA`, `config`, `getPlayingChannels`, `isRunning`.

Verified pattern (chirp 200 → 2000 Hz, 100 Hz steps, 110 ms each):

```python
M5.Speaker.begin()
M5.Speaker.setVolume(128)
for freq in range(200, 2100, 100):
    M5.Speaker.tone(freq, 100)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 110:
        M5.update()
        time.sleep_ms(10)
M5.Speaker.stop()
```

Gotcha: this is a different idiom from the sticks3, where `Speaker.tone()` had to be called repeatedly in a tight inner loop (~50 ms cadence) for any sound to come out. On CORES3, a single `tone()` call plays for the full requested duration on its own. Don't carry the sticks3 pattern over.

## Grove ports

The CORES3 has three Grove ports on the side:

| Port | Color | Function | Pin 1 (yellow) | Pin 2 (white) |
|---|---|---|---|---|
| A | red | I2C / generic | GPIO1 (SDA) | GPIO2 (SCL) |
| B | black | IO | GPIO8 | GPIO9 |
| C | blue | UART | GPIO17 (TX) | GPIO18 (RX) |

5V and GND are on the red/black wires of the Grove cable.

Grove modules use one of the two signal pins depending on the module. Don't assume — verify with a quick PWM sweep on each candidate pin.

### Grove vibration motor — verified

The original M5Stack Grove vibration motor on **Port A** uses **GPIO1** (the yellow wire / SDA pin). GPIO2 produced no output. Drive it via PWM:

```python
from machine import Pin, PWM
motor = PWM(Pin(1), freq=5000, duty=0)
motor.duty(d)   # 0..1023
```

5 kHz PWM works fine; the motor is mechanical so the carrier frequency just needs to be above audible.

Calibrated thresholds (this specific unit, on Grove Port A of this CORES3):

| Duty | Behavior |
|---|---|
| 0–249 | Imperceptible. Motor does not activate. |
| 250 | Spins up only with sustained drive; short pulses (<150 ms) at 250 are silent because the motor can't overcome static friction in time. |
| 300 | Reliable minimum for short pulses; reaches felt amplitude within ~50 ms. |
| 300–600 | Clearly felt; good range for heartbeat / pulse patterns. |
| Above 600 | Strong. Use sparingly. |

Brief pulses need higher duty than sustained vibration to overcome motor inertia. PWM duty is integer 0..1023; higher values are silently clipped.

## TODO — not yet probed

Add a section here once each is probed. Each section should follow the IMU template: chip/where, methods table, units, example values, gotchas.

- [ ] Mic (`M5.Mic`)
- [ ] Touch (`M5.Touch`) — touchscreen input
- [ ] Buttons (`M5.BtnA/B/C/EXT/PWR`) — which are physical on CORES3 vs virtual/touch
- [ ] Power (`M5.Power`) — battery percentage, voltage, charging state
- ~~Led~~ — `M5.Led` exists in the namespace but `M5.Led.getCount()` returns `0` on CORES3. The API (`setColor`, `setBrightness`, `setAllColor`, `display`) targets boards like the Atom Lite/Matrix that have addressable WS2812B LEDs. CORES3's green power and charging indicators are hardwired and not software-controllable.
- [ ] SD card / filesystem
- [ ] WiFi STA / AP setup pattern

## Probing recipe

To inspect any module quickly without writing files:

```bash
mpremote connect /dev/tty.usbmodem3101 exec "
import M5
M5.begin()
print('attrs:', sorted([a for a in dir(M5.Speaker) if not a.startswith('_')]))
"
```

Class methods can be inspected without instantiating, which avoids hangs from heavy constructors:

```bash
mpremote connect /dev/tty.usbmodem3101 exec "
import M5
print('Label methods:', sorted([a for a in dir(M5.Widgets.Label) if not a.startswith('_')]))
"
```
