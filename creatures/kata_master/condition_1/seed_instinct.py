async def run():
    # THE BASELINE, v1 — the first put-together: both proven halves of the
    # instrument in one instinct. A swift motion is a GUST (the Kill Bill
    # pan-flute scoop, level gate from 1_swoosh); a stable rest position is
    # a TONE (six gravity faces, vibraphone, from 2_tones). This is the
    # condition template: study variants copy this directory and change
    # what they must — the seed, the character, or both.
    FLUTE_CH, FLUTE_NOTE = 0, 69
    BODY_CH, BODY_NOTE = 1, 55
    TONE_CH = 2
    BODY_LVL = 80                 # seashore under the flute (0 = off)
    VIB = 55                      # flute vibrato after the attack
    CUT = 0.55                    # gust dies below this (follow-through band)
    TONES = {"X-": 72, "X+": 60, "Z+": 64, "Z-": 67, "Y+": 62, "Y-": 69}
    CONE_DEG = 25.0               # a rest within this of orthogonal is TRUE
    FACE_HOLD_S = 0.30            # the face must persist this long at rest
    REST_GAP_S = 0.5              # shorter absences don't re-arm the same face

    Synth.program(FLUTE_CH, 75)   # pan flute
    Synth.program(BODY_CH, 122)   # seashore
    Synth.program(TONE_CH, 11)    # vibraphone
    for ch in (FLUTE_CH, BODY_CH, TONE_CH):
        Synth.control_change(ch, 11, 127)   # never trust inherited expression
        Synth.pitch_bend(ch, 0)
        Synth.control_change(ch, 91, 55)
    for ch in (FLUTE_CH, BODY_CH):
        Synth.control_change(ch, 101, 0)    # RPN 0: bend range 12 semitones
        Synth.control_change(ch, 100, 0)
        Synth.control_change(ch, 6, 12)
    # Hello: rising third — the voice self-check at every (re)deploy.
    Synth.note(TONE_CH, 60, 150, 90)
    await asyncio.sleep_ms(200)
    Synth.note(TONE_CH, 64, 250, 90)

    def flute_expr(s):
        return max(112, min(127, int(112 + (s - CUT) * 5)))

    def scoop_bend(s):
        return int(max(-2600, min(1500, -2200 + (s - CUT) * 1250)))

    voice_on = False
    vib_on = False
    gust_t0 = 0.0
    last_cc = 0.0
    sounded = None                # face already sounded for the current rest
    unset_since = None
    cand = None                   # (face, since) awaiting FACE_HOLD_S

    # send() only writes to the record; reflect() is the one call that
    # summons the soul, and it costs a reflection. The 20 s report window is
    # NOT the place for it — that is a reporting cadence, and asking there
    # would summon the soul three times a minute. What actually changes is
    # whether this body is being PRACTISED with: picked up, put down. A run
    # that has just ended is the whole thing worth thinking about, and it is
    # the one reading a reflex cannot do for itself.
    last_state = None
    table_since = None
    run_start = time.ticks_ms() / 1000.0
    run_gusts = 0
    run_set = 0
    run_overruns = 0

    win_start = time.ticks_ms() / 1000.0
    gusts = []
    offs = {}
    inside = 0
    outside = 0
    flights = []
    overruns = 0

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()            # feeds Kata/Motion/Handling
        Imu.getGyro()
        s = Kata.speed()

        # ── the gust: swift motion, voiced live ─────────────────────────
        L = Kata.launched()
        if L and not voice_on:
            v = max(105, min(127, int(95 + s * 12)))
            Synth.control_change(FLUTE_CH, 1, 0)
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
            if s < CUT:           # the strike is done: die NOW
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
                    Synth.control_change(FLUTE_CH, 1, VIB)
                    vib_on = True
                if now - last_cc >= 0.03:
                    Synth.control_change(FLUTE_CH, 11, flute_expr(s))
                    Synth.pitch_bend(FLUTE_CH, scoop_bend(s))
                    last_cc = now

        # ── the tone: a stable rest position, sounded once ──────────────
        if Kata.phase() == "set":
            unset_since = None
            face, off = Kata.pose()
            if face is None:
                cand = None
            elif cand is None or cand[0] != face:
                cand = (face, now)
            elif now - cand[1] >= FACE_HOLD_S and face != sounded:
                note = TONES.get(face, 60)
                if off <= CONE_DEG:
                    Synth.note(TONE_CH, note, 600, 95)
                    inside += 1
                else:
                    Synth.note(TONE_CH, note, 120, 40)
                    outside += 1
                offs.setdefault(face, []).append(off)
                sounded = face
        else:
            cand = None
            if unset_since is None:
                unset_since = now
            elif now - unset_since > REST_GAP_S:
                sounded = None

        K = Kata.landed()
        if K:
            flights.append([K[1], K[2], K[6]])
        if Kata.overrun():
            overruns += 1

        # ── picked up / put down: the only thing worth waking the soul ────
        state = Handling.state()
        if state != last_state:
            if last_state is not None:
                live = state != "table"
                was_live = last_state != "table"
                if was_live and not live:
                    # A practice run just ended — the whole run is the
                    # subject. Fold in the window still open, or a run
                    # shorter than one report window looks empty.
                    reflect("put down after {:.0f}s of practice: {} gusts, "
                            "{} of them from the set, {} overruns, fluency "
                            "{:.2f}. Did I sound like the motion felt?".format(
                                now - run_start,
                                run_gusts + len(gusts),
                                run_set + sum(f[2] for f in flights),
                                run_overruns + overruns, Motion.fluency()))
                    table_since = now
                elif live and not was_live:
                    # NOT Handling.alone_s(): a real touch resets it, and by
                    # the time the state has flipped the touch has happened,
                    # so it always reads 0 here. Time it myself.
                    reflect("picked up after {:.0f}s alone — a run is "
                            "starting".format(
                                now - table_since if table_since else 0.0))
                    run_start = now
                    run_gusts = 0
                    run_set = 0
                    run_overruns = 0
            last_state = state

        # REPORT every ~20 s: both halves, side by side.
        if now - win_start > 20.0:
            span = now - win_start
            if gusts:
                g = sorted(gusts)
                gstats = "{} gusts ms med {} max {}".format(
                    len(g), g[len(g) // 2], g[-1])
            else:
                gstats = "no gusts"
            n_set = sum(f[2] for f in flights)
            if offs:
                per_face = " ".join(
                    "{}:{}".format(f, len(v)) for f, v in sorted(offs.items()))
                tstats = "rests {} in / {} out [{}]".format(
                    inside, outside, per_face)
            else:
                tstats = "no rests"
            send("window {:.0f}s: {} ({} from set) | {} | {} overruns | "
                 "phase {} | state {} alone {:.0f}s | fluency {:.2f}".format(
                     span, gstats, n_set, tstats, overruns, Kata.phase(),
                     Handling.state(), Handling.alone_s(), Motion.fluency()))
            run_gusts += len(gusts)
            run_set += n_set
            run_overruns += overruns
            win_start = now
            gusts = []
            offs = {}
            inside = 0
            outside = 0
            flights = []
            overruns = 0

        await asyncio.sleep_ms(5)   # 200 Hz polling: the gust waits for no one
