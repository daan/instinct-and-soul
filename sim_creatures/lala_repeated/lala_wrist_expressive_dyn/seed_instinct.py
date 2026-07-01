async def run():
    # A simple starting point, not a finished idea: make sound from how the body
    # moves, keep a short memory of recent motion, and report an honest summary
    # now and then so I can reflect on a stretch of time. Grow this however the
    # dance asks.
    CH = 0
    Synth.program(CH, 12)            # marimba to start — struck, not a soft pad;
                                     # the voice and its hardness are mine to grow

    WIN = 200                        # ~6 s of samples in Mem
    last_note = None
    n = 0

    while True:
        ax, ay, az = Imu.getAccel()
        energy = abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)
        Mem.push("energy", round(energy, 4), maxlen=WIN)

        # match the body's intensity: use the FULL loudness range — gentle motion
        # quiet, a hard/fast gesture loud and short-struck — silent when still.
        if energy > 0.06:
            note = 60 + min(24, int(energy * 12))
            if note != last_note:
                # velocity spans the whole range (to 127); sharper energy -> shorter, harder hit
                vel = max(20, min(127, int(20 + energy * 280)))
                dur = max(90, 280 - int(energy * 200))
                Synth.note(CH, note, dur, velocity=vel)
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
