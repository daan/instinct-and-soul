"""
test_grove_vibration/main.py — Grove vibration motor on CORES3 Port A.

CORES3 Grove ports (per M5Stack docs):
  Port A (red)   I2C / Generic — GPIO1 (yellow / SDA), GPIO2 (white / SCL)
  Port B (black) IO            — GPIO8, GPIO9
  Port C (blue)  UART          — GPIO17 (TX), GPIO18 (RX)

A single-pin Grove vibration motor uses one of Port A's two signal pins.
Most Grove modules expect the signal on the yellow wire (= GPIO1 = SDA), but
the original M5Stack vibration unit puts it on the white wire (= GPIO2 = SCL).

This sketch defaults to GPIO2. If you hear no buzz, flip MOTOR_PIN below to 1
and re-flash.

Flash with:
    flash test/CORES3/test_grove_vibration

What it does:
- Sweeps PWM duty 0 -> 1023 in steps of 25, holding each step ~150 ms.
- Holds peak for 1 s, then off for 2 s, then repeats.
- Shows current duty on the LCD and prints to serial.
"""

import M5
from machine import Pin, PWM
import time

M5.begin()

MOTOR_PIN = 1          # Port A signal (yellow / SDA)
PWM_FREQ  = 5000       # Hz; vibration motors don't care above audible

motor = PWM(Pin(MOTOR_PIN), freq=PWM_FREQ, duty=0)

W = M5.Widgets
F = W.FONTS
W.fillScreen(0x000000)
W.Label("test_grove_vibration", 8, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)
W.Label("Port A  GPIO{}  {} Hz".format(MOTOR_PIN, PWM_FREQ),
        8, 36, 1.0, 0x66ff66, 0x000000, F.DejaVu18)

W.Label("duty", 8, 90, 1.0, 0xaaccff, 0x000000, F.DejaVu24)
lbl_duty = W.Label("0", 80, 90, 1.0, 0xffff66, 0x000000, F.DejaVu56)

W.Label("phase", 8, 180, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_phase = W.Label("idle", 100, 180, 1.0, 0xffffff, 0x000000, F.DejaVu18)

print("test_grove_vibration: pin={} freq={}Hz".format(MOTOR_PIN, PWM_FREQ))

while True:
    # sweep up
    lbl_phase.setText("sweep")
    for d in range(0, 1024, 25):
        motor.duty(d)
        lbl_duty.setText("{:4d}".format(d))
        print("duty={}".format(d))
        time.sleep_ms(150)
    # hold peak
    motor.duty(1023)
    lbl_duty.setText("1023")
    lbl_phase.setText("hold ")
    print("hold peak")
    time.sleep(1)
    # off
    motor.duty(0)
    lbl_duty.setText("   0")
    lbl_phase.setText("off  ")
    print("off")
    time.sleep(2)
