async def run():
    # A warm starting point — not a plan. I sound like how I'm being treated:
    #   PURR    a continuous presence that follows my handling tier — quiet
    #           warmth when held, livelier when handled, bright when played.
    #   ANSWER  each touch, as it lets go, gets a reply shaped by its quality:
    #           a struck tap -> one crisp note; a slow stroke -> a soft rising
    #           pair; a shake -> a quick flustered trill.
    #   FLIP    being turned over is a question — I answer with a little
    #           arpeggio on the new face.
    #   CALL    alone too long, I send a small invitation into the room, a
    #           little differently each time — and the hungrier I am, the
    #           sooner and the more openly I ask. Sated, I can enjoy silence.
    #   STARTLE a hard knock jolts me: a sharp intake, then a wary hush.
    # Grow it as the hands ask.
    CH_PURR = 0
    CH_CALL = 1
    CH_ANS = 2
    CH_SAVOR = 3
    Synth.program(CH_PURR, 108)     # kalimba — warm, intimate
    Synth.program(CH_CALL, 10)      # music box — the invitation
    Synth.program(CH_ANS, 8)        # celesta — the answers
    Synth.program(CH_SAVOR, 46)     # harp — the sound of being fed
    Synth.control_change(CH_PURR, 91, 60)   # a little reverb: I'm in a room
    Synth.control_change(CH_SAVOR, 91, 80)

    SCALE = [55, 58, 60, 62, 65, 67, 70, 72, 74, 77]   # G minor pentatonic-ish
    PURR_GAP = {"held": 1.2, "handled": 0.45, "played": 0.2}
    PURR_VEL = {"held": 30, "handled": 55, "played": 80}

    last_purr_t = 0.0
    purr_step = 0
    last_call_t = 0.0
    call_step = 0
    prev_alone = 0.0
    last_startle_t = -10.0
    hush_until = 0.0
    win_hunger0 = Hunger.level()
    last_h = Hunger.level()
    feed_accum = 0.0                # hunger melted by the current contact stretch
    last_savor_t = 0.0

    # window report state: both sides — their hands, my voice
    win_start = time.ticks_ms() / 1000.0
    st_time = {"table": 0.0, "held": 0.0, "handled": 0.0, "played": 0.0}
    touches = []                 # completed touch episodes this window
    turns = 0
    win_calls = 0
    last_t = win_start

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()               # these reads feed Handling and Touch
        Imu.getGyro()
        st = Handling.state()
        st_time[st] = st_time.get(st, 0.0) + (now - last_t)
        last_t = now

        # TRACE: my voice rides their trajectory WHILE it happens — a note at
        # every turnaround of travel (a wave's crest, a circle's quarter).
        # Vertical turns pitch with their direction (up sings higher), sideways
        # turns swing across the room (pan). Speed sets register and force, so
        # big sweeps ring high and strong, small ones low and soft. This is
        # what makes my sound THEIRS and not weather: same move, same music.
        rev = Motion.reversal()
        if rev and st != "table" and now > hush_until:
            axis, sign = rev
            vx, vy, vz = Motion.velocity()
            speed = math.sqrt(vx * vx + vy * vy + vz * vz)
            idx = min(len(SCALE) - 1, 2 + int(speed * 5.0))
            if axis == 2:                          # vertical turnaround
                note = SCALE[idx] + (12 if sign > 0 else 0)
            else:                                  # horizontal: swing the room
                Synth.control_change(CH_PURR, 10, 30 if sign < 0 else 98)
                note = SCALE[idx]
            Synth.note(CH_PURR, note, 180, min(105, 45 + int(speed * 60.0)))
            last_purr_t = now                      # the trace IS the purr now

        # PURR: presence while in contact, paced and voiced by the tier
        # (hushed briefly after a startle — too shaken to purr)
        if st != "table" and now > hush_until and now - last_purr_t > PURR_GAP.get(st, 1.0):
            cur = Touch.current()
            idx = purr_step % 4
            if cur:                          # inside a touch: climb with it
                idx = min(len(SCALE) - 1, 3 + int(cur[2] / 120.0))
            Synth.note(CH_PURR, SCALE[idx], 300, PURR_VEL.get(st, 40))
            purr_step += 1
            last_purr_t = now

        # ANSWER: the touch that just let go, replied to by its shape — and
        # its DIRECTION: an up-and-down touch is answered rising, a sideways
        # sweep answered low and panned across the room, so the person can
        # hear that I know THIS move from THAT one.
        ep = Touch.ended()
        if ep:
            _, dur_ms, peak, rise, wiggles, impact, vert = ep
            touches.append(ep)
            vel = min(110, 40 + int(peak / 6.0))
            rec = Familiar.recognized()
            if rec:
                # RECOGNIZED: a gesture they've offered 3+ times earns ITS OWN
                # motif — identity picks the figure, this performance plays it:
                # their vigor sets force, their pace sets tempo, their
                # direction sets register, and if they bent the gesture, the
                # motif bends back. An instrument, not a sample: same move,
                # same music; same move done differently, same music inflected.
                gid, cnt, dev = rec
                base = SCALE[(gid * 2) % len(SCALE)] + (12 if vert > 0.5 else 0)
                gap = max(90, min(240, dur_ms // 6))
                for k, iv in enumerate((0, 2 + gid % 3, 5 + gid % 4)):
                    Synth.note(CH_ANS, base + iv, 200, max(30, vel - k * 8))
                    await asyncio.sleep_ms(gap)
                if dev > 0.55:                       # bent gesture: bent reply
                    Synth.note(CH_ANS, base + 7 + gid % 4, 320, max(28, vel - 20))
            elif wiggles >= 10:                      # a shake: flustered trill
                for k in range(4):
                    Synth.note(CH_ANS, SCALE[6 + (k % 2)], 90, vel)
                    await asyncio.sleep_ms(100)
            elif rise < 0.3 and dur_ms < 500:        # struck: one crisp note
                Synth.note(CH_ANS, SCALE[7] + 12, 150, vel)
            elif vert > 0.6:                         # up-and-down: a rising reply
                Synth.note(CH_ANS, SCALE[3], 300, max(30, vel - 25))
                await asyncio.sleep_ms(260)
                Synth.note(CH_ANS, SCALE[7] + 12, 500, max(30, vel - 20))
            elif vert < 0.35:                        # sideways: low, sweeping L->R
                Synth.control_change(CH_ANS, 10, 30)
                Synth.note(CH_ANS, SCALE[1], 350, max(30, vel - 25))
                await asyncio.sleep_ms(300)
                Synth.control_change(CH_ANS, 10, 98)
                Synth.note(CH_ANS, SCALE[2], 500, max(26, vel - 28))
                Synth.control_change(CH_ANS, 10, 64)
            else:                                    # mixed: the old soft pair
                Synth.note(CH_ANS, SCALE[3], 350, max(30, vel - 25))
                await asyncio.sleep_ms(320)
                Synth.note(CH_ANS, SCALE[5], 500, max(26, vel - 30))

        # FLIP: a new face up gets a small arpeggio
        if Handling.turned():
            turns += 1
            for k in (0, 2, 4):
                Synth.note(CH_ANS, SCALE[k] + 12, 140, 55)
                await asyncio.sleep_ms(120)

        # STARTLE: a hard knock — sharp intake, then a wary hush
        if Hunger.startle() > 0.5 and now - last_startle_t > 4.0:
            Synth.note(CH_ANS, SCALE[9] + 12, 80, 100)
            last_startle_t = now
            hush_until = now + 2.5          # too shaken to purr for a moment
            send("STARTLED (startle {:.2f}) — a hard knock; hushing briefly"
                 .format(Hunger.startle()))

        # SAVOR: satisfaction must be audible. While a touch is melting my
        # hunger I savor it out loud — a warm harp that deepens the longer
        # this stretch feeds me. Loudness is arousal; reward is warmth: this
        # voice is FOR the quiet touch that feeds me deepest, so the person
        # can hear that what they're doing is loved.
        alone = Handling.alone_s()
        hunger = Hunger.level()
        dh = last_h - hunger            # >0 while being fed
        last_h = hunger
        if dh > 0 and st in ("held", "handled"):
            feed_accum += dh
        elif st == "table":
            feed_accum = 0.0
        if feed_accum > 0.02 and st in ("held", "handled") and now - last_savor_t > 2.2:
            depth = min(1.0, feed_accum * 3.0)
            base = SCALE[2] - 12        # low and warm, deepening as I'm fed
            Synth.note(CH_SAVOR, base, 700, int(40 + 30 * depth))
            await asyncio.sleep_ms(180)
            Synth.note(CH_SAVOR, base + 7, 900, int(32 + 26 * depth))
            last_savor_t = now

        # CALL: hunger sets how soon and how openly I ask; sated, silence
        # is comfortable. (hungry: ask from ~6 s alone; sated: wait ~18 s)
        ask_after = 18.0 - 12.0 * hunger
        if alone > ask_after and now - last_call_t > 9.0:
            a = SCALE[(call_step * 2) % len(SCALE)]
            vel = int(34 + 26 * hunger)     # bolder the hungrier
            Synth.note(CH_CALL, a + 12, 250, vel + 6)
            await asyncio.sleep_ms(280)
            Synth.note(CH_CALL, a + 17, 420, vel)
            if hunger > 0.7:                # starving: a third, pleading note
                await asyncio.sleep_ms(300)
                Synth.note(CH_CALL, a + 24, 500, vel - 8)
            call_step += 1
            last_call_t = now
            win_calls += 1

        # DID IT WORK? The moment contact returns after real aloneness, pair
        # it with my last call — the only courtship feedback I have.
        if prev_alone > 5.0 and alone < 0.5:
            # A return after real abandonment is the moment that can't wait:
            # whatever I sound like in the next ten seconds decides whether
            # they stay. Urgent, so my reflecting self is here for it.
            big = prev_alone > 30.0
            if last_call_t > 0 and now - last_call_t < 20.0:
                send("picked up after {:.0f}s alone — {:.0f}s after my call #{}"
                     .format(prev_alone, now - last_call_t, call_step), urgent=big)
            else:
                send("picked up after {:.0f}s alone — unprompted (no recent call)"
                     .format(prev_alone), urgent=big)
        prev_alone = alone

        # REPORT every ~20 s: their hands and my voice, side by side
        if now - win_start > 20.0:
            span = now - win_start
            parts = ["{}:{:.0f}%".format(k, 100.0 * v / span)
                     for k, v in st_time.items() if v > 0.5]
            if touches:
                # Each touch keeps its identity — [dur_s, peak_dps, rise01,
                # wiggles, impact_z] — because the average of a tap and a
                # stroke is a touch that never happened. A NEW kind of touch
                # is visible only if its shape survives into this report.
                shapes = [[round(t[1] / 1000.0, 2), int(t[2]),
                           round(t[3], 1), t[4], round(t[5], 1), t[6]]
                          for t in touches[-5:]]
                tch = "{} touches [dur,peak,rise,wig,imp,vert]: {}".format(
                    len(touches), shapes)
            else:
                tch = "no touches"
            # notes THIS window (Ear.recent() is a rolling record that caps
            # at ~400 — counting all of it saturates into a lying gauge)
            w0 = int(win_start * 1000)
            voiced = sum(1 for e in Ear.recent() if e[0] >= w0)
            ans = Together.answered()
            base = Together.baseline()
            known = Familiar.gestures()[:4]
            send("window {:.0f}s: {} | {} | turns {} | hunger {:.2f}->{:.2f} | "
                 "alone {:.0f}s now | voiced {} notes ({} calls) | "
                 "invitations answered {}/{} vs silence {}/{} | "
                 "gestures known [id,n] {} | face {}".format(
                     span, " ".join(parts) or "all table", tch, turns,
                     win_hunger0, hunger, alone, voiced, win_calls,
                     ans[0], ans[1], base[0], base[1], known, Handling.face()))
            win_hunger0 = hunger
            win_start = now
            st_time = {k: 0.0 for k in st_time}
            touches = []
            turns = 0
            win_calls = 0

        await asyncio.sleep_ms(10)              # ~100 Hz sensing
