async def run():
    # THE FEEL GATE. A hit must be indistinguishable from striking a MIDI
    # pad: the instant the wrist snaps, a drum sounds. Three fixed drums by
    # the swing's direction, velocity from how hard — nothing else. No
    # melody, no coaching, no cleverness: everything this creature may ever
    # become stands on this feeling right.
    #   downward chop          -> snare (38); very hard -> kick (36)
    #   sideways sweep         -> closed hat (42); very hard -> crash (49)
    #   in between             -> low tom (45)
    DRUMS = 9                       # GM drum channel: the note picks the sound
    Synth.control_change(DRUMS, 91, 45)   # a touch of room

    win_start = time.ticks_ms() / 1000.0
    hits = []                       # [vigor_z, vert01] this window
    last_t = win_start

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()               # feeds Strike/Touch/Familiar/Motion
        Imu.getGyro()

        h = Strike.hit()
        if h:
            t_ms, vigor, vert, rot, gid = h
            vel = min(127, 45 + int(vigor * 9))
            if vert >= 0.55:
                note = 36 if vigor >= 9.0 else 38
            elif vert <= 0.35:
                note = 49 if vigor >= 9.0 else 42
            else:
                note = 45
            Synth.note(DRUMS, note, 150, vel)
            hits.append([vigor, vert])

        # REPORT every ~20 s: their playing and my sounding, side by side
        if now - win_start > 20.0:
            span = now - win_start
            if hits:
                vig = sorted(h[0] for h in hits)
                verts = [h[1] for h in hits]
                stats = ("{} hits ({:.1f}/s) | vigor med {:.1f} max {:.1f} | "
                         "vert dist {}".format(
                             len(hits), len(hits) / span, vig[len(vig) // 2],
                             vig[-1],
                             [round(v, 1) for v in verts[-8:]]))
            else:
                stats = "no hits"
            send("window {:.0f}s: {} | swings known [id,n] {} | state {} "
                 "alone {:.0f}s | fluency {:.2f}".format(
                     span, stats, Familiar.gestures()[:4], Handling.state(),
                     Handling.alone_s(), Motion.fluency()))
            win_start = now
            hits = []

        await asyncio.sleep_ms(5)   # 200 Hz polling: the hit waits for no one
