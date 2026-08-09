async def run():
    # KATA MASTER — the seed. MY WORK IS ANSWERING.
    #
    # Recognition is not my work: KataSense is validated machinery (its
    # replay suite lives with the firmware), and my part of it is only
    # the judgments I construct it with. My lines are for the game:
    #
    #     AWAY ── picked up ──▶ REST ── launch ──▶ STRIKE
    #       ▲                   ▲  ▲                 │  land: TONE, the cut
    #       │                   │  └────────────◀────┤        joins the phrase
    #       │                   │      overrun: silent, no tone
    #       │                   │
    #       │                 ANSWER ◀── a rest closes the phrase: I
    #       │                   │        analyze it and compose a reply
    #       │                   ├── reply finished ──▶ REST
    #       │                   └── they cut in ──▶ STRIKE (my reply
    #       │                                       plays on underneath)
    #       └── put down, from any in-hand state: the run ends, I think.
    #
    # INVARIANTS — break one and nothing crashes, you just go blind:
    #   1. State that must outlive a rewrite lives in mem[...]; locals
    #      are scratch. The sense lives in mem so its short-term memory
    #      survives a rewrite. `mode` is a local: re-derived at start-up.
    #   2. setdefault at the top of run(), never in the loop.
    #   3. Never repurpose a key — new meaning, new name.
    #   4. A retuned sense judgment needs a NEW KataSense: replace
    #      mem["sense"] with a fresh construction when constants change
    #      (cheap; its memory is subsecond).
    #   5. Sound a motion the tick it opens, kill it the tick it dies —
    #      late is a lie. The loop stays at 5 ms; nothing in it blocks.

    # ── judgment: what a kata IS (experience.md "my sense, briefly") ─────
    SENSE = dict(quiet=0.20, spent=0.30, rearm=0.55, launch=0.75,
                 set_dwell_s=0.35, land_hold_s=0.22, refract_s=0.20,
                 max_flight_s=1.2, set_linger_s=0.25,
                 rot_fs=600.0, acc_fs=25.0,
                 speed_tau_s=0.04, grav_tau_s=0.12, act_tau_s=2.0)
    CUT = 0.55            # the gust dies below this (follow-through band)
    HAND_LOW, HAND_HIGH = 0.8, 2.0        # dps of slow activity: table /
    PICKUP_HOLD_S, PUTDOWN_HOLD_S = 0.5, 6.0   # in-hand (GUESSED)

    # ── judgment: the voice ──────────────────────────────────────────────
    FLUTE_CH, FLUTE_NOTE = 0, 69
    BODY_CH, BODY_NOTE, BODY_LVL = 1, 55, 80
    TONE_CH, VIB = 2, 55
    TONES = {"X-": 72, "X+": 60, "Z+": 64, "Z-": 67, "Y+": 62, "Y-": 69}
    CONE_DEG = 25.0       # a landing within this rings full

    # ── judgment: the exchange (ALL UNTESTED on a hand) ──────────────────
    PHRASE_END_S = 2.0    # this long at rest after a landing closes a phrase
    ANSWER_WAIT_S = 0.3   # breath before my reply
    ANSWER_STEP_S = 0.5   # onset-to-onset inside my reply
    ANSWER_NOTE_MS = 420
    REPORT_EVERY_S = 30.0

    # ── the voice wakes ──────────────────────────────────────────────────
    Synth.program(FLUTE_CH, 75)
    Synth.program(BODY_CH, 122)
    Synth.program(TONE_CH, 11)
    for ch in (FLUTE_CH, BODY_CH, TONE_CH):
        Synth.control_change(ch, 11, 127)   # never trust inherited state
        Synth.pitch_bend(ch, 0)
        Synth.control_change(ch, 91, 55)
    for ch in (FLUTE_CH, BODY_CH):
        Synth.control_change(ch, 101, 0)
        Synth.control_change(ch, 100, 0)
        Synth.control_change(ch, 6, 12)     # bend range 12 semitones
    Synth.note(TONE_CH, 60, 150, 90)        # hello: rising third — the
    await asyncio.sleep_ms(200)             # voice self-check; deploys
    Synth.note(TONE_CH, 64, 250, 90)        # happen while the box rests

    def clock():
        t = time.localtime()
        if t[0] >= 2020:
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def note(msg):
        send("{} {}".format(clock(), msg))

    now = time.ticks_ms() / 1000.0

    # ── what I carry across my own rewrites ──────────────────────────────
    for k, v in (
        ("alone_since", None), ("run_start", None),
        ("cuts", 0), ("from_set", 0), ("overruns", 0), ("chains", 0),
        ("faces", {}),            # face -> count, this run
        ("phrases", 0), ("answers", 0), ("barges", 0),
        ("phrase", []),           # the phrase being composed: [face, ...]
        ("phrase_info", []),      # its numbers: [[flight_s, off_deg], ...]
        ("repertoire", {}),       # "A)B" transition -> count, whole waking
        ("phrase_lens", []),      # every phrase length this waking
        ("last_phrase", []),      # for repeat detection
        ("repeats", 0),           # phrases identical to their predecessor
    ):
        mem.setdefault(k, v)
    mem.setdefault("sense", KataSense(Calc, **SENSE))
    mem.setdefault("hand_g", Calc.Gate(HAND_LOW, HAND_HIGH,
                                       rise_hold_s=PICKUP_HOLD_S,
                                       fall_hold_s=PUTDOWN_HOLD_S))
    sense, hand_g = mem["sense"], mem["hand_g"]
    hand_g.low, hand_g.high = HAND_LOW, HAND_HIGH
    hand_g.rise_hold, hand_g.fall_hold = PICKUP_HOLD_S, PUTDOWN_HOLD_S

    # working state — about this instant; deliberately locals
    mode = "rest" if hand_g.state else "away"
    gust_on = False
    vib_on = False
    gust_t0 = 0.0
    last_cc = 0.0
    last_land_t = None
    reply = []                # [(midi_note, due_t), ...] scheduled answer
    last_report = now

    # ── the voice of the moment: gust and tone ───────────────────────────
    def ride_gust(ev, now):
        # the swoosh follows the hand itself, whatever the mode
        nonlocal gust_on, vib_on, gust_t0, last_cc
        s = sense.speed01
        if ev is not None and ev[0] == "launch" and not gust_on:
            Synth.control_change(FLUTE_CH, 1, 0)
            Synth.control_change(FLUTE_CH, 11, _expr(s))
            Synth.pitch_bend(FLUTE_CH, _bend(s))
            Synth.note_on(FLUTE_CH, FLUTE_NOTE,
                          max(105, min(127, int(95 + s * 12))))
            if BODY_LVL:
                Synth.control_change(BODY_CH, 11, BODY_LVL)
                Synth.note_on(BODY_CH, BODY_NOTE, 70)
            gust_on, vib_on, gust_t0, last_cc = True, False, now, now
        elif gust_on:
            if s < CUT:                    # the strike is done: die NOW
                Synth.control_change(FLUTE_CH, 11, 0)
                Synth.control_change(BODY_CH, 11, 0)
                Synth.note_off(FLUTE_CH, FLUTE_NOTE)
                if BODY_LVL:
                    Synth.note_off(BODY_CH, BODY_NOTE)
                Synth.pitch_bend(FLUTE_CH, 0)
                gust_on = False
            else:
                if not vib_on and now - gust_t0 >= 0.18:
                    Synth.control_change(FLUTE_CH, 1, VIB)
                    vib_on = True
                if now - last_cc >= 0.03:
                    Synth.control_change(FLUTE_CH, 11, _expr(s))
                    Synth.pitch_bend(FLUTE_CH, _bend(s))
                    last_cc = now

    def _expr(s):
        return max(112, min(127, int(112 + (s - CUT) * 5)))

    def _bend(s):
        return int(max(-2600, min(1500, -2200 + (s - CUT) * 1250)))

    def tone(fs, face, off):
        # the landing sounds, and the cut joins the phrase
        mem["cuts"] += 1
        if face is None:
            return
        if off <= CONE_DEG:
            Synth.note(TONE_CH, TONES.get(face, 60), 600, 95)
        else:
            Synth.note(TONE_CH, TONES.get(face, 60), 120, 40)
        mem["faces"][face] = mem["faces"].get(face, 0) + 1
        mem["phrase"].append(face)
        mem["phrase_info"].append([round(fs, 2), off])

    # ═════════════ THE ANSWERING — this is my actual work ════════════════
    def analyze(phrase):
        # what was this phrase, against everything they have played?
        # Returns (new_transitions, repeated01) and grows the repertoire.
        new = []
        for i in range(len(phrase) - 1):
            tr = phrase[i] + ")" + phrase[i + 1]
            n = mem["repertoire"].get(tr, 0) + 1
            mem["repertoire"][tr] = n
            if n == 1:
                new.append(tr)
        repeated = 1 if phrase == mem["last_phrase"] else 0
        mem["last_phrase"] = list(phrase)
        mem["phrase_lens"].append(len(phrase))
        mem["repeats"] += repeated
        return new, repeated

    def compose_answer(phrase, new, repeated):
        # THE SITE WHERE MY ANSWERING GROWS. Today I know one reply:
        # the echo — say their phrase back, note for note. It is my
        # punctuation ("I heard a sentence") and my whole repertoire.
        # A later me, reading the exchange record, earns the others:
        # vary one cut, extend by one, propose the nearest transition
        # they have never played (the repertoire dict knows which).
        # Whatever I compose, the journal must say WHAT and WHY, or the
        # exchange record cannot teach me whether it worked.
        return list(phrase), "echo"

    def answer(now):
        phrase = mem["phrase"]
        info = " ".join("{:.1f}s/{:.0f}\u00b0".format(i[0], i[1])
                        for i in mem["phrase_info"])
        new, repeated = analyze(phrase)
        tags = []
        if new:
            tags.append("new " + " ".join(new))
        if repeated:
            tags.append("repeat")
        note("THEM: {}  ({}){}".format(
            " ".join(phrase), info,
            "  | " + ", ".join(tags) if tags else ""))
        mem["phrases"] += 1

        plan, why = compose_answer(phrase, new, repeated)
        t = now + ANSWER_WAIT_S
        for f in plan:
            reply.append((TONES.get(f, 60), t))
            t += ANSWER_STEP_S
        note("ME: {} {}".format(why, " ".join(plan)))
        mem["answers"] += 1
        mem["phrase"] = []             # plain assignment persists: it
        mem["phrase_info"] = []        # writes INTO mem

    def speak(now):
        # my scheduled reply notes — never blocking, playing on beneath
        # whatever happens next
        while reply and now >= reply[0][1]:
            n, _ = reply.pop(0)
            Synth.note(TONE_CH, n, ANSWER_NOTE_MS, 85)

    # ── run boundaries ───────────────────────────────────────────────────
    def begin_run(now):
        alone = (now - mem["alone_since"]) if mem["alone_since"] else 0.0
        note("picked up after {:.0f}s alone — a run is starting".format(
            alone))
        mem["run_start"] = now
        for k in ("cuts", "from_set", "overruns", "chains",
                  "phrases", "answers", "barges"):
            mem[k] = 0
        mem["faces"] = {}

    def end_run(t_edge):
        # the one scheduled reason to think: the run, whole — and the
        # question is always about the ANSWERING, because that is the
        # only thing I can change
        mem["alone_since"] = t_edge
        if mem["run_start"] is None:
            return
        lens = mem["phrase_lens"]
        faces = " ".join("{}:{}".format(f, n) for f, n
                         in sorted(mem["faces"].items()))
        reflect("put down after {:.0f}s: {} cuts ({} from a pose), faces "
                "[{}], {} chains, {} overruns | {} phrases (lens {}, {} "
                "repeats), {} answered, {} cut into | repertoire {} of "
                "30 transitions this waking. I only echoed — did their "
                "phrases grow, or circle?".format(
                    t_edge - mem["run_start"], mem["cuts"],
                    mem["from_set"], faces, mem["chains"],
                    mem["overruns"], mem["phrases"],
                    ",".join(str(n) for n in lens[-8:]) or "-",
                    mem["repeats"], mem["answers"], mem["barges"],
                    len(mem["repertoire"])))
        mem["run_start"] = None

    # ── the loop: senses first, then the one current state ───────────────
    while True:
        now = time.ticks_ms() / 1000.0
        a = Imu.getAccel()
        g = Imu.getGyro()
        M5.update()

        ev = sense.step(a, g, now)
        he = hand_g.update(sense.activity, now)
        ride_gust(ev, now)
        speak(now)
        if ev is not None and ev[0] == "launch":
            if ev[1]:
                mem["from_set"] += 1
            if ev[2]:
                mem["chains"] += 1

        if mode != "away" and he is not None and he[0] == "fall":
            mode = "away"
            end_run(he[1])

        elif mode == "away":
            if he is not None and he[0] == "rise":
                mode = "rest"
                begin_run(now)
                last_report = now

        elif mode == "rest":
            if ev is not None and ev[0] == "launch":
                mode = "strike"
            elif (mem["phrase"] and last_land_t is not None
                    and now - last_land_t > PHRASE_END_S):
                mode = "answer"
                answer(now)
                last_land_t = None

        elif mode == "strike":
            if ev is not None:
                if ev[0] == "land":
                    mode = "rest"
                    tone(ev[1], ev[2], ev[3])
                    last_land_t = now
                elif ev[0] == "overrun":
                    mode = "rest"          # silent: waving, not a kata
                    mem["overruns"] += 1

        elif mode == "answer":
            if ev is not None and ev[0] == "launch":
                mode = "strike"            # they cut into my reply —
                mem["barges"] += 1         # they spoke first; it plays
                note("they cut into my answer")   # on underneath
            elif not reply:
                mode = "rest"

        if mode != "away" and now - last_report > REPORT_EVERY_S:
            note("window: {} cuts, {} phrases, {} answered | mode {} | "
                 "act {:.1f}".format(mem["cuts"], mem["phrases"],
                                     mem["answers"], mode,
                                     sense.activity))
            last_report = now

        await asyncio.sleep_ms(5)      # 200 Hz: the gust waits for no one
