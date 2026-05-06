"""
test_speaker/main.py — speaker probe for CORES3.

Flash with:
    flash test/CORES3/test_speaker

What it does:
- Plays an ascending chirp (200 Hz -> 2000 Hz, 100 Hz steps).
- Shows the current frequency on the LCD.
- Re-runs the chirp every 5 seconds.

If you hear no sound:
- Confirm Speaker.isEnabled() is True (printed on screen).
- The CORES3 amplifier idles audibly when active. Speaker.end() silences it.
- Volume is 0..255. We use 128 here (loud enough to hear, not piercing).

Probed API:
    M5.Speaker.begin()                  -> initialize
    M5.Speaker.end()                    -> deinit (silences amp idle)
    M5.Speaker.setVolume(0..255)        -> master volume
    M5.Speaker.tone(freq, ms)           -> play tone for ms; returns immediately
    M5.Speaker.stop()                   -> stop current playback
    M5.Speaker.isPlaying()              -> bool
    M5.Speaker.isEnabled()              -> bool

Volume getters worth noting:
    getVolume()             -> int (0..255)
    getVolumePercentage()   -> float; returned 0.0 in our probe even with
                               getVolume()=64 — likely tracks per-channel mix
                               level, not master setting.
"""

import M5
import time

M5.begin()
M5.Speaker.begin()
M5.Speaker.setVolume(128)

W = M5.Widgets
F = W.FONTS

W.fillScreen(0x000000)
W.Label("test_speaker  CORES3", 8, 4, 1.0, 0xFFFFFF, 0x000000, F.DejaVu24)

W.Label("enabled:",  8, 40, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
W.Label(str(M5.Speaker.isEnabled()), 110, 40, 1.0, 0xffffff, 0x000000, F.DejaVu18)

W.Label("volume:",   8, 64, 1.0, 0xaaccff, 0x000000, F.DejaVu18)
W.Label("{} / 255".format(M5.Speaker.getVolume()), 110, 64, 1.0, 0xffffff, 0x000000, F.DejaVu18)

W.Label("freq:",   8, 110, 1.5, 0xaaccff, 0x000000, F.DejaVu24)
lbl_freq = W.Label("", 100, 110, 1.5, 0xffff66, 0x000000, F.DejaVu40)

print("test_speaker: starting (volume {} / 255)".format(M5.Speaker.getVolume()))

while True:
    for freq in range(200, 2100, 100):
        lbl_freq.setText("{:4d} Hz".format(freq))
        print("tone {} Hz".format(freq))
        M5.Speaker.tone(freq, 100)
        # tone() returns immediately; sleep covers the playback window
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 110:
            M5.update()
            time.sleep_ms(10)

    M5.Speaker.stop()
    lbl_freq.setText("paused")
    print("paused")
    time.sleep(2)
