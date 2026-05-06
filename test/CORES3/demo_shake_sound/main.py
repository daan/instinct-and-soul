"""
demo_shake_sound/main.py — shake-driven sound demo for CORES3.

Combines what test_imu and test_speaker established into one experience:
  - Read accelerometer, compute deviation from rest (gravity).
  - Map motion intensity to tone frequency (more shake → higher pitch).
  - Below threshold = silent, above = continuous tracking tone.
  - Volume 32/255, a quarter of the test_speaker probe.

Flash with:
    flash test/CORES3/demo_shake_sound
"""

import M5
import time
import math

M5.begin()
M5.Speaker.begin()
M5.Speaker.setVolume(32)

W = M5.Widgets
F = W.FONTS

W.fillScreen(0x000000)
W.Label("shake to make sound", 8, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)
W.Label("volume 32/255", 8, 36, 1.0, 0x66ff66, 0x000000, F.DejaVu18)

W.Label("motion:", 8, 90, 1.0, 0xaaccff, 0x000000, F.DejaVu24)
lbl_motion = W.Label("0.000", 140, 90, 1.0, 0xffff66, 0x000000, F.DejaVu40)

W.Label("tone:", 8, 160, 1.0, 0xaaccff, 0x000000, F.DejaVu24)
lbl_tone = W.Label("---", 140, 160, 1.0, 0xffaa66, 0x000000, F.DejaVu40)

THRESHOLD  = 0.15   # g — anything quieter than this is "still"
MOTION_MAX = 2.0    # g — saturate the tone mapping above this
FREQ_MIN   = 200
FREQ_MAX   = 1500
TONE_MS    = 80     # play length per call; we recall every 50 ms while shaking
LOOP_MS    = 50

print("demo_shake_sound: threshold={} g  freq={}–{} Hz".format(THRESHOLD, FREQ_MIN, FREQ_MAX))

while True:
    M5.update()
    ax, ay, az = M5.Imu.getAccel()
    # deviation from rest (gravity is +1 g on z when face-up)
    motion = math.sqrt(ax * ax + ay * ay + (az - 1.0) ** 2)

    lbl_motion.setText("{:.3f}".format(motion))

    if motion > THRESHOLD:
        m = min(motion, MOTION_MAX)
        span = MOTION_MAX - THRESHOLD
        freq = FREQ_MIN + int((m - THRESHOLD) / span * (FREQ_MAX - FREQ_MIN))
        M5.Speaker.tone(freq, TONE_MS)
        lbl_tone.setText("{:4d} Hz".format(freq))
        print("motion={:.3f}  freq={}".format(motion, freq))
    else:
        lbl_tone.setText("---  ")

    time.sleep_ms(LOOP_MS)
