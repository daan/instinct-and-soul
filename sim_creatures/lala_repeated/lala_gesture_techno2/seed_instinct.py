async def run():
    # A warm starting point — a continuous electronic soundscape that follows the
    # body: sustained pads that swell and open with how much it moves, and a lead
    # that traces the ARC of the gesture as a run of notes (a hand running up and
    # down a keyboard as the arm swings). No percussion. Grow it as the body asks.
    CH_PAD = 0
    CH_PAD2 = 2
    CH_LEAD = 1
    Synth.program(CH_PAD, 88)      # warm pad
    Synth.program(CH_PAD2, 94)     # halo pad
    Synth.program(CH_LEAD, 81)     # saw lead
    Synth.control_change(CH_LEAD, 65, 110)   # portamento on — glide between notes

    pose = Calc.Madgwick(beta=0.1)
    vol_euro = Calc.OneEuro(min_cutoff=0.3, beta=0.1)
    baseline = Calc.Running(n=120)

    SCALE = [48, 51, 53, 55, 58, 60, 63, 65, 67, 70, 72, 75, 77, 79]  # C minor-ish
    chord = [SCALE[0], SCALE[2], SCALE[4]]
    for nte in chord:
        Synth.note_on(CH_PAD, nte, velocity=45)
        Synth.note_on(CH_PAD2, nte + 7, velocity=30)

    last_idx = -1
    last_note_t = 0.0
    n = 0
    while True:
        now = time.ticks_ms() / 1000.0
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()
        wx, wy, wz = pose.update(ax, ay, az, gx, gy, gz, now)
        ux, uy, uz = pose.up()

        # how much the body moves (world motion + rotation), self-calibrated
        rot = math.sqrt(gx * gx + gy * gy + gz * gz)
        mot = math.sqrt(wx * wx + wy * wy + wz * wz)
        intensity = mot + rot * 0.1
        baseline.push(intensity)
        smooth_i = baseline.mean()

        # --- pads: continuous swell + filter opening with intensity, pan with lean ---
        vol = int(vol_euro.update(min(112, 25 + smooth_i * 6.0), now))
        cutoff = int(min(120, 42 + smooth_i * 5.0))
        pan = int(max(10, min(118, 64 + ux * 55)))
        Synth.control_change(CH_PAD, 7, vol)
        Synth.control_change(CH_PAD2, 7, max(0, vol - 12))
        Synth.control_change(CH_PAD, 74, cutoff)
        Synth.control_change(CH_PAD2, 74, max(40, cutoff - 10))
        Synth.control_change(CH_PAD, 10, pan)
        Synth.control_change(CH_PAD2, 10, 127 - pan)

        # --- lead traces the arc: where the arm is along its swing picks the note,
        #     so a sweeping gesture runs notes up and down the scale ---
        arc_pos = (ux + 1.0) * 0.5 + (uz + 1.0) * 0.15
        idx = max(0, min(len(SCALE) - 1, int(arc_pos * (len(SCALE) - 1))))
        if idx != last_idx and smooth_i > 1.0 and (now - last_note_t) > 0.09:
            vel = int(max(45, min(115, 55 + smooth_i * 5.0)))
            Synth.control_change(CH_LEAD, 74, cutoff)
            Synth.control_change(CH_LEAD, 10, pan)
            Synth.note(CH_LEAD, SCALE[idx], 260, velocity=vel)
            last_idx = idx
            last_note_t = now

        # --- slow harmonic drift with posture (a colour, not a plan) ---
        if n % 130 == 0:
            r = 0 if uz > 0.3 else (2 if ux > 0.3 else (5 if ux < -0.3 else 0))
            new_chord = [SCALE[r], SCALE[r + 2], SCALE[r + 4]]
            if new_chord != chord:
                for nte in chord:
                    Synth.note_off(CH_PAD, nte)
                    Synth.note_off(CH_PAD2, nte + 7)
                chord = new_chord
                for nte in chord:
                    Synth.note_on(CH_PAD, nte, velocity=45)
                    Synth.note_on(CH_PAD2, nte + 7, velocity=30)

        n += 1
        if n % 200 == 0:
            send("intensity={:.1f} arc_idx={} vol={}".format(smooth_i, idx, vol))
        await asyncio.sleep_ms(15)
