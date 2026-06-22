async def run():
    # Sonify wrist motion through the MIDI voice. Tracking, not triggering:
    # while the arm is moving, a soft mallet note sounds, its pitch and
    # loudness following the gesture; at rest the creature is silent.
    CH = 0
    Synth.program(CH, 11)  # GM 11 = Vibraphone — soft attack, sits inside a room

    # A small pentatonic-ish set so consecutive notes stay consonant.
    SCALE = [57, 60, 62, 64, 67, 69, 72, 76]

    WINDOW = 30          # ~1 s of samples at the 33 ms loop
    energies = []
    last_note = None

    while True:
        ax, ay, az = Imu.getAccel()
        # Deviation from gravity: how much the arm accelerates beyond being held.
        energy = abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)

        energies.append(energy)
        if len(energies) > WINDOW:
            energies.pop(0)

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

        # Report activity for the soul's reflection (~1 s cadence).
        if len(energies) == WINDOW:
            mean_e = sum(energies) / WINDOW
            send("energy mean={:.4f} now={:.4f}".format(mean_e, energy))
            energies.clear()

        await asyncio.sleep_ms(33)
