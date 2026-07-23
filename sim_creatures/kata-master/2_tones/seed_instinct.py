async def run():
    # THE REST-TONE GATE, v2. This stage sounds exactly ONE thing: a STABLE
    # REST POSITION, the moment it is detected. No swoosh, no strike
    # coupling. Six rest positions — gravity through each body axis
    # (X+/- Y+/- Z+/-), read via Kata.pose() — six tones. Move however you
    # like: silence. Come to rest and hold: that face's tone, once. Roll
    # slowly to another face while at rest: its tone, once. Leave rest and
    # come back: the tone again.
    #
    # Rest = the Kata organ's "set" phase (speed01 < 0.20 held 0.35 s),
    # plus the face itself holding FACE_HOLD_S — so total latency from
    # stopping to tone is ~0.65 s. If that feels sluggish live, the knobs
    # are QUIET01/SET_DWELL_S (organ) and FACE_HOLD_S (here); tighten in
    # that order. Inside CONE_DEG of a true axis the tone rings full;
    # outside it lands as a dull smudge — the cone edge stays feelable,
    # and the report carries the measured off-angles to tune it.
    #
    # Faces, mounted on the back of the hand with X toward the wrist:
    #   X- fingers up -> C5    X+ fingers down -> C4
    #   Z+ palm down  -> E4    Z- palm up      -> G4
    #   Y+/Y- hand blade (chop pose) -> D4 / A4  (which edge is which sign
    #   depends on the hand it rides — label it from the first session)
    TONES = {"X-": 72, "X+": 60, "Z+": 64, "Z-": 67, "Y+": 62, "Y-": 69}
    CONE_DEG = 25.0               # a rest within this of orthogonal is TRUE
    FACE_HOLD_S = 0.30            # the face must persist this long at rest
    REST_GAP_S = 0.5              # a shorter absence doesn't re-arm the
                                  # same face (breathing-wobble guard)
    TONE_CH = 0
    Synth.program(TONE_CH, 11)    # vibraphone: a struck tone that rings
    # Never trust inherited channel state: a previous instinct (the swoosh
    # seeds) kills its sound by zeroing expression, and CCs persist on the
    # synth across swaps — session 20260713_135529 was fully silent that way.
    Synth.control_change(TONE_CH, 11, 127)
    Synth.pitch_bend(TONE_CH, 0)
    # Hello: a rising third at session start — the voice self-check. If a
    # session starts silent, the synth path is broken, not the seed.
    Synth.note(TONE_CH, 60, 150, 90)
    await asyncio.sleep_ms(200)
    Synth.note(TONE_CH, 64, 250, 90)

    sounded = None                # face already sounded for the current rest
    unset_since = None            # when rest was left (None while resting)
    cand = None                   # (face, since) awaiting FACE_HOLD_S

    win_start = time.ticks_ms() / 1000.0
    offs = {}                     # face -> [off_deg, ...] this window
    inside = 0
    outside = 0

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()            # feeds Kata/Motion/Handling
        Imu.getGyro()

        if Kata.phase() == "set":
            unset_since = None
            face, off = Kata.pose()
            if face is None:
                cand = None
            elif cand is None or cand[0] != face:
                cand = (face, now)
            elif now - cand[1] >= FACE_HOLD_S and face != sounded:
                # a stable rest position, newly reached: sound it NOW
                note = TONES.get(face, 60)
                if off <= CONE_DEG:
                    Synth.note(TONE_CH, note, 600, 95)
                    inside += 1
                else:             # the smudge: same tone, dull and short —
                    Synth.note(TONE_CH, note, 120, 40)   # the cone edge, felt
                    outside += 1
                offs.setdefault(face, []).append(off)
                sounded = face
        else:
            cand = None
            if unset_since is None:
                unset_since = now
            elif now - unset_since > REST_GAP_S:
                sounded = None    # a real departure: the next rest sounds

        # REPORT every ~20 s: where the rests landed and how far off — the
        # evidence CONE_DEG (and the hold times) get tuned against.
        if now - win_start > 20.0:
            span = now - win_start
            if offs:
                per_face = " ".join(
                    "{}:{} med {:.0f} max {:.0f}".format(
                        f, len(v), sorted(v)[len(v) // 2], max(v))
                    for f, v in sorted(offs.items()))
                stats = ("{} in / {} out of {:.0f} deg cone | off_deg {}"
                         .format(inside, outside, CONE_DEG, per_face))
            else:
                stats = "no rests"
            send("window {:.0f}s: {} | phase {} pose {} | state {} "
                 "alone {:.0f}s".format(
                     span, stats, Kata.phase(), Kata.pose(),
                     Handling.state(), Handling.alone_s()))
            win_start = now
            offs = {}
            inside = 0
            outside = 0

        await asyncio.sleep_ms(5)   # 200 Hz polling
