import M5
from M5 import *
import time
import math

M5.begin()
Speaker.begin()
Speaker.setVolume(200)

# Show something on screen
Widgets.fillScreen(0x000000)
label = Widgets.Label("wave me!", 20, 50, 1.0, 0xFFFFFF, 0x000000, Widgets.FONTS.DejaVu18)

GRAVITY = 1.0       # baseline g when still
THRESHOLD = 1.5     # g above which we react
MIN_FREQ = 200
MAX_FREQ = 2000

def accel_magnitude(x, y, z):
    return math.sqrt(x*x + y*y + z*z)

def map_to_freq(magnitude):
    # clamp between threshold and 4g
    m = max(THRESHOLD, min(magnitude, 4.0))
    ratio = (m - THRESHOLD) / (4.0 - THRESHOLD)
    return int(MIN_FREQ + ratio * (MAX_FREQ - MIN_FREQ))

while True:
    M5.update()
    x, y, z = Imu.getAccel()
    mag = accel_magnitude(x, y, z)

    if mag > THRESHOLD:
        freq = map_to_freq(mag)
        Speaker.tone(freq, 80)   # 80ms burst
        label.setText(str(freq) + "Hz")
    else:
        label.setText("still...")

    time.sleep_ms(50)


