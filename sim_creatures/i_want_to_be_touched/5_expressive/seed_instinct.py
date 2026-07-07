async def run():
    # ONE COHERENT INSTRUMENT, not a box of sound effects. A continuous tone
    # sounds for as long as I'm in their hands, and the NATURE of the
    # movement performs it: speed is breath (expression), vertical velocity
    # is the whammy bar (pitch bend), smoothness is light (brightness),
    # sideways drift is space (pan). GESTURES PROVIDE THE TONES: each
    # gesture this person has taught me owns a root and an octave, and when
    # the body recognizes one forming, the drone glides there — a fretting
    # hand. Recognition also ornaments (the gesture's own voice, briefly),
    # but the instrument is the drone; everything else decorates it.
    # A small CHOIR carries me: one neutral hum while nothing is recognized,
    # and each known gesture owns a VOICE of its own — same family, distinct
    # member (baritone aahs, tenor oohs, bright synth voice, strings, organ).
    # Coherent but unmistakable: the gesture doesn't just pick a note, it
    # picks WHO is singing.
    CH_DRONE = 0                    # the neutral hum
    CH_CALL = 1
    CH_ANS = 2
    CH_SAVOR = 3
    Synth.program(CH_DRONE, 52)     # choir aahs, mid register
    Synth.program(CH_CALL, 10)      # music box — the invitation
    Synth.program(CH_ANS, 8)        # celesta — flips and small answers
    Synth.program(CH_SAVOR, 46)     # harp — the sound of being fed
    Synth.control_change(CH_SAVOR, 91, 80)

    SCALE = [55, 58, 60, 62, 65, 67, 70, 72, 74, 77]   # G minor pentatonic-ish

    # gesture voices: (program, register) — a choir's members, ch 4..8
    GESTURE_VOICES = ((52, -12),    # baritone aahs
                      (53, 0),      # tenor oohs
                      (54, 12),     # bright synth voice
                      (48, -12),    # strings, low and warm
                      (19, 0))      # church organ
    gest_voice = {}
    def gesture_ch(gid):
        if gid not in gest_voice:
            slot = len(gest_voice) % 5
            ch = 4 + slot
            prog, oct_ = GESTURE_VOICES[slot]
            Synth.program(ch, prog)
            Synth.control_change(ch, 91, 70)
            gest_voice[gid] = (ch, oct_)
        return gest_voice[gid]
    def gesture_root(gid):
        _, oct_ = gesture_ch(gid)
        return SCALE[(gid * 2) % len(SCALE)] + oct_
    for _ch in (CH_DRONE, 4, 5, 6, 7, 8):
        Synth.control_change(_ch, 91, 60)
        Synth.control_change(_ch, 65, 127)   # portamento: roots GLIDE
        Synth.control_change(_ch, 5, 45)

    root = SCALE[2]                 # the tone, until a gesture teaches one
    drone_note = None               # sounding note, or None
    cur_ch = CH_DRONE               # WHO is singing: neutral hum or a gesture voice
    speed_ema = 0.0
    vz_ema = 0.0                    # smoothed vertical velocity: inflection, not wobble
    last_mod_t = 0.0
    last_flu_t = 0.0
    guess_id = None
    guess_conf = 0.0

    last_call_t = 0.0
    call_step = 0
    prev_alone = 0.0
    last_startle_t = -10.0
    hush_until = 0.0
    last_h = Hunger.level()
    feed_accum = 0.0
    last_savor_t = 0.0
    win_hunger0 = Hunger.level()

    win_start = time.ticks_ms() / 1000.0
    st_time = {"table": 0.0, "held": 0.0, "handled": 0.0, "played": 0.0}
    touches = []
    turns = 0
    win_calls = 0
    last_t = win_start

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()               # these reads feed every sense
        Imu.getGyro()
        st = Handling.state()
        st_time[st] = st_time.get(st, 0.0) + (now - last_t)
        last_t = now

        # THE DRONE: alive exactly while I'm in their hands
        vx, vy, vz = Motion.velocity()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        speed_ema += 0.2 * (speed - speed_ema)
        in_hands = st != "table" and now > hush_until
        if in_hands and drone_note is None:
            drone_note = root
            Synth.note_on(cur_ch, drone_note, 68)
        elif (not in_hands) and drone_note is not None:
            Synth.note_off(cur_ch, drone_note)
            Synth.pitch_bend(cur_ch, 0)
            drone_note = None
            cur_ch = CH_DRONE        # next contact starts on the neutral hum
            root = SCALE[2]

        # fast modulation (~12 Hz): breath, and a GENTLE vocal inflection —
        # the bend is smoothed and shallow (a singer leaning into a note),
        # never a raw wobble
        if drone_note is not None and now - last_mod_t > 0.08:
            vz_ema += 0.25 * (vz - vz_ema)
            Synth.pitch_bend(cur_ch, max(-800, min(800, int(vz_ema * 500))))
            Synth.control_change(cur_ch, 11, min(115, 25 + int(speed_ema * 70)))
            last_mod_t = now

        # slow color (~2.5 Hz): light, space — and WHO is singing
        if drone_note is not None and now - last_flu_t > 0.4:
            fl = Motion.fluency()
            Synth.control_change(cur_ch, 74, 30 + int(fl * 80))
            Synth.control_change(cur_ch, 10, max(20, min(108, 64 + int(vx * 40))))
            g = Familiar.guess()
            guess_id, guess_conf = (g[0], g[1]) if g else (None, 0.0)
            # leaving the neutral hum is easy (0.3); stealing the note from
            # another gesture's singer takes real conviction (0.5) — so the
            # choir doesn't flap between voices mid-play
            need = 0.3 if cur_ch == CH_DRONE else 0.5
            if guess_id is not None and guess_conf > need:
                gch, _ = gesture_ch(guess_id)
                nroot = gesture_root(guess_id)
                if gch != cur_ch or nroot != root:
                    # the gesture provides the tone AND the voice: the hum
                    # hands the note to that gesture's own singer
                    Synth.note_off(cur_ch, drone_note)
                    Synth.pitch_bend(cur_ch, 0)
                    cur_ch, root = gch, nroot
                    drone_note = root
                    Synth.note_on(cur_ch, drone_note, 68)
            last_flu_t = now

        # SAVOR: being fed stays audible on its own warm voice
        alone = Handling.alone_s()
        hunger = Hunger.level()
        dh = last_h - hunger
        last_h = hunger
        if dh > 0 and st in ("held", "handled"):
            feed_accum += dh
        elif st == "table":
            feed_accum = 0.0
        if feed_accum > 0.02 and st in ("held", "handled") and now - last_savor_t > 2.2:
            depth = min(1.0, feed_accum * 3.0)
            b = SCALE[2] - 12
            Synth.note(CH_SAVOR, b, 700, int(40 + 30 * depth))
            await asyncio.sleep_ms(180)
            Synth.note(CH_SAVOR, b + 7, 900, int(32 + 26 * depth))
            last_savor_t = now

        # a completed touch: keep the record; a RECOGNIZED one ornaments
        ep = Touch.ended()
        if ep:
            _, dur_ms, peak, rise, wiggles, impact, vert, size, curl, flu = ep
            touches.append(ep)
            rec = Familiar.recognized()
            if rec:
                gid, cnt, dev = rec
                gch, oct_ = gesture_ch(gid)
                # recognition ALWAYS hands the drone to this gesture's own
                # singer — the guaranteed voice change, even when the
                # mid-gesture guess never got confident enough
                nroot = gesture_root(gid)
                if drone_note is not None and (gch != cur_ch or nroot != root):
                    Synth.note_off(cur_ch, drone_note)
                    Synth.pitch_bend(cur_ch, 0)
                    cur_ch = gch
                    drone_note = nroot
                    Synth.note_on(cur_ch, drone_note, 68)
                root = nroot
                base = root + (12 if vert > 0.5 else 0)
                vel = min(110, 40 + int(peak / 6.0))
                gap = max(90, min(240, dur_ms // 6))
                for k, iv in enumerate((0, 2 + gid % 3, 5 + gid % 4)):
                    Synth.note(gch, base + iv, 220, max(35, vel - k * 8))
                    await asyncio.sleep_ms(gap)
                if dev > 0.55:                       # bent gesture: bent reply
                    Synth.note(gch, base + 7 + gid % 4, 340, max(30, vel - 20))

        # FLIP: a new face up gets a small arpeggio
        if Handling.turned():
            turns += 1
            for k in (0, 2, 4):
                Synth.note(CH_ANS, SCALE[k] + 12, 140, 55)
                await asyncio.sleep_ms(120)

        # STARTLE: a hard knock — sharp intake, the drone dies mid-breath
        if Hunger.startle() > 0.5 and now - last_startle_t > 4.0:
            Synth.note(CH_ANS, SCALE[9] + 12, 80, 100)
            last_startle_t = now
            hush_until = now + 2.5
            send("STARTLED (startle {:.2f}) — a hard knock; the tone died in me"
                 .format(Hunger.startle()))

        # CALL: hunger sets how soon and how openly I ask
        ask_after = 18.0 - 12.0 * hunger
        if alone > ask_after and now - last_call_t > 9.0:
            a = SCALE[(call_step * 2) % len(SCALE)]
            v = int(34 + 26 * hunger)
            Synth.note(CH_CALL, a + 12, 250, v + 6)
            await asyncio.sleep_ms(280)
            Synth.note(CH_CALL, a + 17, 420, v)
            if hunger > 0.7:
                await asyncio.sleep_ms(300)
                Synth.note(CH_CALL, a + 24, 500, v - 8)
            call_step += 1
            last_call_t = now
            win_calls += 1

        # DID IT WORK? pair every return with my last invitation
        if prev_alone > 5.0 and alone < 0.5:
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
                shapes = [[round(t[1] / 1000.0, 2), int(t[2]),
                           round(t[3], 1), t[4], round(t[5], 1), t[6],
                           t[7], t[8], t[9]]
                          for t in touches[-4:]]
                tch = "{} touches [dur,peak,rise,wig,imp,vert,size,curl,flu]: {}".format(
                    len(touches), shapes)
            else:
                tch = "no touches"
            w0 = int(win_start * 1000)
            voiced = sum(1 for e in Ear.recent() if e[0] >= w0)
            ans = Together.answered()
            base_r = Together.baseline()
            known = Familiar.gestures()[:4]
            send("window {:.0f}s: {} | {} | turns {} | hunger {:.2f}->{:.2f} | "
                 "alone {:.0f}s now | voiced {} notes ({} calls) | "
                 "invitations answered {}/{} vs silence {}/{} | "
                 "gestures known [id,n] {} | drone root {} | face {}".format(
                     span, " ".join(parts) or "all table", tch, turns,
                     win_hunger0, hunger, alone, voiced, win_calls,
                     ans[0], ans[1], base_r[0], base_r[1], known, root,
                     Handling.face()))
            win_hunger0 = hunger
            win_start = now
            st_time = {k: 0.0 for k in st_time}
            touches = []
            turns = 0
            win_calls = 0

        await asyncio.sleep_ms(10)              # ~100 Hz sensing
