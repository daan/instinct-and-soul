"""
test_imu/main.py — IMU probe for the M5Stack CORES3.

Flash with:
    flash test/CORES3/test_imu

What it does:
- Initializes M5.
- Reads accel/gyro/mag from M5.Imu at ~10 Hz.
- Prints to serial and updates 9 labels on the LCD (no flicker — labels are
  created once and refreshed via setText).

Probed API on a live CORES3 (BMI270, IMU_TYPE=6):
    M5.Imu.isEnabled()           -> bool
    M5.Imu.getType()             -> int (compare with M5.Imu.IMU_TYPE.*)
    M5.Imu.getAccel()            -> (x, y, z) tuple of floats, units = g
    M5.Imu.getGyro()             -> (x, y, z) tuple of floats, units = deg/s
    M5.Imu.getMag()              -> (x, y, z) tuple of floats, magnetometer
"""

import M5
import time

M5.begin()

W = M5.Widgets
F = W.FONTS

IMU_NAMES = {
    0: "NULL", 1: "UNKNOWN", 2: "SH200Q",
    3: "MPU6050", 4: "MPU6886", 5: "MPU9250", 6: "BMI270",
}

W.fillScreen(0x000000)
W.Label("test_imu  CORES3", 8, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)

chip = IMU_NAMES.get(M5.Imu.getType(), str(M5.Imu.getType()))
W.Label("chip: {}   enabled: {}".format(chip, M5.Imu.isEnabled()),
        8, 36, 1.0, 0x66ff66, 0x000000, F.DejaVu18)

W.Label("accel (g)",   8, 64,  1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_ax = W.Label("", 16, 86,  1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_ay = W.Label("", 16, 106, 1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_az = W.Label("", 16, 126, 1.0, 0xffffff, 0x000000, F.DejaVu18)

W.Label("gyro (deg/s)", 170, 64,  1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_gx = W.Label("", 178, 86,  1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_gy = W.Label("", 178, 106, 1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_gz = W.Label("", 178, 126, 1.0, 0xffffff, 0x000000, F.DejaVu18)

W.Label("mag",          8,  154, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_mx = W.Label("", 16, 176, 1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_my = W.Label("", 16, 196, 1.0, 0xffffff, 0x000000, F.DejaVu18)
lbl_mz = W.Label("", 16, 216, 1.0, 0xffffff, 0x000000, F.DejaVu18)

print("test_imu: chip={} type={} enabled={}".format(chip, M5.Imu.getType(), M5.Imu.isEnabled()))

while True:
    M5.update()
    ax, ay, az = M5.Imu.getAccel()
    gx, gy, gz = M5.Imu.getGyro()
    mx, my, mz = M5.Imu.getMag()

    lbl_ax.setText("x {:+.3f}".format(ax))
    lbl_ay.setText("y {:+.3f}".format(ay))
    lbl_az.setText("z {:+.3f}".format(az))
    lbl_gx.setText("x {:+7.1f}".format(gx))
    lbl_gy.setText("y {:+7.1f}".format(gy))
    lbl_gz.setText("z {:+7.1f}".format(gz))
    lbl_mx.setText("x {:+7.1f}".format(mx))
    lbl_my.setText("y {:+7.1f}".format(my))
    lbl_mz.setText("z {:+7.1f}".format(mz))

    print("a=({:+.3f},{:+.3f},{:+.3f})  g=({:+.1f},{:+.1f},{:+.1f})  m=({:+.1f},{:+.1f},{:+.1f})".format(
        ax, ay, az, gx, gy, gz, mx, my, mz
    ))

    time.sleep_ms(100)
