# screen_test — a deterministic, IMU-independent display + audio test pattern.
#
# Its job is to debug the *renderer* and audio sync, not to behave interestingly.
# Every primitive is drawn at a known place against the real panel size, so any
# geometry / scale / colour / arc-angle bug is visible by eye. One bar sweeps
# top->bottom and the tone glides with it, so the timeline scrubber and audio
# sync are verifiable too.
#
# Expected picture (135x240 sticks3 / 320x240 cores3):
#   - white 2px border framing the whole panel
#   - corner squares: TL red, TR green, BL blue, BR yellow
#   - R/G/B/W colour bars across the top
#   - grey center cross; cyan circle at center; magenta triangle below it;
#     orange arc (0..120 deg) ringing the circle; green diagonal corner-to-corner
#   - a white horizontal bar sweeping top->bottom every PERIOD_MS

PERIOD_MS = 3000.0


async def run():
    W = M5.Display.width()
    H = M5.Display.height()
    cx, cy = W // 2, H // 2
    Speaker.begin()
    Speaker.setVolume(180)

    frame = 0
    t = 0.0
    while True:
        M5.Display.fillScreen(0x000000)

        # border frame (white, 2px)
        M5.Display.fillRect(0, 0, W, 2, 0xffffff)
        M5.Display.fillRect(0, H - 2, W, 2, 0xffffff)
        M5.Display.fillRect(0, 0, 2, H, 0xffffff)
        M5.Display.fillRect(W - 2, 0, 2, H, 0xffffff)

        # corner markers (orientation check)
        M5.Display.fillRect(0, 0, 10, 10, 0xff0000)            # TL red
        M5.Display.fillRect(W - 10, 0, 10, 10, 0x00ff00)       # TR green
        M5.Display.fillRect(0, H - 10, 10, 10, 0x0000ff)       # BL blue
        M5.Display.fillRect(W - 10, H - 10, 10, 10, 0xffff00)  # BR yellow

        # R/G/B/W colour bars across the top
        bw = W // 4
        M5.Display.fillRect(0 * bw, 14, bw, 16, 0xff0000)
        M5.Display.fillRect(1 * bw, 14, bw, 16, 0x00ff00)
        M5.Display.fillRect(2 * bw, 14, bw, 16, 0x0000ff)
        M5.Display.fillRect(3 * bw, 14, W - 3 * bw, 16, 0xffffff)

        # center cross
        M5.Display.fillRect(cx - 1, 36, 2, H - 72, 0x444444)
        M5.Display.fillRect(2, cy - 1, W - 4, 2, 0x444444)

        # shape primitives
        M5.Display.fillCircle(cx, cy, 18, 0x00cccc)
        M5.Display.fillTriangle(cx, cy + 40, cx - 20, cy + 74, cx + 20, cy + 74, 0xcc00cc)
        M5.Display.fillArc(cx, cy, 26, 34, 0, 120, 0xffaa00)
        M5.Display.drawLine(4, 40, W - 5, H - 40, 0x66ff66)

        # moving element: a bar sweeping top->bottom over PERIOD_MS
        phase = (t % PERIOD_MS) / PERIOD_MS
        y = int(phase * (H - 6)) + 3
        M5.Display.fillRect(2, y - 1, W - 4, 3, 0xffffff)

        # audio: glide the tone with the sweep so sync is audible
        Speaker.tone(220 + phase * 660, 80)

        M5.update()
        frame += 1
        t += 33.0
        await asyncio.sleep_ms(33)
