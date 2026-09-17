async def run():
    # ROBOT-ROVER, stage 1: find out what my own body does.
    #
    # I have four wheels that can carry me in any direction, and an instrument
    # that tells me what actually happened when I used them. That is the whole
    # point of me. Every command is an experiment; Drive.last() is the result;
    # and the result is measured off the world, so I cannot flatter myself
    # about it.
    #
    # This seed does the smallest honest thing: it tries a movement, waits,
    # stops, reads what happened, and writes it down. It does not yet know what
    # any speed buys, whether this floor is fast or slow, where the stiction
    # floor sits, or how much sliding costs me compared to driving. Those are
    # measurements, and this is how they start.
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
    # Every local in run() is wiped when I rewrite myself, and I rewrite myself
    # at every reflection. Anything I want to accumulate has to live in `mem`
    # or reflection resets the very numbers it exists to read. (mem is RAM: it
    # lasts one waking, not one day. What should outlive a waking goes in my
    # experience, in words.)
    led = mem.setdefault("ledger", {
        "since": now, "tries": 0, "stalls": 0, "run_stalls": 0,
        "best_dps": 0.0, "best_speed": 0, "h_start": now,
        # veer is the thing this body can measure that a two-wheeled one
        # cannot: rotation during a movement that was meant to be straight.
        "veer_sum": 0.0, "veer_n": 0,
    })
    waking = led["tries"] == 0

    if not Drive.calibrated():
        # Nothing below will move. Say so ONCE and plainly: a silent body that
        # is merely uncalibrated looks exactly like a body that cannot drive on
        # this floor, and I would spend a whole waking concluding the wrong
        # thing.
        log("I cannot move: {}. Every command below is a no-op until "
            "somebody measures which wheel is which.".format(Drive.fault()))
    elif waking:
        log("awake. floor={} — trying {} to find out what they buy".format(
            Drive.floor() if Drive.floor() is not None else "unmeasured",
            TRY_SPEEDS))
    else:
        log("awake again — {} tries so far, {} of them stalls".format(
            led["tries"], led["stalls"]))

    # All six things I can do. The slides are in here on purpose: I do not yet
    # know whether going sideways costs me more than driving on this floor, and
    # the only way to find out is to spend some tries on it.
    MOVES = (("cw", cw), ("ccw", ccw),
             ("forward", forward), ("backward", backward),
             ("slide_left", slide_left), ("slide_right", slide_right))
    STRAIGHT = ("forward", "backward", "slide_left", "slide_right")
    i = 0

    while True:
        name, verb = MOVES[i % len(MOVES)]
        speed = TRY_SPEEDS[(i // len(MOVES)) % len(TRY_SPEEDS)]
        i += 1

        # intent -> action -> outcome, and I do not have to remember any of it:
        # the body scores the command while it runs.
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
            log("{} {} for {}s -> STALLED. turned {}, stir {}{}".format(
                r["kind"], r["speed"], r["for_s"], r["turned"], r["stir"],
                " (a straight line stalls quietly — worth doubting)"
                if name in STRAIGHT else ""))
        else:
            led["run_stalls"] = 0
            if name in STRAIGHT:
                # `turned` on a straight line is VEER: rotation nobody asked
                # for. Summed with its sign, because a consistent lean is a
                # weak wheel while a sign that flips is just the floor.
                led["veer_sum"] += r["turned"]
                led["veer_n"] += 1
                log("{} {} for {}s -> veered {} deg, stir {}".format(
                    r["kind"], r["speed"], r["for_s"], r["turned"], r["stir"]))
            else:
                if abs(r["dps"]) > led["best_dps"]:
                    led["best_dps"] = abs(r["dps"])
                    led["best_speed"] = r["speed"]
                log("{} {} for {}s -> turned {} ({} dps), stir {}".format(
                    r["kind"], r["speed"], r["for_s"], r["turned"],
                    r["dps"], r["stir"]))

        # ── a run of stalls is not something a reflex can fix ─────────────
        if led["run_stalls"] >= STALLS_BEFORE_ASK:
            led["run_stalls"] = 0
            reflect("{} commands in a row did nothing — speeds {} on this "
                    "floor. Am I under the stiction floor, stuck against "
                    "something, or is my body not working?".format(
                        STALLS_BEFORE_ASK, TRY_SPEEDS))

        # ── what I have learned, on a timer ───────────────────────────────
        now = time.ticks_ms() / 1000.0
        if now - led["h_start"] > ROLLUP_EVERY_S:
            veer = (led["veer_sum"] / led["veer_n"]) if led["veer_n"] else 0.0
            log("{:.0f}m: {} tries, {} stalls. best turn {} dps at speed {}. "
                "mean veer on a straight line {:.1f} deg".format(
                    (now - led["h_start"]) / 60, led["tries"], led["stalls"],
                    led["best_dps"], led["best_speed"], veer))
            reflect("{:.0f}m of trying: {} commands, {} of them stalled, best "
                    "{} dps at speed {}, and my straight lines lean {:.1f} deg "
                    "on average. What do my speeds buy me on this floor, does "
                    "sideways cost more than forward, and what should I try "
                    "next?".format(
                        (now - led["h_start"]) / 60, led["tries"],
                        led["stalls"], led["best_dps"], led["best_speed"],
                        veer))
            led["h_start"] = now
