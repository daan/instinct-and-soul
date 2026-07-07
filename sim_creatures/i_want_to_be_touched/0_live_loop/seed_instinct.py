async def run():
    # A warm starting point — not a plan. Three behaviours, all touch-hungry:
    #   PURR    while I'm being handled: a soft kalimba voice that follows the
    #           energy of the handling — gentle handling sings low and warm,
    #           lively handling climbs and brightens.
    #   ACCENT  a sharp jolt (tap, shake, catch) lands a bright struck note —
    #           the moment deserves punctuation.
    #   CALL    left alone too long, I send a small two-note invitation into
    #           the room, and wait, and try again a little differently.
    # Grow it as the hands ask.
    CH_PURR = 0
    CH_CALL = 1
    CH_HIT = 2
    Synth.program(CH_PURR, 108)     # kalimba — warm, intimate
    Synth.program(CH_CALL, 10)      # music box — the invitation
    Synth.program(CH_HIT, 8)        # celesta — the accent
    Synth.control_change(CH_PURR, 91, 60)   # a little reverb: I'm in a room

    SCALE = [55, 58, 60, 62, 65, 67, 70, 72, 74, 77]   # G minor pentatonic-ish

    # Handling intensity, self-calibrated: |acc| deviates from 1 g when the
    # body is moved, gyro catches turning. The baseline makes "still" mean
    # *this* table, not a hard-coded zero.
    smooth = Calc.OneEuro(min_cutoff=0.4, beta=0.2)
    baseline = Calc.Running(n=200)

    last_active_t = time.ticks_ms() / 1000.0   # last moment I felt handling
    last_call_t = 0.0
    call_step = 0
    last_purr_t = 0.0
    purr_i = 0

    # Reporting: a window of what happened to me and what I voiced.
    win_start = time.ticks_ms() / 1000.0
    win_peak = 0.0
    win_sum = 0.0
    win_n = 0
    win_notes = 0
    win_calls = 0

    while True:
        now = time.ticks_ms() / 1000.0
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        rot = math.sqrt(gx * gx + gy * gy + gz * gz)
        raw = abs(mag - 1.0) + rot / 300.0      # handling energy, ~0 at rest
        level = smooth.update(raw, now)
        baseline.push(raw)
        z = baseline.z(raw)
        win_peak = max(win_peak, level)
        win_sum += level
        win_n += 1

        handled = level > 0.02                  # any live handling at all
        if handled:
            last_active_t = now

        # ACCENT: a sharp jolt well above the recent baseline.
        if z > 4.0 and raw > 0.25 and now - last_purr_t > 0.05:
            idx = min(len(SCALE) - 1, int(4 + z))
            Synth.note(CH_HIT, SCALE[idx] + 12, 120, min(120, int(60 + z * 8)))
            win_notes += 1

        # PURR: while handled, a note every so often; pace and pitch follow
        # the handling energy — calm strokes purr slow and low, play speeds up.
        if handled:
            gap = 0.6 - min(0.45, level * 2.0)  # 0.15..0.6 s between notes
            if now - last_purr_t > gap:
                idx = min(len(SCALE) - 1, int(level * 14.0))
                vel = min(100, 35 + int(level * 180.0))
                Synth.note(CH_PURR, SCALE[idx], 260, vel)
                purr_i += 1
                last_purr_t = now
                win_notes += 1

        # CALL: alone too long — a small invitation, changing a little each
        # time so I don't become wallpaper. Silence between calls is part of
        # the invitation.
        alone_s = now - last_active_t
        if alone_s > 10.0 and now - last_call_t > 9.0:
            a = SCALE[(call_step * 2) % len(SCALE)]
            Synth.note(CH_CALL, a + 12, 250, 40)
            await asyncio.sleep_ms(280)
            Synth.note(CH_CALL, a + 17, 420, 34)
            call_step += 1
            last_call_t = now
            win_calls += 1

        # REPORT every ~20 s: both sides — how I was handled, what I voiced.
        if now - win_start > 20.0:
            mean_lvl = win_sum / max(1, win_n)
            send("window {:.0f}s: handling mean={:.3f} peak={:.2f} | "
                 "alone {:.0f}s now | voiced {} notes, {} invitation calls".format(
                     now - win_start, mean_lvl, win_peak, alone_s,
                     win_notes, win_calls))
            win_start = now
            win_peak = 0.0
            win_sum = 0.0
            win_n = 0
            win_notes = 0
            win_calls = 0

        await asyncio.sleep_ms(10)              # ~100 Hz sensing
