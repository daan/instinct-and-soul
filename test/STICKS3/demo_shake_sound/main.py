"""
demo_shake_sound/main.py — shake-driven sound for the M5StickS3.

Same idea as test/CORES3/demo_shake_sound but adapted:
  - StickS3 speaker needs the looped tone() pattern (single call doesn't sustain)
  - Layout for 135 x 240 portrait LCD
  - Volume 32 / 255 (gentle, same as CORES3 demo)

Map: deviation from rest (gravity) → tone frequency. More shake = higher pitch.
Below threshold = silent.

Flash with:
    flash test/STICKS3/demo_shake_sound
"""

import M5
import math
import time

M5.begin()
M5.Speaker.begin()
M5.Speaker.setVolume(32)

W = M5.Widgets
F = W.FONTS

W.fillScreen(0x000000)
W.Label("shake -> sound", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu18)
W.Label("vol 32 / 255", 4, 24, 1.0, 0x66ff66, 0x000000, F.DejaVu12)

W.Label("motion", 4, 60, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_motion = W.Label("0.000", 4, 84, 1.0, 0xffff66, 0x000000, F.DejaVu24)

W.Label("tone", 4, 130, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_tone = W.Label("---", 4, 154, 1.0, 0xffaa66, 0x000000, F.DejaVu24)

THRESHOLD  = 0.15
MOTION_MAX = 2.0
FREQ_MIN   = 200
FREQ_MAX   = 1500

print("demo_shake_sound: threshold={} g  freq={}-{} Hz".format(THRESHOLD, FREQ_MIN, FREQ_MAX))

while True:
    M5.update()
    ax, ay, az = M5.Imu.getAccel()
    motion = math.sqrt(ax * ax + ay * ay + (az - 1.0) ** 2)

    lbl_motion.setText("{:.3f}".format(motion))

    if motion > THRESHOLD:
        m = min(motion, MOTION_MAX)
        span = MOTION_MAX - THRESHOLD
        freq = FREQ_MIN + int((m - THRESHOLD) / span * (FREQ_MAX - FREQ_MIN))
        # StickS3 needs a tight loop to sustain the tone — issue a short burst per frame
        M5.Speaker.tone(freq, 80)
        lbl_tone.setText("{:4d} Hz".format(freq))
        print("motion={:.3f}  freq={}".format(motion, freq))
    else:
        lbl_tone.setText("---  ")

    time.sleep_ms(50)
