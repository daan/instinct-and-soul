"""
test_imu/main.py — IMU probe for the M5StickS3.

Flash with:
    flash test/STICKS3/test_imu

Same idea as test/CORES3/test_imu but laid out for the StickS3's 135 × 240
portrait LCD. Reads accel/gyro/mag from M5.Imu at ~10 Hz, prints to serial,
and updates 9 labels on the screen via setText (no flicker).

Probed API on this board (BMI270, IMU_TYPE=6):
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
W.Label("test_imu", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu18)
W.Label("STICKS3",  4, 24, 1.0, 0x66ff66, 0x000000, F.DejaVu12)

chip = IMU_NAMES.get(M5.Imu.getType(), str(M5.Imu.getType()))
W.Label(chip, 4, 40, 1.0, 0xaaccff, 0x000000, F.DejaVu12)

# Section labels
W.Label("accel (g)",   4, 60, 1.0, 0xaaccff, 0x000000, F.DejaVu12)
lbl_ax = W.Label("", 4, 76,  1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_ay = W.Label("", 4, 90,  1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_az = W.Label("", 4, 104, 1.0, 0xffffff, 0x000000, F.DejaVu12)

W.Label("gyro (deg/s)", 4, 122, 1.0, 0xaaccff, 0x000000, F.DejaVu12)
lbl_gx = W.Label("", 4, 138, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_gy = W.Label("", 4, 152, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_gz = W.Label("", 4, 166, 1.0, 0xffffff, 0x000000, F.DejaVu12)

W.Label("mag",   4, 184, 1.0, 0xaaccff, 0x000000, F.DejaVu12)
lbl_mx = W.Label("", 4, 200, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_my = W.Label("", 4, 214, 1.0, 0xffffff, 0x000000, F.DejaVu12)
lbl_mz = W.Label("", 4, 228, 1.0, 0xffffff, 0x000000, F.DejaVu12)

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
