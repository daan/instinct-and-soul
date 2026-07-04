async def run():
    # A warm starting point — a continuous electronic soundscape that follows the
    # body: sustained pads that swell and open with how much it moves, and a lead
    # that speaks at the TURNAROUNDS of travel — each swing through space lands
    # on a note, and the pitch rides the vertical flow (rising travel sings
    # higher, sinking lower), so an arc becomes a phrase. No percussion.
    # Grow it as the body asks.
    CH_PAD = 0
    CH_PAD2 = 2
    CH_LEAD = 1
    Synth.program(CH_PAD, 88)      # warm pad
    Synth.program(CH_PAD2, 94)     # halo pad
    Synth.program(CH_LEAD, 81)     # saw lead
    Synth.control_change(CH_LEAD, 65, 110)   # portamento on — glide between notes

    # Orientation and travel come from the Motion sense — always warm, fed by
    # my own Imu reads, never reset by a rewrite. I keep reading the Imu
    # briskly every loop; that is what keeps the sense sharp.
    vol_euro = Calc.OneEuro(min_cutoff=0.3, beta=0.1)
    baseline = Calc.Running(n=120)

    SCALE = [48, 51, 53, 55, 58, 60, 63, 65, 67, 70, 72, 75, 77, 79]  # C minor-ish
    chord = [SCALE[0], SCALE[2], SCALE[4]]
    for nte in chord:
        Synth.note_on(CH_PAD, nte, velocity=45)
        Synth.note_on(CH_PAD2, nte + 7, velocity=30)

    last_note_t = 0.0
    win_rev = 0                  # travel turnarounds seen this window
    n = 0

    # --- reporting: my sends are the only senses my reflecting self has, so
    # each one carries both sides of the last stretch — what the body did and
    # what I voiced (Ear) — and I ask for reflection when the two diverge.
    # A slow fallback report keeps me from ever going long unheard.
    # The report clock lives in Mem so a rewrite doesn't reset my cadence.
    now0 = time.ticks_ms() / 1000.0
    win_start = now0             # start of the current observation window (s)
    win_sum = 0.0                # accumulated intensity over the window
    win_peak = 0.0
    win_n = 0
    last_report_t = Mem.latest("last_report_t")
    if last_report_t is None:
        last_report_t = now0 - 21.0   # first boot only: report early
    cc_at_win = Ear.cc_total()   # CC messages already sent when this window opened

    while True:
        now = time.ticks_ms() / 1000.0
        ax, ay, az = Imu.getAccel()      # these reads also feed the Motion sense
        gx, gy, gz = Imu.getGyro()
        wx, wy, wz = Motion.accel_world()
        ux, uy, uz = Motion.up()
        vx, vy, vz = Motion.velocity()   # travel, world frame

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

        # --- lead speaks at the turnarounds of travel: each swing lands on a
        #     note; pitch rides the vertical flow (rising travel sings higher,
        #     sinking lower); velocity carries the speed of the new stroke.
        #     An arc through space becomes a phrase, not a stutter. ---
        rev = Motion.reversal()
        if rev:
            win_rev += 1
        if rev and smooth_i > 1.0 and (now - last_note_t) > 0.15:
            speed = math.sqrt(vx * vx + vy * vy + vz * vz)
            idx = max(0, min(len(SCALE) - 1, int(len(SCALE) * 0.45 + vz * 4.0)))
            vel = int(max(50, min(115, 55 + speed * 18.0)))
            Synth.control_change(CH_LEAD, 74, cutoff)
            Synth.control_change(CH_LEAD, 10, pan)
            Synth.note(CH_LEAD, SCALE[idx], 420, velocity=vel)
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

        # --- report & warrant: every ~4 s, hold what the body did against what
        # I voiced; a divergence is a reason to reflect, routine is not.
        win_sum += intensity
        win_n += 1
        if intensity > win_peak:
            win_peak = intensity
        if now - win_start >= 4.0:
            mean_i = win_sum / max(1, win_n)
            t0_ms = win_start * 1000.0
            lead = other = 0
            lead_ts = []
            for e in Ear.recent():
                if e[0] >= t0_ms and e[1] != "off":
                    if e[2] == CH_LEAD:
                        lead += 1
                        lead_ts.append(e[0])
                    else:
                        other += 1
            # the timing of my own lead notes: median gap between them, so a
            # rhythm I believe in is one I can check against what I voiced
            ioi = "-"
            if len(lead_ts) >= 3:
                gaps = sorted(lead_ts[i + 1] - lead_ts[i] for i in range(len(lead_ts) - 1))
                ioi = "{:.2f}s".format(gaps[len(gaps) // 2] / 1000.0)
            cc_now = Ear.cc_total()
            cc_win = cc_now - cc_at_win   # control messages I poured out this window
            moving_quiet = mean_i > 25.0 and (lead + other) < 2   # body loud, voice absent
            still_loud = mean_i < 4.0 and (lead + other) > 8      # body still, voice busy
            overdue = (now - last_report_t) > 25.0                # fallback: never long unheard
            if moving_quiet or still_loud or overdue:
                tag = "MISMATCH" if (moving_quiet or still_loud) else "ok"
                send("{} last {:.0f}s: body mean={:.1f} peak={:.1f} rev={}; voiced lead={} other={} lead_gap={} cc={}".format(
                    tag, now - win_start, mean_i, win_peak, win_rev, lead, other, ioi, cc_win))
                last_report_t = now
                Mem.push("last_report_t", now)
            win_start = now
            win_sum = 0.0
            win_peak = 0.0
            win_n = 0
            win_rev = 0
            cc_at_win = cc_now

        n += 1
        await asyncio.sleep_ms(15)
