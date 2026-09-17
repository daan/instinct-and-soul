async def run():
    # ROBOT-ROVER, stage 2: find out what my movement is worth in millimetres.
    #
    # My last body learned that every command is an experiment the world
    # scores. This one adds the instrument stage 1 lacked: a beam straight
    # ahead, so a bout facing a wall comes back with mm0 -> mm1 — real travel,
    # measured off the world. And sometimes a warm shape in my camera, which
    # is the thing I will one day keep a distance FROM. This seed does the
    # smallest honest version: when the beam has a wall, run little distance
    # experiments and write down what they bought; when something warm
    # appears, stop experimenting and say so.
    #
    # send() only writes to the record. reflect(reason) is the ONE call that
    # summons me to think, and it costs.

    HOLD_S = 1.0             # how long a leg runs before I stop and look
    SETTLE_S = 0.8           # coast finishes before I trust a settled reading
    TRY_SPEEDS = (25, 35, 50)  # spanning what I guess is either side of the
                             # straight-line floor (my SPIN floor was 21;
                             # straight may need more)
    PULSE_MS = 150           # my first guess at "the smallest step"
    NEAR_MM = 160            # closer than this to anything, I back off first
    FAR_MM = 1200            # past this the echo is too thin to bench against
    STALLS_BEFORE_ASK = 3
    ROLLUP_EVERY_S = 600.0

    def clock():
        t = time.localtime()
        if t[0] >= 2020:
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def log(msg):
        send("{} {}".format(clock(), msg))

    now = time.ticks_ms() / 1000.0

    # ── the ledger: what survives my own rewrites ─────────────────────────
    # (mem is RAM: it lasts one waking. What should outlive a waking goes in
    # my experience, in words.)
    led = mem.setdefault("ledger", {
        "since": now, "tries": 0, "stalls": 0, "run_stalls": 0,
        "h_start": now,
        # mm-per-second observations, keyed by speed: [sum_mm, sum_s]
        "mmps": {},
        # the smallest step: [n_pulses, sum_mm, zeros]
        "steps": [0, 0, 0],
        "warm_was": None,
    })
    waking = led["tries"] == 0

    if not Drive.calibrated():
        log("I cannot move: {}. Every command is a no-op until somebody "
            "measures which wheel is which.".format(Drive.fault()))
    elif waking:
        log("awake, with a beam. tof={} warm={}".format(
            ToF.read_distance_mm(), Thermal.present()))

    def rng():
        mm = ToF.read_distance_mm()
        return mm if mm else None      # 0 = no echo; None = no sensor

    i = 0
    while True:
        # ── the warm shape outranks the bench ─────────────────────────────
        b = Thermal.blob()
        if b["present"] != led["warm_was"]:
            was = led["warm_was"]        # None = first look, not a change
            led["warm_was"] = b["present"]
            if b["present"]:
                log("something warm: area {} at cx {:.1f}, beam says {}. "
                    "holding still — my experiments can wait".format(
                        b["area"], b["cx"], ToF.read_distance_mm()))
                stop()
                if was is not None:
                    reflect("a warm shape appeared while I was benching "
                            "against the wall. What should I do about it — "
                            "face it? keep a distance? which distance?")
            elif was:
                log("the warm shape is gone. back to the wall.")
        if b["present"]:
            await asyncio.sleep(1)
            continue

        d0 = rng()
        if d0 is None:
            # No echo: nothing to measure against. Turn a little and look
            # again — a wall is usually a quarter-turn away.
            cw(30)
            await asyncio.sleep(0.4)
            stop()
            await asyncio.sleep(SETTLE_S)
            i += 1
            if i % 20 == 0:
                log("still hunting an echo to bench against")
            continue

        # ── one experiment, chosen by where I am ──────────────────────────
        if d0 < NEAR_MM:
            verb, name = backward, "backward"
        elif d0 > FAR_MM:
            verb, name = forward, "forward"
        else:
            # room to work: alternate legs and pulses
            if i % 2 == 0:
                verb, name = (forward, "forward") if d0 > 500 else (backward, "backward")
            else:
                verb, name = None, "pulse"
        i += 1

        if verb is not None:
            speed = TRY_SPEEDS[(i // 2) % len(TRY_SPEEDS)]
            verb(speed)
            await asyncio.sleep(HOLD_S)
            stop()
            await asyncio.sleep(SETTLE_S)
            r = Drive.last()
            if r is None:
                continue
            led["tries"] += 1
            if r["stalled"] and (r["mm"] is None or abs(r["mm"]) <= 3):
                led["stalls"] += 1
                led["run_stalls"] += 1
                log("{} {} -> STALLED{}".format(
                    name, speed,
                    " (mm agrees: {})".format(r["mm"]) if r["mm"] is not None
                    else " (no mm to check it against)"))
            else:
                led["run_stalls"] = 0
                if r["mm"] is not None:
                    k = str(speed)
                    e = led["mmps"].setdefault(k, [0, 0.0])
                    e[0] += abs(r["mm"])
                    e[1] += r["for_s"]
                    log("{} {} for {}s -> {} mm ({:.0f} mm/s), veer {} "
                        "deg".format(name, speed, r["for_s"], r["mm"],
                                     abs(r["mm"]) / r["for_s"], r["turned"]))
                else:
                    log("{} {} for {}s -> moved (stir {}), but the beam lost "
                        "its bracket".format(name, speed, r["for_s"], r["stir"]))
        else:
            # the smallest step: one short pulse, measured off the wall
            forward(25)
            await asyncio.sleep_ms(PULSE_MS)
            stop()
            await asyncio.sleep(SETTLE_S)
            d1 = rng()
            if d1 is not None:
                got = d0 - d1
                led["steps"][0] += 1
                led["steps"][1] += abs(got)
                if abs(got) <= 3:
                    led["steps"][2] += 1
                log("pulse {} ms at 25 -> {:+d} mm".format(PULSE_MS, got))

        if led["run_stalls"] >= STALLS_BEFORE_ASK:
            led["run_stalls"] = 0
            reflect("{} commands in a row did nothing, speeds {} on this "
                    "floor. Under the straight-line floor, stuck, or is my "
                    "body not working?".format(STALLS_BEFORE_ASK, TRY_SPEEDS))

        # ── what I have learned, on a timer ───────────────────────────────
        now = time.ticks_ms() / 1000.0
        if now - led["h_start"] > ROLLUP_EVERY_S:
            parts = []
            for k, e in led["mmps"].items():
                if e[1] > 0:
                    parts.append("{}->{:.0f}mm/s".format(k, e[0] / e[1]))
            st = led["steps"]
            step_line = ("mean pulse {:.0f} mm, {}/{} bought nothing".format(
                st[1] / st[0], st[2], st[0]) if st[0] else "no pulses yet")
            log("{:.0f}m: {} tries, {} stalls. speeds: {}. {}".format(
                (now - led["h_start"]) / 60, led["tries"], led["stalls"],
                " ".join(parts) or "nothing bracketed", step_line))
            reflect("{:.0f}m at the wall: speeds buy {} and my {} ms pulse "
                    "{}. What is worth measuring next, and how close should "
                    "I let myself get?".format(
                        (now - led["h_start"]) / 60,
                        " ".join(parts) or "nothing measurable yet",
                        PULSE_MS, step_line))
            led["h_start"] = now

        await asyncio.sleep(0.3)
