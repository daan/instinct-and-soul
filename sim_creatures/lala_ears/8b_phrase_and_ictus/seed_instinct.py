async def run():
    # A warm starting point — a continuous electronic soundscape that follows
    # the body: sustained pads that swell and open with how much it moves, and
    # a lead that sings each GESTURE as a phrase — the note begins when the
    # gesture begins, glides to a new pitch at every turnaround of travel
    # (rising travel sings higher, sinking lower), and releases when the
    # gesture lands, so the note lasts exactly as long as the arm's arc.
    # On top of the phrase, STRONG strokes strike: a fast turnaround lands a
    # short accented hit an octave up — the vertical punctuation of the sweep.
    # No percussion. Grow it as the body asks.
    CH_PAD = 0
    CH_PAD2 = 2
    CH_LEAD = 1
    CH_HIT = 3
    Synth.program(CH_PAD, 88)      # warm pad
    Synth.program(CH_PAD2, 94)     # halo pad
    Synth.program(CH_LEAD, 81)     # saw lead
    Synth.program(CH_HIT, 81)      # same voice, struck: the accents
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
    last_hit_t = 0.0
    win_rev = 0                  # travel turnarounds seen this window
    win_eps = []                 # completed gesture durations (ms) this window
    phrase_note = None           # the lead note held through the current gesture
    chord_due = False            # a pending chord change, waiting for the beat
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

        # --- lead: each gesture is a phrase. A note begins when the gesture
        #     begins, glides to a new pitch at every turnaround of travel
        #     (rising travel sings higher, sinking lower), and releases when
        #     the gesture lands — so the note lasts as long as the arm's arc.
        rev = Motion.reversal()
        if rev:
            win_rev += 1
        if Episode.started() and phrase_note is None:
            idx = max(0, min(len(SCALE) - 1, int(len(SCALE) * 0.45 + vz * 4.0)))
            phrase_note = SCALE[idx]
            Synth.control_change(CH_LEAD, 74, cutoff)
            Synth.control_change(CH_LEAD, 10, pan)
            Synth.note_on(CH_LEAD, phrase_note, velocity=85)
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if phrase_note is not None and rev and (now - last_note_t) > 0.15:
            idx = max(0, min(len(SCALE) - 1, int(len(SCALE) * 0.45 + vz * 4.0)))
            nxt = SCALE[idx]
            if nxt != phrase_note:
                vel = int(max(50, min(115, 55 + speed * 18.0)))
                Synth.note_on(CH_LEAD, nxt, velocity=vel)   # legato: on before off
                Synth.note_off(CH_LEAD, phrase_note)
                phrase_note = nxt
            last_note_t = now
        # a strong stroke's turnaround STRIKES — short, bright, an octave up,
        # loud with the speed of the stroke: the accent on top of the phrase
        if rev and speed > 2.0 and (now - last_hit_t) > 0.18:
            idx = max(0, min(len(SCALE) - 1, int(len(SCALE) * 0.45 + vz * 4.0)))
            Synth.control_change(CH_HIT, 74, min(127, cutoff + 25))
            Synth.note(CH_HIT, SCALE[idx] + 12, 140,
                       velocity=int(min(127, 60 + speed * 20.0)))
            last_hit_t = now
        done = Episode.ended()
        if done is not None:
            win_eps.append(done[1])       # completed gesture duration, ms
            if phrase_note is not None:
                Synth.note_off(CH_LEAD, phrase_note)   # the landing releases
                phrase_note = None

        # --- slow harmonic drift with posture (a colour, not a plan); when
        # the body carries a pulse, the change waits for the beat (phase ~ 0)
        if n % 130 == 0:
            chord_due = True
        if chord_due:
            ph = Pulse.phase()
            on_beat = ph is None or Pulse.confidence() < 0.25 or ph < 0.12 or ph > 0.88
            if on_beat:
                chord_due = False
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
            hits = 0
            for e in Ear.recent():
                if e[0] >= t0_ms and e[1] != "off":
                    if e[2] == CH_LEAD:
                        lead += 1
                        lead_ts.append(e[0])
                    elif e[2] == CH_HIT:
                        hits += 1
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
            ep_txt = "-"
            if win_eps:
                med = sorted(win_eps)[len(win_eps) // 2]
                ep_txt = "{}~{:.1f}s".format(len(win_eps), med / 1000.0)
            # gestures without voice are the mismatch that matters
            moving_quiet = (mean_i > 25.0 or len(win_eps) >= 2) and (lead + other) < 2
            still_loud = mean_i < 4.0 and (lead + other) > 8      # body still, voice busy
            overdue = (now - last_report_t) > 25.0                # fallback: never long unheard
            conf = Pulse.confidence()
            pulse_txt = "{:.2f}s@{:.2f}".format(Pulse.period(), conf) if conf > 0.1 else "-"
            if moving_quiet or still_loud or overdue:
                tag = "MISMATCH" if (moving_quiet or still_loud) else "ok"
                send("{} last {:.0f}s: body mean={:.1f} peak={:.1f} rev={} ep={} pulse={}; voiced lead={} hits={} other={} lead_gap={} cc={}".format(
                    tag, now - win_start, mean_i, win_peak, win_rev, ep_txt, pulse_txt, lead, hits, other, ioi, cc_win))
                last_report_t = now
                Mem.push("last_report_t", now)
            win_start = now
            win_sum = 0.0
            win_peak = 0.0
            win_n = 0
            win_eps = []
            win_rev = 0
            cc_at_win = cc_now

        n += 1
        await asyncio.sleep_ms(15)
