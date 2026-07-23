async def run():
    # THE FLUTE GATE, v5. Gate timing unchanged (open at Kata.launched(),
    # hard cut below CUT); the voice is now a KILL BILL pan flute — the
    # Zamfir "Lonely Shepherd" shape, one gust at a time:
    #   ch 0  GM 75 Pan Flute — the lead. The scoop INTO the note is the
    #         signature: bend starts ~2 semitones low and rides the speed
    #         up through center as the strike accelerates (bend range 12
    #         via RPN); vibrato (CC 1) blooms just after the attack, so
    #         the chiff stays clean and the sustain sings.
    #   ch 1  GM 122 Seashore — a whisper of breath under the flute, so a
    #         gust reads as air, not a keyboard. Set BODY_LVL 0 to solo
    #         the flute.
    # (v4's seashore+whistle wind is one git checkout away if the flute
    # doesn't survive contact with real strikes.)
    FLUTE_CH, FLUTE_NOTE = 0, 69          # A4; bend does the motion
    BODY_CH, BODY_NOTE = 1, 55
    BODY_LVL = 80                         # breath under the flute (0 = off)
    VIB = 55                              # vibrato depth after the attack
    CUT = 0.55                            # die below this (follow-through)
    Synth.program(FLUTE_CH, 75)           # pan flute
    Synth.program(BODY_CH, 122)           # seashore
    for ch in (FLUTE_CH, BODY_CH):
        Synth.control_change(ch, 11, 127)  # never trust inherited expression
        Synth.pitch_bend(ch, 0)
        Synth.control_change(ch, 101, 0)  # RPN 0: pitch bend sensitivity...
        Synth.control_change(ch, 100, 0)
        Synth.control_change(ch, 6, 12)   # ...= 12 semitones
        Synth.control_change(ch, 91, 55)  # room: the shepherd is outdoors
    # Hello: one short flute note at session start — the voice self-check.
    Synth.note(FLUTE_CH, 69, 200, 90)

    def flute_expr(s):    # speed 0.55..3.5 -> 112..127 (hot: the gust is
        return max(112, min(127, int(112 + (s - CUT) * 5)))   # the lead voice)

    def scoop_bend(s):    # low at the gate, up through center with the speed
        return int(max(-2600, min(1500, -2200 + (s - CUT) * 1250)))

    voice_on = False
    last_cc = 0.0
    gust_t0 = 0.0
    vib_on = False
    win_start = time.ticks_ms() / 1000.0
    gusts = []                     # lengths (ms) this window
    flights = []                   # [flight_ms, peak_rot, peak_acc, from_set]
    overruns = 0
    longest_set = 0.0

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()             # feeds Kata/Motion/Handling
        Imu.getGyro()

        s = Kata.speed()
        L = Kata.launched()
        if L and not voice_on:
            v = max(105, min(127, int(95 + s * 12)))
            Synth.control_change(FLUTE_CH, 1, 0)       # clean chiff first
            Synth.control_change(FLUTE_CH, 11, flute_expr(s))
            Synth.pitch_bend(FLUTE_CH, scoop_bend(s))
            Synth.note_on(FLUTE_CH, FLUTE_NOTE, v)
            if BODY_LVL:
                Synth.control_change(BODY_CH, 11, BODY_LVL)
                Synth.note_on(BODY_CH, BODY_NOTE, 70)
            voice_on = True
            vib_on = False
            gust_t0 = now
            last_cc = now
        elif voice_on:
            if s < CUT:            # the strike is done: the gust dies NOW —
                # expression to 0 kills the GM release tail instantly
                Synth.control_change(FLUTE_CH, 11, 0)
                Synth.control_change(BODY_CH, 11, 0)
                Synth.note_off(FLUTE_CH, FLUTE_NOTE)
                if BODY_LVL:
                    Synth.note_off(BODY_CH, BODY_NOTE)
                Synth.pitch_bend(FLUTE_CH, 0)
                voice_on = False
                gusts.append(int((now - gust_t0) * 1000))
            else:
                if not vib_on and now - gust_t0 >= 0.18:
                    Synth.control_change(FLUTE_CH, 1, VIB)   # the sustain sings
                    vib_on = True
                if now - last_cc >= 0.03:
                    Synth.control_change(FLUTE_CH, 11, flute_expr(s))
                    Synth.pitch_bend(FLUTE_CH, scoop_bend(s))
                    last_cc = now

        K = Kata.landed()
        if K:
            flights.append([K[1], K[2], K[3], K[6]])
        if Kata.overrun():
            overruns += 1
        longest_set = max(longest_set, Kata.set_s())

        # REPORT every ~20 s: their motion and my sounding, side by side.
        if now - win_start > 20.0:
            span = now - win_start
            if flights:
                dur = sorted(f[0] for f in flights)
                rot = sorted(f[1] for f in flights)
                acc_p = sorted(f[2] for f in flights)
                n_set = sum(f[3] for f in flights)
                stats = ("{} flights ({} from set) | ms med {} max {} | "
                         "peak rot med {} max {} dps | peak acc med {:.1f} "
                         "max {:.1f}".format(
                             len(flights), n_set, dur[len(dur) // 2], dur[-1],
                             rot[len(rot) // 2], rot[-1],
                             acc_p[len(acc_p) // 2], acc_p[-1]))
            else:
                stats = "no flights"
            if gusts:
                g = sorted(gusts)
                gstats = "{} gusts ms med {} max {}".format(
                    len(g), g[len(g) // 2], g[-1])
            else:
                gstats = "no gusts"
            send("window {:.0f}s: {} | {} | {} overruns | longest set "
                 "{:.1f}s | phase {} | state {} alone {:.0f}s | fluency "
                 "{:.2f}".format(
                     span, gstats, stats, overruns, longest_set,
                     Kata.phase(), Handling.state(), Handling.alone_s(),
                     Motion.fluency()))
            win_start = now
            gusts = []
            flights = []
            overruns = 0
            longest_set = 0.0

        await asyncio.sleep_ms(5)   # 200 Hz polling: the gust waits for no one
