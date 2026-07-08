async def run():
    # THE FEEL GATE, v2. A strike is a wrist FLICK (gyro peak); WHERE you
    # aim picks the drum: stick pitch chooses the row (high / mid / low),
    # magnetometer heading chooses the column (left / middle / right of
    # your average facing). Nine drums in the air around you. Without a
    # mag stream it falls back to the three-row kit.
    #
    #            left        middle      right
    #   high:    crash 49    ride 51     china 52
    #   mid:     hi tom 48   snare 38    mid tom 45
    #   low:     floor 41    kick 36     low tom 43
    DRUMS = 9                       # GM drum channel: the note picks the sound
    Synth.control_change(DRUMS, 91, 45)   # a touch of room
    KIT = ((49, 51, 52),            # high row
           (48, 38, 45),            # mid row
           (41, 36, 43))            # low row

    win_start = time.ticks_ms() / 1000.0
    hits = []                       # [vigor_z, vert01] this window
    last_t = win_start

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()               # feeds Strike/Touch/Familiar/Motion
        Imu.getGyro()

        h = Strike.hit()
        if h:
            t_ms, vigor, vert, elev, head, gid = h
            # vigor = flick peak dps: gentle ~450-600, hard ~800-1500
            vel = max(35, min(120, int(35 + (vigor - 400) * 0.1)))
            row = 0 if elev > 0.35 else (2 if elev < -0.35 else 1)
            if head is None:
                col = 1                      # no mag: three-row kit
            else:
                col = 0 if head < -25 else (2 if head > 25 else 1)
            note = KIT[row][col]
            Synth.note(DRUMS, note, 150, vel)
            hits.append([vigor, elev if head is None else head])

        # REPORT every ~20 s: their playing and my sounding, side by side
        if now - win_start > 20.0:
            span = now - win_start
            if hits:
                vig = sorted(h[0] for h in hits)
                verts = [h[1] for h in hits]
                stats = ("{} hits ({:.1f}/s) | vigor med {:.1f} max {:.1f} | "
                         "aim {}".format(
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
