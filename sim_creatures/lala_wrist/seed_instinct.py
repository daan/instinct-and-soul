async def run():
    # A simple starting point, not a finished idea: make sound from how the body
    # moves, keep a short memory of recent motion, and report an honest summary
    # now and then so I can reflect on a stretch of time. Grow this however the
    # dance asks.
    CH = 0
    Synth.program(CH, 11)            # vibraphone to start

    WIN = 200                        # ~6 s of samples in Mem
    last_note = None
    n = 0

    while True:
        ax, ay, az = Imu.getAccel()
        energy = abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)
        Mem.push("energy", round(energy, 4), maxlen=WIN)

        # sound follows motion: higher and louder as the body moves more, silent
        # when it's still. Re-strike only on change, not every tick.
        if energy > 0.06:
            note = 60 + min(24, int(energy * 12))
            if note != last_note:
                Synth.note(CH, note, 220,
                           velocity=max(30, min(120, int(40 + energy * 200))))
                last_note = note
        else:
            last_note = None

        # honest windowed summary — plain features, no guessed tempo. What the
        # motion's rhythm is (if any) is mine to work out, not to assume here.
        n += 1
        if n % WIN == 0:
            buf = Mem.recent("energy")
            if buf:
                mean_e = sum(buf) / len(buf)
                peak_e = max(buf)
                send("window {:.0f}s: mean_e={:.3f} peak_e={:.3f}".format(
                    len(buf) * 0.03, mean_e, peak_e))

        await asyncio.sleep_ms(30)
