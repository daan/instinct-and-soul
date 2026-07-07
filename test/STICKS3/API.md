# M5StickS3 — M5 MicroPython API

Source: live introspection on a physical StickS3 running UIFlow MicroPython (firmware reports `MicroPython v1.27.0-dirty` on `esp32`, board id `26`).

This file is the source-of-truth for crafting / updating `creatures/sticks3/system_prompt.md`. Add a section per peripheral as you probe it.

## Module structure

After `import M5` and `M5.begin()`:

| Attribute | Notes on this board |
|---|---|
| `M5.Imu` | BMI270, full API including `getMag()` |
| `M5.Display`, `M5.Lcd` | 135 × 240 portrait color LCD |
| `M5.Speaker` | Built-in mono speaker (see gotcha) |
| `M5.Mic` | Built-in microphone |
| `M5.BtnA`, `M5.BtnB` | Physical buttons |
| `M5.BtnC` | API present but not wired (always returns False) |
| `M5.Power` | Rich battery + power API; `setLed`/`setVibration` are no-ops |
| `M5.Touch` | API present but `getCount()` returns 0 (no touchscreen) |
| `M5.Als` | API present but `getLightSensorData()=0`, `getProximitySensorData()=1` — no real ALS chip |
| `M5.Led` | `getCount()=0` — no addressable WS2812 |
| `M5.Widgets` | Same widget API as CORES3 |
| `M5.update()` | Call in your main loop |

## IMU

Chip: **BMI270** (`getType() == 6 == M5.Imu.IMU_TYPE.BMI270`). 6-axis (accel + gyro) only — **no magnetometer wired on this board**. `getMag()` is callable but returns `(0.0, 0.0, 0.0)` always.

| Method | Returns | Units |
|---|---|---|
| `M5.Imu.isEnabled()` | `bool` | |
| `M5.Imu.getType()` | `int` | Compare with `M5.Imu.IMU_TYPE.*` |
| `M5.Imu.getAccel()` | `(x, y, z)` tuple of floats | g (1 g ≈ 9.81 m/s²) |
| `M5.Imu.getGyro()` | `(x, y, z)` tuple of floats | deg/s |
| `M5.Imu.getMag()` | `(0.0, 0.0, 0.0)` always | n/a — no magnetometer |

`IMU_TYPE` enum: `NULL=0, UNKNOWN=1, SH200Q=2, MPU6050=3, MPU6886=4, MPU9250=5, BMI270=6`.

Differs from CORES3: same chip, same API, but on the StickS3 there's no companion magnetometer chip (the CORES3 has one). Treat the StickS3 IMU as 6-axis only.

### Gotcha — IMU stuck reading all zeros

**Symptom**: `getAccel()` and `getGyro()` both return `(0.0, 0.0, 0.0)` even though `isEnabled()` returns `True` and `getType()` returns `6` (BMI270). At rest you should see `accel ≈ (0, 0, 1)` (or whichever axis gravity is along, depending on orientation). All-zeros means the chip enumerated but its data path never came up.

**Cause**: `M5.begin()` doesn't always cleanly initialize the IMU when the firmware is in a warm/dirty state — for example, after rapid hot-swaps of instinct code, or after a prior process that left the I2C bus in an odd state. `M5.update()` ticks (even hundreds of them) do **not** recover it.

**Fix**: hard reset the board.

```bash
mpremote connect /dev/cu.usbmodem... reset
# then re-probe
mpremote connect /dev/cu.usbmodem... exec "
import M5; M5.begin()
import time; time.sleep_ms(200)
print('accel:', M5.Imu.getAccel())   # expect non-zero with gravity along one axis
print('gyro:',  M5.Imu.getGyro())    # expect tiny values < 1 deg/s at rest
"
```

The user-facing equivalent is to hold the power button ~6 seconds for a full power-off, then short-press to power back on.

If the IMU still reads zeros after a hard reset, that's a real fault — at that point reach for direct I2C probing (BMI270 `WHO_AM_I = 0x00`, expected `0x24`).

## Display (LCD)

Resolution: **135 × 240** portrait. Module: `M5.Display`.

Same drawing methods as CORES3 (`drawPixel`, `drawLine`, `drawCircle`, `drawString`, etc.) and same `M5.Widgets` high-level API. Only the canvas size differs — layouts must be redone per screen.

## Speaker — gotcha (preserved from old firmware)

A single `Speaker.tone(freq, ms)` call does **not** play for the full duration on the StickS3. Tones must be driven in a tight loop with `M5.update()` ticking the audio engine, per the original sticks3 creature pattern:

```python
M5.Speaker.begin()
M5.Speaker.setVolume(64)
loops = ms // 50
for _ in range(max(1, loops)):
    M5.Speaker.tone(freq, 80)
    M5.update()
    time.sleep_ms(50)
M5.Speaker.end()
```

This is the **opposite of CORES3**, where a single `tone()` call plays through. Keep the idioms separated.

## Power

`M5.Power` exposes a large API including battery state, charging, deep/light sleep, USB output control, and (for boards that have them) `setLed()` and `setVibration()`. On the StickS3:

| Method | Result |
|---|---|
| `M5.Power.getBatteryLevel()` | int 0..100 (e.g. 45) |
| `M5.Power.getBatteryVoltage()` | int mV (e.g. 3664) |
| `M5.Power.isCharging()` | bool |
| `M5.Power.getVBUSVoltage()` | int mV (e.g. 5208 when on USB) |
| `M5.Power.setLed(0..255)` | No-op on this board (no software-controllable front LED). |
| `M5.Power.setVibration(0..255)` | No-op on this board. Use the vibration HAT via raw PWM on `Pin(0)`. |

## Vibration

No built-in vibrator on the bare StickS3 (`M5.Power.setVibration()` is a no-op). The legacy `creatures/sticks3/main.py` drove a vibration HAT via raw PWM on `Pin(0)`. A different vibration accessory will live on a different pin — leave this section TODO until a specific vibrator is chosen.

## Not present on this board

- **Touch screen** — `M5.Touch.getCount()` returns 0.
- **Ambient light / proximity** — `M5.Als.*` calls return trivial values (0 / 1). No real sensor.
- **Addressable LED (WS2812)** — `M5.Led.getCount()` returns 0.
- **Software-controlled front LED** — `M5.Power.setLed()` is a no-op on this board.
- **Built-in vibration motor** — `M5.Power.setVibration()` is a no-op on this board.

## TODO — not yet probed

Add a section here once each is probed. Each section should follow the IMU template: chip/where, methods table, units, example values, gotchas.

- [ ] Mic (`M5.Mic`) — recording, raw audio buffer access
- [ ] Buttons (`M5.BtnA`, `M5.BtnB`) — wasPressed / wasReleased / hold detection
- [ ] IR transmitter (StickS3 has one — needs separate module probe)
- [ ] Power deep/light sleep behavior
- [ ] Vibration accessory (when chosen) — probe pin and PWM frequency
- [ ] Thermal2 unit on Grove (I2C 0x32, MLX90640 behind an MCU) — probe with `test/STICKS3/test_thermal`, then document register map + confirmed fps here

## Probing recipe

```bash
mpremote connect /dev/tty.usbmodem... exec "
import M5
M5.begin()
print('attrs:', sorted([a for a in dir(M5.Mic) if not a.startswith('_')]))
"
```
