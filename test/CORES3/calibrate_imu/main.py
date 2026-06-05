"""
calibrate_imu/main.py — IMU rest + ODR + poll-rate calibration for the CORES3.

Purpose: pin down the three things the synthetic-IMU pipeline needs to match the
real BMI270 — the resting units/orientation, the effective output data rate
(how often a *fresh* sample lands), and the raw poll ceiling.

Run one-shot over USB (does NOT overwrite the flashed creature):
    mpremote connect /dev/ttyACM0 run test/CORES3/calibrate_imu/main.py

Or flash it as main.py (gives the on-LCD live readout too):
    flash test/CORES3/calibrate_imu

The numeric phases (REST/ODR/RATE) print to serial FIRST, with no Widgets calls
and no long idle sleeps — on the CoreS3's native USB-CDC, M5.begin() + display
init + a multi-second sleep under `mpremote run` can glitch the link and reset
the board, dropping the capture. Keeping serial fed and the display untouched
until the numbers are out sidesteps that. The LCD summary + live loop come last.

Measured reference (this unit, lying still on a desk, 2026-06-05):
    REST  accel mean g  : x=+0.004 y=-0.005 z=+1.001   |a|=1.001  (gravity +z)
          accel std  g  : ~0.0006                       (very low noise)
          gyro  bias dps: x=+0.04 y=-0.07 z=+0.05
          gyro  std  dps: ~0.06-0.10                    (noise floor)
    ODR   new-sample    : ~95 Hz   (BMI270 default 100 Hz ODR)
    RATE  accel poll    : ~15.6 kHz ; accel+gyro ~7.9 kHz ; +M5.update() ~6.4 kHz
    => distinct IMU data caps at ~100 Hz; poll rate is never the bottleneck.

Units (BMI270, confirmed in test/CORES3/API.md):
    getAccel() -> (x,y,z) g      (1 g ≈ 9.81 m/s²); at rest one axis ≈ ±1.0
    getGyro()  -> (x,y,z) deg/s  ; at rest ≈ 0 with small bias
    getMag()   -> (x,y,z) µT     (raw; the StickS3 has no mag)
"""

import M5
import time

M5.begin()
imu = M5.Imu
AXES = ("x", "y", "z")
IMU_NAMES = {0: "NULL", 1: "UNKNOWN", 2: "SH200Q",
             3: "MPU6050", 4: "MPU6886", 5: "MPU9250", 6: "BMI270"}

chip = IMU_NAMES.get(imu.getType(), str(imu.getType()))
print("=" * 56)
print("calibrate_imu  chip={} type={} enabled={}".format(chip, imu.getType(), imu.isEnabled()))

# Guard: the "IMU stuck reading all zeros" gotcha (see test/STICKS3/API.md).
if imu.getAccel() == (0.0, 0.0, 0.0) and imu.getGyro() == (0.0, 0.0, 0.0):
    print("!! accel AND gyro read all-zeros — IMU data path is dead.")
    print("!! Power-cycle the board (hold power ~6s) and retry.")
    raise SystemExit


def mean_std(v):
    n = len(v)
    m = sum(v) / n
    return m, (sum((q - m) ** 2 for q in v) / n) ** 0.5


# ── phase 1: REST (hold still) ───────────────────────────────────────────────
REST_N = 500
print("\n-- REST: keep the device still ({} samples) --".format(REST_N))
xs, ys, zs, gxs, gys, gzs = [], [], [], [], [], []
for _ in range(REST_N):
    x, y, z = imu.getAccel()
    ux, uy, uz = imu.getGyro()
    xs.append(x); ys.append(y); zs.append(z)
    gxs.append(ux); gys.append(uy); gzs.append(uz)

amx, asx = mean_std(xs); amy, asy = mean_std(ys); amz, asz = mean_std(zs)
gmx, gsx = mean_std(gxs); gmy, gsy = mean_std(gys); gmz, gsz = mean_std(gzs)
amag = (amx * amx + amy * amy + amz * amz) ** 0.5
gi = max(range(3), key=lambda i: abs((amx, amy, amz)[i]))
gsign = "+" if (amx, amy, amz)[gi] >= 0 else "-"
print("  accel mean g  : x=%+.4f y=%+.4f z=%+.4f" % (amx, amy, amz))
print("  accel std  g  : x=%.4f y=%.4f z=%.4f" % (asx, asy, asz))
print("  |accel| g     : %.4f   (expect ~1.000)" % amag)
print("  gravity axis  : %s%s   (sensor reads +1g opposing gravity)" % (gsign, AXES[gi]))
print("  gyro  bias dps: x=%+.3f y=%+.3f z=%+.3f" % (gmx, gmy, gmz))
print("  gyro  std  dps: x=%.3f y=%.3f z=%.3f   <- noise floor" % (gsx, gsy, gsz))

# ── phase 2: ODR (effective new-sample rate) ─────────────────────────────────
# Poll flat-out and count how often the accel value actually changes — that is
# the real "max update frequency", independent of how fast we can poll.
print("\n-- ODR: effective new-sample rate --")
DUR = 2000
t0 = time.ticks_ms()
polls = 0
changes = 0
last = imu.getAccel()
while time.ticks_diff(time.ticks_ms(), t0) < DUR:
    v = imu.getAccel()
    polls += 1
    if v != last:
        changes += 1
        last = v
el = time.ticks_diff(time.ticks_ms(), t0) / 1000.0
odr = changes / el
print("  poll rate     : %.0f Hz (%d polls / %.2fs)" % (polls / el, polls, el))
print("  NEW-sample    : %.1f Hz (%d changes)  <- effective IMU ODR" % (odr, changes))
print("  polls/sample  : %.1f" % (polls / max(1, changes)))

# ── phase 3: RATE (poll ceiling) ─────────────────────────────────────────────
print("\n-- RATE: max polling frequency --")


def bench(label, fn, n):
    t = time.ticks_us()
    for _ in range(n):
        fn()
    d = time.ticks_diff(time.ticks_us(), t)
    print("  %-22s %8.0f Hz  (%6.1f us/read)" % (label, n * 1e6 / d, d / n))


bench("accel only", lambda: imu.getAccel(), 3000)
bench("accel + gyro", lambda: (imu.getAccel(), imu.getGyro()), 3000)
bench("accel + gyro + mag", lambda: (imu.getAccel(), imu.getGyro(), imu.getMag()), 3000)
bench("a+g+M5.update()", lambda: (M5.update(), imu.getAccel(), imu.getGyro()), 1500)
print("\n  -> distinct IMU data caps at ~%.0f Hz (ODR); poll rate is never the limit." % odr)
print("  -> synthetic-imu should target fps <= %.0f; seed loop uses sleep_ms(33)=30 Hz." % odr)

# ── phase 4: LIVE on-LCD readout (interactive) ───────────────────────────────
# Only now do we touch the display. If `mpremote run` glitches here, the numbers
# above are already captured.
print("\n-- LIVE: move it around; Ctrl-C to stop --")
W = M5.Widgets
F = W.FONTS
W.fillScreen(0x000000)
W.Label("calibrate_imu  ODR=%.0fHz" % odr, 8, 4, 1.0, 0xFFFF66, 0x000000, F.DejaVu18)
la = W.Label("", 8, 40, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)
lg = W.Label("", 8, 80, 1.0, 0xAACCFF, 0x000000, F.DejaVu24)
lm = W.Label("", 8, 120, 1.0, 0x88FF88, 0x000000, F.DejaVu18)
while True:
    M5.update()
    x, y, z = imu.getAccel()
    ux, uy, uz = imu.getGyro()
    mx, my, mz = imu.getMag()
    la.setText("a %+.2f %+.2f %+.2f" % (x, y, z))
    lg.setText("g %+5.0f %+5.0f %+5.0f" % (ux, uy, uz))
    lm.setText("m %+5.0f %+5.0f %+5.0f" % (mx, my, mz))
    time.sleep_ms(100)
