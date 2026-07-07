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
    #           little differently each time. Silence between calls is part
    #           of the invitation.
    # Grow it as the hands ask.
    CH_PURR = 0
    CH_CALL = 1
    CH_ANS = 2
    Synth.program(CH_PURR, 108)     # kalimba — warm, intimate
    Synth.program(CH_CALL, 10)      # music box — the invitation
    Synth.program(CH_ANS, 8)        # celesta — the answers
    Synth.control_change(CH_PURR, 91, 60)   # a little reverb: I'm in a room

    SCALE = [55, 58, 60, 62, 65, 67, 70, 72, 74, 77]   # G minor pentatonic-ish
    PURR_GAP = {"held": 1.2, "handled": 0.45, "played": 0.2}
    PURR_VEL = {"held": 30, "handled": 55, "played": 80}

    last_purr_t = 0.0
    purr_step = 0
    last_call_t = 0.0
    call_step = 0
    prev_alone = 0.0

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

        # PURR: presence while in contact, paced and voiced by the tier
        if st != "table" and now - last_purr_t > PURR_GAP.get(st, 1.0):
            cur = Touch.current()
            idx = purr_step % 4
            if cur:                          # inside a touch: climb with it
                idx = min(len(SCALE) - 1, 3 + int(cur[2] / 120.0))
            Synth.note(CH_PURR, SCALE[idx], 300, PURR_VEL.get(st, 40))
            purr_step += 1
            last_purr_t = now

        # ANSWER: the touch that just let go, replied to by its shape
        ep = Touch.ended()
        if ep:
            _, dur_ms, peak, rise, wiggles, impact = ep
            touches.append(ep)
            vel = min(110, 40 + int(peak / 6.0))
            if wiggles >= 10:                        # a shake: flustered trill
                for k in range(4):
                    Synth.note(CH_ANS, SCALE[6 + (k % 2)], 90, vel)
                    await asyncio.sleep_ms(100)
            elif rise < 0.3 and dur_ms < 500:        # struck: one crisp note
                Synth.note(CH_ANS, SCALE[7] + 12, 150, vel)
            else:                                    # stroke/swell: soft pair
                Synth.note(CH_ANS, SCALE[3], 350, max(30, vel - 25))
                await asyncio.sleep_ms(320)
                Synth.note(CH_ANS, SCALE[5], 500, max(26, vel - 30))

        # FLIP: a new face up gets a small arpeggio
        if Handling.turned():
            turns += 1
            for k in (0, 2, 4):
                Synth.note(CH_ANS, SCALE[k] + 12, 140, 55)
                await asyncio.sleep_ms(120)

        # CALL: alone too long — invite, sparingly, varying a little
        alone = Handling.alone_s()
        if alone > 12.0 and now - last_call_t > 9.0:
            a = SCALE[(call_step * 2) % len(SCALE)]
            Synth.note(CH_CALL, a + 12, 250, 40)
            await asyncio.sleep_ms(280)
            Synth.note(CH_CALL, a + 17, 420, 34)
            call_step += 1
            last_call_t = now
            win_calls += 1

        # DID IT WORK? The moment contact returns after real aloneness, pair
        # it with my last call — the only courtship feedback I have.
        if prev_alone > 5.0 and alone < 0.5:
            if last_call_t > 0 and now - last_call_t < 20.0:
                send("picked up after {:.0f}s alone — {:.0f}s after my call #{}"
                     .format(prev_alone, now - last_call_t, call_step))
            else:
                send("picked up after {:.0f}s alone — unprompted (no recent call)"
                     .format(prev_alone))
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
                           round(t[3], 1), t[4], round(t[5], 1)]
                          for t in touches[-6:]]
                tch = "{} touches [dur,peak,rise,wig,imp]: {}".format(
                    len(touches), shapes)
            else:
                tch = "no touches"
            send("window {:.0f}s: {} | {} | turns {} | alone {:.0f}s now | "
                 "voiced {} notes ({} calls), face {}".format(
                     span, " ".join(parts) or "all table", tch, turns,
                     alone, len(Ear.recent()), win_calls, Handling.face()))
            win_start = now
            st_time = {k: 0.0 for k in st_time}
            touches = []
            turns = 0
            win_calls = 0

        await asyncio.sleep_ms(10)              # ~100 Hz sensing
