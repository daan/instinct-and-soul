async def run():
    # Sonify wrist motion through the MIDI voice. Tracking, not triggering:
    # while the arm is moving, a soft mallet note sounds, its pitch and
    # loudness following the gesture; at rest the creature is silent.
    CH = 0
    Synth.program(CH, 11)  # GM 11 = Vibraphone — soft attack, sits inside a room

    # A small pentatonic-ish set so consecutive notes stay consonant.
    SCALE = [57, 60, 62, 64, 67, 69, 72, 76]

    DT = 0.033           # loop period (s)
    WIN = 300            # ~10 s of samples kept in Mem
    last_note = None
    n = 0
    last_report = 0

    while True:
        ax, ay, az = Imu.getAccel()
        # Deviation from gravity: how much the arm accelerates beyond being held.
        energy = abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)

        # Persist the motion stream in Mem so it survives my reflections and I
        # can hear the gesture's shape over time, not just this instant.
        Mem.push("energy", round(energy, 4), maxlen=WIN)

        # Track: map the gesture's intensity onto pitch + velocity. Only
        # re-strike when the pitch changes, so held motion phrases rather
        # than machine-guns a single note.
        if energy > 0.06:
            idx = min(len(SCALE) - 1, int(energy * 10))
            note = SCALE[idx]
            vel = max(30, min(120, int(35 + energy * 220)))
            if note != last_note:
                Synth.note(CH, note, 220, velocity=vel)
                last_note = note
        else:
            last_note = None

        # Every ~10 s, look back over the buffered window and report its SHAPE,
        # not a single reading: mean/peak energy and a crude tempo (how many
        # energy peaks per minute). Sending only here paces my reflections — the
        # soul thinks once per window, on a time-series, instead of every tick.
        n += 1
        if n - last_report >= WIN:
            last_report = n
            buf = Mem.recent("energy")
            if buf:
                mean_e = sum(buf) / len(buf)
                peak_e = max(buf)
                # crude beat count: local maxima above the window mean
                beats = 0
                for i in range(1, len(buf) - 1):
                    if buf[i] > mean_e and buf[i] >= buf[i - 1] and buf[i] > buf[i + 1]:
                        beats += 1
                secs = len(buf) * DT
                bpm = beats / secs * 60.0 if secs > 0 else 0.0
                send("window {:.0f}s mean={:.3f} peak={:.3f} peaks={} ~{:.0f}/min".format(
                    secs, mean_e, peak_e, beats, bpm))

        await asyncio.sleep_ms(33)
