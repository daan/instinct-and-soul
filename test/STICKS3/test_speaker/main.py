"""
test_speaker/main.py — speaker probe for the M5StickS3.

Flash with:
    flash test/STICKS3/test_speaker

Confirms the StickS3 speaker gotcha: a single Speaker.tone() call does not
sustain — tones must be driven in a tight loop with M5.update() ticking the
audio engine. (CORES3 doesn't need this.)

Plays an ascending chirp (200 -> 2000 Hz, 100 Hz steps), shows the current
frequency on the LCD, repeats every 5 s.

Probed API:
    M5.Speaker.begin() / end()
    M5.Speaker.setVolume(0..255)
    M5.Speaker.tone(freq, ms)        # short burst; needs to be re-issued
    M5.Speaker.stop()
"""

import M5
import time

M5.begin()
M5.Speaker.begin()
M5.Speaker.setVolume(64)

W = M5.Widgets
F = W.FONTS

W.fillScreen(0x000000)
W.Label("test_speaker", 4, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu18)
W.Label("STICKS3", 4, 24, 1.0, 0x66ff66, 0x000000, F.DejaVu12)
W.Label("vol {} / 255".format(M5.Speaker.getVolume()),
        4, 40, 1.0, 0xaaccff, 0x000000, F.DejaVu12)

W.Label("freq", 4, 80, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
lbl_freq = W.Label("", 4, 104, 1.0, 0xffff66, 0x000000, F.DejaVu24)

print("test_speaker: starting (vol {} / 255)".format(M5.Speaker.getVolume()))


def play_tone(freq, ms):
    """Drive a tone for `ms` by issuing short bursts in a tight loop."""
    loops = max(1, ms // 50)
    for _ in range(loops):
        M5.Speaker.tone(freq, 80)
        M5.update()
        time.sleep_ms(50)


while True:
    for freq in range(200, 2100, 100):
        lbl_freq.setText("{:4d} Hz".format(freq))
        print("tone {} Hz".format(freq))
        play_tone(freq, 200)
    M5.Speaker.stop()
    lbl_freq.setText("paused")
    print("paused")
    time.sleep(2)
