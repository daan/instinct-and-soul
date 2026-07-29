async def run():
    # THE PHRASE, v1. Both halves of the voice from condition_1 — the
    # pan-flute swoosh on a swift action, the vibraphone tone on the pose
    # it lands in — plus the thing this stage exists to test: CUTS CHAIN
    # INTO A PHRASE.
    #
    # The game: a swift action then a static pose is one CUT. Cuts chained
    # without a real rest are a PHRASE. A phrase that completes earns a
    # power-up. One player; nothing answers yet.
    #
    # The whole question of this stage is whether a phrase READS — whether
    # the boundaries fall where a person would put them. So the journal
    # writes one line per phrase, in the game's own grammar:
    #
    #     X+ X- Y- Y- Z+ (power up) | rests .9 1.1 .7 1.4 | 8.4s
    #
    # and nothing per cut. PHRASE_GAP_S below is the guess under test.

    PHRASE_GAP_S = 2.0        # rest longer than this ends the phrase
    MIN_PHRASE = 2            # fewer cuts than this is not a phrase, so
                              # no power-up (a single cut is just a cut)
    STALE_PHRASES = 4         # phrases with no new territory before I ask
                              # the soul how to invite them somewhere else

    FLUTE_CH, FLUTE_NOTE = 0, 69
    BODY_CH, BODY_NOTE = 1, 55
    TONE_CH = 2
    BODY_LVL = 80             # seashore under the flute (0 = off)
    VIB = 55                  # flute vibrato after the attack
    CUT = 0.55                # the gust dies below this
    TONES = {"X-": 72, "X+": 60, "Z+": 64, "Z-": 67, "Y+": 62, "Y-": 69}
    CONE_DEG = 25.0           # a rest within this of orthogonal is TRUE
    FACE_HOLD_S = 0.30        # the face must persist this long at rest
    REST_GAP_S = 0.5          # shorter absences don't re-arm the same face
    POWER_UP = (72, 76, 79, 84)   # the reward: a rising figure

    Synth.program(FLUTE_CH, 75)   # pan flute
    Synth.program(BODY_CH, 122)   # seashore
    Synth.program(TONE_CH, 11)    # vibraphone
    for ch in (FLUTE_CH, BODY_CH, TONE_CH):
        Synth.control_change(ch, 11, 127)   # never trust inherited state
        Synth.pitch_bend(ch, 0)
        Synth.control_change(ch, 91, 55)
    for ch in (FLUTE_CH, BODY_CH):
        Synth.control_change(ch, 101, 0)    # RPN 0: bend range 12 semitones
        Synth.control_change(ch, 100, 0)
        Synth.control_change(ch, 6, 12)
    Synth.note(TONE_CH, 60, 150, 90)        # hello: the voice self-check
    await asyncio.sleep_ms(200)
    Synth.note(TONE_CH, 64, 250, 90)

    def flute_expr(s):
        return max(112, min(127, int(112 + (s - CUT) * 5)))

    def scoop_bend(s):
        return int(max(-2600, min(1500, -2200 + (s - CUT) * 1250)))

    def clock():
        # ELAPSED, not wall time. This stage is read against a recording,
        # and a replay of 75 s finishes in well under a wall second — every
        # line would carry the same clock time and the phrase boundaries
        # would be unreadable. Elapsed is also what a boundary means.
        return "t+{:.1f}s".format(time.ticks_ms() / 1000.0)

    async def power_up():
        for n in POWER_UP:
            Synth.note(TONE_CH, n, 90, 100)
            await asyncio.sleep_ms(70)

    voice_on = False
    vib_on = False
    gust_t0 = 0.0
    last_cc = 0.0
    sounded = None            # face already sounded for the current rest
    unset_since = None
    cand = None               # (face, since) awaiting FACE_HOLD_S

    # ── the phrase under construction ────────────────────────────────────
    phrase = []               # faces, in order
    rests = []                # seconds between them
    loose = 0                 # cuts launched from loose motion, not a pose
    faults = 0
    phrase_t0 = None
    last_cut_t = None

    # ── the movement space, and how much of it they have visited ─────────
    seen_faces = []
    seen_pairs = []           # "X+>Z-" transitions
    longest = 0
    stale = 0                 # phrases in a row that found nothing new
    n_phrases = 0
    was_live = False          # for the session-end ask

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()        # feeds Kata/Motion/Handling — MY reads
        Imu.getGyro()
        s = Kata.speed()

        # ── the swoosh: a swift action, voiced live ──────────────────────
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
            if s < CUT:
                Synth.control_change(FLUTE_CH, 11, 0)
                Synth.control_change(BODY_CH, 11, 0)
                Synth.note_off(FLUTE_CH, FLUTE_NOTE)
                if BODY_LVL:
                    Synth.note_off(BODY_CH, BODY_NOTE)
                Synth.pitch_bend(FLUTE_CH, 0)
                voice_on = False
            else:
                if not vib_on and now - gust_t0 >= 0.18:
                    Synth.control_change(FLUTE_CH, 1, VIB)
                    vib_on = True
                if now - last_cc >= 0.03:
                    Synth.control_change(FLUTE_CH, 11, flute_expr(s))
                    Synth.pitch_bend(FLUTE_CH, scoop_bend(s))
                    last_cc = now

        # ── the tone: a stable rest position, sounded once ───────────────
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
                else:                       # the smudge: the cone edge, felt
                    Synth.note(TONE_CH, note, 120, 40)
                sounded = face
        else:
            cand = None
            if unset_since is None:
                unset_since = now
            elif now - unset_since > REST_GAP_S:
                sounded = None

        # ── a cut lands: one element of the phrase ───────────────────────
        K = Kata.landed()
        if K:
            face, from_set = K[4], K[6]
            if face is None:
                # sounded nothing readable — the feel gate's failure case,
                # worth a line because it is a FAULT, not a phrase event
                faults += 1
                send("{} a cut landed with no readable pose — no tone".format(
                    clock()))
            else:
                if last_cut_t is not None:
                    rests.append(now - last_cut_t)
                else:
                    phrase_t0 = now
                phrase.append(face)
                if not from_set:
                    loose += 1
                last_cut_t = now

        # ── the phrase ends when they rest ───────────────────────────────
        if phrase and last_cut_t is not None and now - last_cut_t > PHRASE_GAP_S:
            # the span ENDS at the last cut, not at the rest that closed it —
            # otherwise every phrase looks PHRASE_GAP_S longer than it was,
            # and a single cut appears to last exactly the gap
            span = (last_cut_t - phrase_t0) if phrase_t0 else 0.0
            earned = len(phrase) >= MIN_PHRASE
            if earned:
                await power_up()

            # what of the movement space did this phrase visit?
            fresh = []
            for f in phrase:
                if f not in seen_faces:
                    seen_faces.append(f)
                    fresh.append(f)
            for a, b in zip(phrase, phrase[1:]):
                p = "{}>{}".format(a, b)
                if p not in seen_pairs:
                    seen_pairs.append(p)
            longer = len(phrase) > longest
            if longer:
                longest = len(phrase)
            n_phrases += 1

            if earned:
                send("{} {} (power up) | rests {} | {:.1f}s | {}".format(
                    clock(), " ".join(phrase),
                    " ".join("{:.1f}".format(r) for r in rests),
                    span,
                    "all {} loose".format(loose) if loose == len(phrase)
                    else "{} of {} loose".format(loose, len(phrase)) if loose
                    else "all from a set pose"))
            else:
                # one cut on its own is not a phrase — say so plainly rather
                # than dressing it up with an empty rest list and a span
                send("{} single cut {}{}".format(
                    clock(), phrase[0], " (loose)" if loose else ""))

            # ── when this is worth waking the soul for ───────────────────
            # My job is to invite them into the movement space. So I ask
            # when that is going somewhere, or when it has stopped going
            # anywhere — never merely because a phrase happened.
            if fresh or longer:
                # New ground is only worth waking the soul for when it was
                # HARD WON — when they had stopped finding anything and then
                # did. At the start of a session everything is new; a
                # creature that asks about each of those is asking about
                # nothing, and measured 5 reflections in 75 s doing it.
                # Someone exploring freely is the creature succeeding, which
                # is precisely when it does not need help.
                if stale:
                    what = []
                    if fresh:
                        what.append("faces " + " ".join(fresh))
                    if longer:
                        what.append("their longest phrase yet ({})".format(
                            longest))
                    reflect("unstuck — {}. They played {} after {} phrases "
                            "that found nothing. {} of 6 faces now, {} "
                            "transitions. Whatever just happened, I want to "
                            "know what preceded it.".format(
                                " and ".join(what), " ".join(phrase), stale,
                                len(seen_faces), len(seen_pairs)))
                stale = 0
            else:
                stale += 1
                if stale >= STALE_PHRASES:
                    reflect("{} phrases with nothing new. They keep to {} of "
                            "6 faces ({}) and {} transitions; longest phrase "
                            "still {}. Whatever I am doing is not inviting "
                            "them anywhere.".format(
                                stale, len(seen_faces), " ".join(seen_faces),
                                len(seen_pairs), longest))
                    stale = 0

            phrase = []
            rests = []
            loose = 0
            phrase_t0 = None
            last_cut_t = None

        # ── they put it down: the session is the subject ─────────────────
        live = Handling.state() != "table"
        if was_live and not live and n_phrases:
            reflect("put down after {} phrases. They visited {} of 6 faces "
                    "({}) and {} of the 30 transitions; longest phrase {}. "
                    "Where did I never get them to go, and what might have "
                    "invited them there?".format(
                        n_phrases, len(seen_faces), " ".join(seen_faces),
                        len(seen_pairs), longest))
            n_phrases = 0
        was_live = live

        await asyncio.sleep_ms(5)   # 200 Hz: the gust waits for no one
