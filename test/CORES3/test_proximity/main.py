"""
test_proximity/main.py — ALS (ambient light + proximity) probe for CORES3.

The CORES3 has an LTR-553ALS-WA combo sensor exposed via M5.Als.

Flash with:
    flash test/CORES3/test_proximity

What it does:
- Reads ambient light + proximity at ~10 Hz.
- Prints raw counts to serial.
- Shows live values + auto-scaling bar graphs on the LCD.
- Tracks a running max for each so the bar scaling adapts.

Wave a hand near the front face to see proximity climb. Cover the sensor with
your finger to see ambient light drop.

Probed API:
    M5.Als.getLightSensorData()       -> int   (raw counts)
    M5.Als.getProximitySensorData()   -> int   (raw counts; ~0 when far)
"""

import M5
import time

M5.begin()

W = M5.Widgets
F = W.FONTS

W.fillScreen(0x000000)
W.Label("test_proximity  CORES3", 8, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)

W.Label("light",       8, 50,  1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_light = W.Label("",          80, 50,  1.0, 0xffffff, 0x000000, F.DejaVu18)
W.Label("proximity",   8, 130, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_prox  = W.Label("",          120, 130, 1.0, 0xffffff, 0x000000, F.DejaVu18)

# Bar graph rectangles. Track max-seen for auto-scaling.
BAR_X = 8
BAR_W = 304
BAR_H = 20
LIGHT_BAR_Y = 80
PROX_BAR_Y  = 160

# Outline rectangles (drawn once)
W.Rectangle(BAR_X, LIGHT_BAR_Y, BAR_W, BAR_H, 0x333333, 0x333333)
W.Rectangle(BAR_X, PROX_BAR_Y,  BAR_W, BAR_H, 0x333333, 0x333333)

# Filled bars (we shrink/grow these by recreating)
light_fill = W.Rectangle(BAR_X, LIGHT_BAR_Y, 1, BAR_H, 0xffaa00, 0xffaa00)
prox_fill  = W.Rectangle(BAR_X, PROX_BAR_Y,  1, BAR_H, 0x00ccff, 0x00ccff)

light_max = 1
prox_max = 1

print("test_proximity: starting")

while True:
    M5.update()
    light = M5.Als.getLightSensorData()
    prox  = M5.Als.getProximitySensorData()

    if light > light_max:
        light_max = light
    if prox > prox_max:
        prox_max = prox

    light_w = max(1, int(BAR_W * light / light_max))
    prox_w  = max(1, int(BAR_W * prox  / prox_max))

    lbl_light.setText("{:5d}  (max {:d})".format(light, light_max))
    lbl_prox.setText( "{:5d}  (max {:d})".format(prox, prox_max))

    # Re-draw filled bars (Rectangle has no setSize, recreate)
    M5.Display.fillRect(BAR_X, LIGHT_BAR_Y, BAR_W, BAR_H, 0x222222)
    M5.Display.fillRect(BAR_X, LIGHT_BAR_Y, light_w, BAR_H, 0xffaa00)
    M5.Display.fillRect(BAR_X, PROX_BAR_Y,  BAR_W, BAR_H, 0x222222)
    M5.Display.fillRect(BAR_X, PROX_BAR_Y,  prox_w,  BAR_H, 0x00ccff)

    print("light={:5d}  prox={:5d}".format(light, prox))
    time.sleep_ms(100)
