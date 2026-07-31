async def run():
    # ROBOT-BUG, stage 1: find out what my own body does.
    #
    # I have four wheels and an instrument that tells me what actually
    # happened when I used them. That is the whole point of me. Every command
    # is an experiment; Drive.last() is the result; and the result is measured
    # off the world, so I cannot flatter myself about it.
    #
    # This seed does the smallest honest thing: it tries a movement, waits,
    # stops, reads what happened, and writes it down. It does not yet know
    # what any speed buys, whether this floor is fast or slow, or where the
    # stiction floor sits. Those are measurements, and this is how they start.
    #
    # send() only writes to the record. reflect(reason) is the ONE call that
    # summons me to think, and it costs. I ask when something changed that I
    # cannot resolve from in here.

    HOLD_S = 1.2             # how long a movement runs before I stop and look.
                             # Long enough for the gyro to have something to
                             # say (a turn needs time), short enough that a
                             # stall is not a long shove against a chair leg.
    REST_S = 1.0             # settle before the next one: the gyro is smoothed
                             # over ~0.3 s and I do not want the tail of one
                             # movement inside the next one's score.
    TRY_SPEEDS = (30, 45, 60)  # first guesses, deliberately spanning what I
                             # expect to be either side of the stiction floor.
                             # If 30 always stalls and 45 never does, the floor
                             # is between them, and that is worth knowing.
    STALLS_BEFORE_ASK = 3    # this many stalls in a row and something is wrong
                             # that a reflex cannot fix — an uncalibrated body,
                             # a floor I cannot drive on, a flat battery
    ROLLUP_EVERY_S = 600.0   # what I have learned so far, out loud

    def clock():
        t = time.localtime()
        if t[0] >= 2020:
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def log(msg):
        send("{} {}".format(clock(), msg))

    now = time.ticks_ms() / 1000.0

    # ── the ledger: the one thing that survives my own rewrites ───────────
    # Every local in run() is wiped when I rewrite myself, and I rewrite
    # myself at every reflection. Anything I want to accumulate has to live
    # in Mem or reflection resets the very numbers it exists to read.
    # (Mem is RAM: it lasts one waking, not one day. What should outlive a
    # waking goes in my experience, in words.)
    LEDGER = "ledger"
    led = Mem.latest(LEDGER)
    waking = led is None
    if waking:
        led = {"since": now, "tries": 0, "stalls": 0, "run_stalls": 0,
               "best_dps": 0.0, "best_speed": 0, "h_start": now}
    else:
        led = dict(led)

    def flush():
        Mem.push(LEDGER, dict(led), 1)

    if not Drive.calibrated():
        # Nothing below will move. Say so ONCE and plainly: a silent body
        # that is merely uncalibrated looks exactly like a body that cannot
        # drive on this floor, and I would spend a whole waking concluding
        # the wrong thing.
        log("I cannot move: nobody has measured which wheel is which. "
            "Every command below is a no-op until they do.")
    elif waking:
        log("awake. floor={} — trying {} to find out what they buy".format(
            Drive.floor() if Drive.floor() is not None else "unmeasured",
            TRY_SPEEDS))
    else:
        log("awake again — {} tries so far, {} of them stalls".format(
            led["tries"], led["stalls"]))
    flush()

    MOVES = (("cw", cw), ("ccw", ccw), ("forward", forward),
             ("backward", backward))
    i = 0

    while True:
        name, verb = MOVES[i % len(MOVES)]
        speed = TRY_SPEEDS[(i // len(MOVES)) % len(TRY_SPEEDS)]
        i += 1

        # intent -> action -> outcome, and I do not have to remember any of
        # it: the body scores the command while it runs.
        verb(speed)
        await asyncio.sleep(HOLD_S)
        stop()
        await asyncio.sleep(REST_S)

        r = Drive.last()
        if r is None:
            # Only reachable if the command was too short to score, which
            # HOLD_S should prevent — so if this appears, HOLD_S is wrong.
            log("{} {} — no reading came back".format(name, speed))
            continue

        led["tries"] += 1
        if r["stalled"]:
            led["stalls"] += 1
            led["run_stalls"] += 1
            log("{} {} for {}s -> STALLED. turned {}, stir {}".format(
                r["kind"], r["speed"], r["for_s"], r["turned"], r["stir"]))
        else:
            led["run_stalls"] = 0
            if r["dps"] > led["best_dps"]:
                led["best_dps"] = r["dps"]
                led["best_speed"] = r["speed"]
            log("{} {} for {}s -> turned {} ({} dps), stir {}".format(
                r["kind"], r["speed"], r["for_s"], r["turned"],
                r["dps"], r["stir"]))
        flush()

        # ── a run of stalls is not something a reflex can fix ─────────────
        if led["run_stalls"] >= STALLS_BEFORE_ASK:
            led["run_stalls"] = 0
            flush()
            reflect("{} commands in a row did nothing — speeds {} on this "
                    "floor. Am I under the stiction floor, stuck against "
                    "something, or is my body not working?".format(
                        STALLS_BEFORE_ASK, TRY_SPEEDS))

        # ── what I have learned, on a timer ───────────────────────────────
        now = time.ticks_ms() / 1000.0
        if now - led["h_start"] > ROLLUP_EVERY_S:
            log("{:.0f}m: {} tries, {} stalls. best so far {} dps at "
                "speed {}".format((now - led["h_start"]) / 60, led["tries"],
                                  led["stalls"], led["best_dps"],
                                  led["best_speed"]))
            reflect("{:.0f}m of trying: {} commands, {} of them stalled, best "
                    "{} dps at speed {}. What do my speeds buy me on this "
                    "floor, and what should I try next?".format(
                        (now - led["h_start"]) / 60, led["tries"],
                        led["stalls"], led["best_dps"], led["best_speed"]))
            led["h_start"] = now
            flush()
