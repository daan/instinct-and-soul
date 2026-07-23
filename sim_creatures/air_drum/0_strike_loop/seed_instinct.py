async def run():
    # THE FEEL GATE, v4. A strike is a wrist FLICK (gyro peak); WHICH WAY
    # the flick swings picks the drum — five strokes, five drums, decided
    # per hit from the flick's own rotation axis. Nothing to settle, no
    # posture memory: a stroke IS its drum.
    # (v3 picked drums from held stick pitch — worked for deliberate play,
    # but a wrist mid-flight between drums has no posture, so every switch
    # at tempo misfired. v2's magnetometer column measured the arm's swing
    # arc, not the aim. Both retired on session evidence, 2026-07-09.)
    #
    # Stroke azimuth calibrated on the 10x5 labeled session 20260709_122741
    # (clusters +-3..6 deg, narrowest gap 8 deg — UP|FLAT):
    #   fwd-UP   -100  -> closed hat 42     fwd-FLAT  -83  -> snare 38
    #   LEFT      +10  -> high tom 48       fwd-DOWN  +82  -> kick 36
    #   RIGHT    +170  -> crash 49
    DRUMS = 9                       # GM drum channel: the note picks the sound
    Synth.control_change(DRUMS, 91, 45)   # a touch of room

    def drum_for(az):
        if az is None:
            return 38               # axis unreadable: default snare
        if -93 <= az < -39:
            return 38               # fwd-FLAT -> snare
        if -39 <= az < 45:
            return 48               # LEFT     -> high tom
        if 45 <= az < 123:
            return 36               # fwd-DOWN -> kick
        if az >= 123 or az < -142:
            return 49               # RIGHT    -> crash
        return 42                   # fwd-UP   -> closed hat

    win_start = time.ticks_ms() / 1000.0
    hits = []                       # [vigor, stroke_az] this window
    last_t = win_start

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()               # feeds Strike/Touch/Familiar/Motion
        Imu.getGyro()

        h = Strike.hit()
        if h:
            t_ms, vigor, vert, elev, az, tilt, gid = h
            # vigor = flick peak dps: gentle ~450-600, hard ~800-1500
            vel = max(35, min(120, int(35 + (vigor - 400) * 0.1)))
            Synth.note(DRUMS, drum_for(az), 150, vel)
            hits.append([vigor, az])

        # REPORT every ~20 s: their playing and my sounding, side by side
        if now - win_start > 20.0:
            span = now - win_start
            if hits:
                vig = sorted(h[0] for h in hits)
                azs = [h[1] for h in hits]
                stats = ("{} hits ({:.1f}/s) | vigor med {:.1f} max {:.1f} | "
                         "strokes {}".format(
                             len(hits), len(hits) / span, vig[len(vig) // 2],
                             vig[-1], azs[-8:]))
            else:
                stats = "no hits"
            send("window {:.0f}s: {} | swings known [id,n] {} | state {} "
                 "alone {:.0f}s | fluency {:.2f}".format(
                     span, stats, Familiar.gestures()[:4], Handling.state(),
                     Handling.alone_s(), Motion.fluency()))
            win_start = now
            hits = []

        await asyncio.sleep_ms(5)   # 200 Hz polling: the hit waits for no one
