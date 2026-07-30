"""Seed instinct for 3_interaction: a timid Braitenberg vehicle on the
thermal gradient. Drawn toward a warm shape at a distance, holds a boundary
when it gets close, backs off when the shape closes fast, settles when it
arrives gently.

This is deliberately the SIMPLEST honest coupling, not a good creature. The
arc of this stage is that it begins as a Braitenberg vehicle and gets
rewritten, phrase by phrase, into something that co-performs. Everything
below is yours to replace.

Two disciplines it does keep, and that a rewrite should keep:

  THE EFFERENCE GATE. The thermal centroid sloshes and the nose beam pitches
  while the legs are moving, so a range reading taken mid-stride is not news
  about the world. Percepts are only trusted after the legs have been still
  for SETTLE_MS. This is why the body moves, then looks — like a dog.

  send() IS FREE, reflect() IS NOT. Every cycle is journalled. The soul is
  summoned only when the situation genuinely changed: a zone crossing, an
  arrival, or a bid that went unanswered long enough to matter.

It also journals the raw material for the two measurements this stage is
blocked on (mm/cycle and deg/cycle — see README): every move reports the
cycles commanded and the range change observed while still. Those lines are
the measurement; nothing else can be attributed until they add up.
"""


async def run():
    # Zone boundaries in mm along the nose beam. GUESSES, drafted for a
    # tabletop and a hand — not measured on this body (README missing item 6).
    # Anything built on them inherits that uncertainty.
    INTIMATE_MM = 150
    PERSONAL_MM = 400
    SOCIAL_MM = 900

    SETTLE_MS = 400      # legs still this long before a percept is trusted
    LOOK_MS = 700        # how long to stand and look between moves
    MOVE_CYCLES = 1.5    # stride cycles per move — short phrases, then look
    PACE = 0.7           # inside the organ's envelope; turning gets less
    CENTRED_PX = 6       # blob within this of frame centre counts as ahead
    PATIENCE_S = 25      # nothing answered for this long is worth a thought

    def zone(mm, present):
        if not present or mm is None or mm <= 0 or mm > SOCIAL_MM:
            return "away"
        if mm < INTIMATE_MM:
            return "intimate"
        if mm < PERSONAL_MM:
            return "personal"
        return "social"

    async def look():
        """Stand still until the senses are trustworthy, then read them."""
        Legs.stop()
        while Legs.since_still_ms() < SETTLE_MS:
            await asyncio.sleep_ms(50)
        await asyncio.sleep_ms(LOOK_MS - SETTLE_MS if LOOK_MS > SETTLE_MS else 0)
        return Thermal.blob(), ToF.read_distance_mm()

    async def move(mode, pace, cycles):
        """One short phrase of motion, then stop. Returns the cycles actually
        commanded — the efference half of every later attribution."""
        if mode == "forward":
            Legs.forward(pace)
        elif mode == "back":
            Legs.back(pace)
        else:
            Legs.turn(mode, pace)
        while Legs.cycles() < cycles:
            if Legs.tipped():
                break            # the organ already stopped us and said so
            await asyncio.sleep_ms(50)
        done = Legs.cycles()
        Legs.stop()
        return done

    send("seed: timid vehicle on the thermal gradient, zones "
         "{}/{}/{}mm (unmeasured)".format(INTIMATE_MM, PERSONAL_MM, SOCIAL_MM))

    last_zone = None
    arrived_from = None      # the zone we came FROM, so an arrival can be told
                             # from having merely been here all along
    last_answer_ms = time.ticks_ms()
    asked_about_silence = False

    while True:
        b, mm = await look()
        z = zone(mm, b["present"])
        area = b["area"]
        cx = b["cx"]

        send("scene {} tof={} area={} exc={:.1f} cx={:.1f} legs={}".format(
            z, mm, area, b["excess_c"], cx, Legs.mode()))

        if z != last_zone:
            # The world changed. This is the one moment worth a reflection —
            # not the steady watching in between.
            if last_zone is not None:
                reflect("we crossed from {} to {} (nose {}mm, warm area {}). "
                        "I do not know whether they moved or I did.".format(
                            last_zone, z, mm, area))
            arrived_from = last_zone
            last_zone = z
            last_answer_ms = time.ticks_ms()
            asked_about_silence = False

        if z == "away":
            # Solo life. Deliberately dull: being ignored only means something
            # if attention was the alternative, and a busy creature gives the
            # human the first move to interrupt.
            before = mm
            n = await move("forward", PACE * 0.6, MOVE_CYCLES)
            _b2, after = await look()
            send("wandered {:.2f} cycles, nose {} -> {} (mm/cycle unmeasured; "
                 "this line is the measurement)".format(n, before, after))

        elif z == "social":
            # Braitenberg 2a: turn toward the warmth, then close.
            if abs(cx - Thermal.CENTRE_X) > CENTRED_PX:
                d = "ccw" if cx < Thermal.CENTRE_X else "cw"
                n = await move(d, PACE * 0.6, 1.0)
                send("faced {} {:.2f} cycles (deg/cycle unmeasured)".format(d, n))
            else:
                before = mm
                n = await move("forward", PACE, MOVE_CYCLES)
                _b2, after = await look()
                send("approached {:.2f} cycles, nose {} -> {} (closed {})".format(
                    n, before, after, (before - after) if before and after else "?"))
                if after and before and after < before - 20:
                    last_answer_ms = time.ticks_ms()

        elif z == "personal":
            # The boundary. Hold it — this is where a timid vehicle stops, and
            # where a later rewrite might decide to be bolder or shyer.
            if arrived_from == "social":
                # Arrived gently, under my own steam: wag once. Fire and
                # forget — an expressive move that expects no answer, so no
                # outcome is measured and none should be claimed.
                send("arrived gently at the boundary, nose {}mm — wagging".format(mm))
                await Legs.wiggle(amp=18, cycles=2.0)
            else:
                send("holding at the boundary, nose {}mm".format(mm))
                await asyncio.sleep_ms(600)

        else:   # intimate
            # Too close. Open the distance; the retreat is also a bid.
            before = mm
            n = await move("back", PACE, MOVE_CYCLES)
            _b2, after = await look()
            send("withdrew {:.2f} cycles, nose {} -> {}".format(n, before, after))

        quiet_s = time.ticks_diff(time.ticks_ms(), last_answer_ms) / 1000.0
        if quiet_s > PATIENCE_S and not asked_about_silence:
            asked_about_silence = True
            reflect("{:.0f}s in {} with nothing changing — my moves are not "
                    "getting answered, or there is nobody there. I cannot tell "
                    "which from what I can sense.".format(quiet_s, z))
