"""
recipes.py — instinct templates for the robot-rover 2_perception tuner.

This body is an M5StickS3 on an M5Stack RoverC — four MECANUM wheels behind an
STM32 at I2C 0x38 — now with senses: a VL53L0X ToF beam (0x29) and, when
fitted, the M5 Thermal2 camera (0x32). Stage 1's calibration recipes are all
still here (motors, floor, spin, straight, slide, box, square, drive) and its
calibration carries over in lib/drive.py.

WHAT THIS STAGE ADDS: DISTANCE. Stage 1 measured rotation and only witnessed
translation. The beam changes that — point this body at a WALL and every
straight-line command becomes measurable in millimetres. The wall bench is a
set of recipes built on exactly that:

  `scan`    — both buses now: the rover at 0x38, and whichever bus the
              sensors turn out to be plugged into. Still first, every session.
  `tof`     — is the beam alive, and what does it say about a hand?
  `blob`    — both senses at rest: the thermal noise floor, blob-vs-distance.
  `wall`    — forward and backward legs against the wall: mm travelled,
              mm/s this speed actually buys, and the coast after stop.
  `step`    — the SMALLEST move this body can make: short pulses, mm each,
              and how repeatable. The number every slow behaviour needs.
  `vfloor`  — the straight-line stiction floor, at last measured rather than
              inferred (the measured floor=21 was a SPIN floor).
  `hold`    — keep a distance to the wall, closed-loop: the achievable
              accuracy and the oscillation, before a human ever stands in.
  `face`    — turn to hold the warm shape at frame centre: the turning side
              of the same question.

THE KEY QUESTION this bench answers: this body cannot move slowly or
accurately — so what CAN it do? Between the straight-line floor, the mm one
pulse buys, and the coast, the deadband any keep-distance behaviour must
tolerate stops being a guess.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
Recipes with no args are sent verbatim, so single braces are fine there.
"""

INSTINCT_IDLE = """
async def run():
    stop()
    send("idle: robot-rover 2_perception tuner")
    while True:
        b = Thermal.blob()
        send("yaw {:.1f} dps | stir {:.3f} | tof {} | warm {} | commanded {} "
             "| calibrated {} ({})".format(
                 Drive.rot(), Drive.stir(), ToF.read_distance_mm(),
                 b["area"] if b["present"] else "-", Drive.commanded(),
                 Drive.calibrated(), Drive.fault() or "ok"))
        await asyncio.sleep(2)
"""

RECIPES = {
    "scan": {
        "args": [],
        "code": """
async def run():
    # WHO IS HOME, ON WHICH BUS? Scans BOTH buses and names what answered:
    # the RoverC's STM32 at 0x38 on the HAT bus, the ToF at 0x29 and the
    # Thermal2 at 0x32 on whichever bus their Grove plug turns out to reach.
    # The chassis Grove ports and the stick's own Grove port are different
    # wiring, and this is the recipe that settles which one you plugged into
    # — no schematic reading required.
    #
    # RUN THIS FIRST, EVERY SESSION. The rover has its OWN POWER SWITCH and
    # its own battery: with it off, the stick boots happily on USB, wifi
    # comes up, the tuner connects, every command is accepted — and nothing
    # moves. No 0x38 means nobody is listening, and no calibration fixes it.
    # Likewise a missing 0x29 here means every distance recipe below will
    # shrug, and the fix is a plug, not code.
    #
    # NOTE the runtime binds each sensor at BOOT: a sensor plugged in after
    # power-on will show up here but stay unbound until the stick reboots.
    stop()
    NAMES = {0x38: "RoverC", 0x29: "ToF", 0x32: "Thermal2"}
    send("scan: both buses. want 0x38 (rover), 0x29 (ToF), 0x32 (thermal).")
    while True:
        for label, bus in (("hat", i2c_hat), ("grove", i2c_grove)):
            try:
                found = bus.scan()
            except Exception as e:
                send("scan {}: BUS ERROR {} — the pins themselves are "
                     "unhappy".format(label, e))
                continue
            if not found:
                send("scan {}: nobody".format(label))
            else:
                send("scan {}: {}".format(label, ", ".join(
                    "{} ({})".format(hex(a), NAMES.get(a, "?"))
                    for a in found)))
        if ToF.read_distance_mm() is None:
            send("scan: runtime has NO ToF bound — if 0x29 just appeared "
                 "above, reboot the stick to bind it")
        await asyncio.sleep(3)
""",
    },
    "joy": {
        "args": [],
        "code": """
async def run():
    # THE OPERATOR HAS THE WHEEL. Deployed when the tuner enters joystick
    # mode: this instinct does not drive at all. The motors are written by
    # the runtime's CTL: handler, straight from your keystrokes, without
    # swapping any code — so there is nothing here to fight with.
    #
    # What it does instead is WATCH. Every latched segment you drive is a
    # bout like any other, scored the same way, so driving the rover around
    # by hand produces exactly the record a recipe would: what you asked
    # for, how far it really turned, how much it shook, and whether it went
    # nowhere. Steering by feel and measuring are the same act here.
    stop()
    send("joystick: the operator has the wheel. I only watch and score.")
    while True:
        r = Drive.last()
        if r:
            mm = ""
            if r["mm"] is not None:
                mm = ", gap {:+d} mm ({}->{})".format(r["mm"], r["mm0"], r["mm1"])
            send("{} {} for {}s -> turned {} ({} dps), stir {}{}{}".format(
                r["kind"], r["speed"], r["for_s"], r["turned"], r["dps"],
                r["stir"], mm, " STALL" if r["stalled"] else ""))
        await asyncio.sleep(0.2)
""",
    },
    "motors": {
        "args": [("speed", int, 60), ("secs", float, 1.5)],
        "code": """
async def run():
    # WHICH WHEEL IS WHICH. Spins ONE motor index at a time at {speed} for
    # {secs}s, announcing each before it moves.
    #
    # Put the rover ON A BOOK or a mug so the wheels spin free — you are
    # reading the wheels, not driving the body. For each index write down:
    #   * which CORNER turned         -> its MOTOR_CORNER entry: FL FR BL BR
    #   * whether it turned FORWARD   -> its MOTOR_SIGN entry: +1 or -1
    #
    # "Forward" means the direction that would carry the rover nose-first if
    # every wheel did it. Two wheels are mounted mirrored, so expect two of
    # the four signs to come out negative.
    #
    # WHILE YOU ARE DOWN THERE, look at the rollers from above. On a mecanum
    # base they must form an X — front-left and back-right leaning one way,
    # front-right and back-left the other. A diamond will drive and turn fine
    # and will never strafe, and no calibration fixes it.
    #
    # Then put both 4-tuples into lib/drive.py and reflash lib/. This recipe
    # writes the motors directly, bypassing the verbs, because the verbs
    # refuse to move until exactly this is known.
    # And the rover's own POWER SWITCH must be ON. Off, this recipe runs
    # perfectly and reports every index while nothing turns — run `scan`
    # first and see 0x38 answer before you believe anything here.
    send("motors: rover ON A BOOK, wheels free, POWER ON. "
         "one index at a time.")
    await asyncio.sleep(2)

    def poke(b):
        # Reported, not raised: a rover that is switched off answers nothing,
        # and an OSError here would kill the recipe mid-round instead of
        # telling you the one thing you need to know.
        try:
            i2c_hat.writeto_mem(0x38, 0x00, struct.pack("bbbb", *b))
            return True
        except Exception as e:
            send("no answer at 0x38 ({{}}) — is the rover's power switch "
                 "on?".format(e))
            return False

    while True:
        for idx in range(4):
            send("--- index {{}}: POSITIVE {speed} — which corner, which way? "
                 "---".format(idx))
            b = [0, 0, 0, 0]
            b[idx] = {speed}
            if not poke(b):
                await asyncio.sleep(2)
                continue
            await asyncio.sleep({secs})
            poke([0, 0, 0, 0])
            await asyncio.sleep(1.5)
        send("=== round done. `off` to stop, or watch it again ===")
        await asyncio.sleep(2)
""",
    },
    "raw": {
        "args": [("m0", int, 0), ("m1", int, 0), ("m2", int, 0), ("m3", int, 0),
                 ("secs", float, 1.5)],
        "code": """
async def run():
    # FOUR BYTES, STRAIGHT AT THE HARDWARE: {m0} {m1} {m2} {m3} for {secs}s,
    # then off. No mixer, no calibration gate, no scoring — the one way to
    # test a corner map you have worked out on paper before you commit it to
    # lib/drive.py, and the way to ask "is this bus alive at all?" without
    # believing anything about the wheels.
    #
    # Off a book, this WILL drive the body. Watch it.
    send("raw {m0} {m1} {m2} {m3} for {secs}s")

    def poke(b):
        try:
            i2c_hat.writeto_mem(0x38, 0x00, struct.pack("bbbb", *b))
            return True
        except Exception as e:
            send("no answer at 0x38 ({{}}) — is the rover's power switch "
                 "on?".format(e))
            return False

    while True:
        if poke([{m0}, {m1}, {m2}, {m3}]):
            await asyncio.sleep({secs})
            poke([0, 0, 0, 0])
            send("...off. yaw was {{:.1f}} dps at the end, stir {{:.3f}}".format(
                Drive.rot(), Drive.stir()))
        await asyncio.sleep(3)
""",
    },
    "floor": {
        "args": [("step", int, 5), ("secs", float, 1.2)],
        "code": """
async def run():
    # THE STICTION FLOOR — the slowest speed that actually moves this body on
    # THIS surface. Ramps a cw spin upward in steps of {step}, holding each
    # {secs}s. The first speed reporting MOVED is your SPEED_FLOOR.
    #
    # A SPIN and not a straight line, because a spin is the only movement this
    # body measures rather than infers: the gyro says how far it really went.
    # A rover rolling quietly forward on a smooth desk can look exactly like a
    # rover that never started.
    #
    # Rover ON THE FLOOR for this one, not on a book: stiction depends on the
    # surface and on the weight the wheels carry. Run it again on carpet and
    # on a desk — the numbers will differ, and that difference is the point.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first and set MOTOR_CORNER/"
             "MOTOR_SIGN. Until then every command below is a "
             "no-op.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("floor: ramping cw in steps of {step}. first MOVED is the floor.")
    first = None
    s = {step}
    while s <= 100:
        cw(s)
        await asyncio.sleep({secs})
        stop()
        await asyncio.sleep(0.8)
        r = Drive.last()
        if r is None:
            send("speed {{}} -> no reading".format(s))
        else:
            send("speed {{}} -> turned {{}} ({{}} dps) stir {{}} {{}}".format(
                s, r["turned"], r["dps"], r["stir"],
                "STALL" if r["stalled"] else "MOVED"))
            if first is None and not r["stalled"]:
                first = s
                send("*** SPEED_FLOOR = {{}} on this surface ***".format(s))
        s += {step}
    send("done. floor={{}} — put it in lib/drive.py".format(first))
    while True:
        await asyncio.sleep(1)
""",
    },
    "spin": {
        "args": [("speed", int, 50), ("secs", float, 3.0)],
        "code": """
async def run():
    # WHAT DOES THIS SPEED BUY? One long cw spin at {speed} for {secs}s, then
    # the same ccw. The two dps figures should be equal and OPPOSITE — cw
    # positive, ccw negative. If they differ in magnitude the two sides are
    # not balanced, and that asymmetry will show up as veer in everything
    # else this body does. If they have the SAME sign, the corner map is
    # wrong: the body is not turning where it thinks it is.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("spin: cw then ccw at {speed}, {secs}s each")
    while True:
        for name, verb in (("cw", cw), ("ccw", ccw)):
            verb({speed})
            await asyncio.sleep({secs})
            stop()
            await asyncio.sleep(1.0)
            r = Drive.last()
            if r:
                send("{{}} {speed} -> turned {{}} in {{}}s = {{}} dps{{}}".format(
                    name, r["turned"], r["for_s"], r["dps"],
                    " STALL" if r["stalled"] else ""))
        await asyncio.sleep(2)
""",
    },
    "straight": {
        "args": [("speed", int, 50), ("secs", float, 2.0)],
        "code": """
async def run():
    # DOES IT GO STRAIGHT? forward {secs}s, then backward {secs}s, at {speed}.
    # The number to read is `turned`: on a straight line it is VEER, degrees
    # of yaw nobody asked for. A few degrees is the floor and the wheels; tens
    # of degrees is one side weaker than the other, or a sign flipped.
    #
    # Forward and backward veer that share a SIGN mean a weak corner (the body
    # curves the same way going either direction, like a shopping trolley).
    # Veer that FLIPS sign with direction means the two sides are geared or
    # loaded differently. Both are worth telling apart, which is why this
    # recipe runs the pair.
    #
    # Give it a couple of metres, and be ready to catch it.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("straight: forward then backward at {speed}, {secs}s each. "
         "`turned` here is VEER.")
    while True:
        for name, verb in (("forward", forward), ("backward", backward)):
            verb({speed})
            await asyncio.sleep({secs})
            stop()
            await asyncio.sleep(1.2)
            r = Drive.last()
            if r:
                send("{{}} {speed} for {{}}s -> veer {{}} deg ({{}} dps), "
                     "stir {{}}{{}}".format(
                    name, r["for_s"], r["turned"], r["dps"], r["stir"],
                    " STALL(or silent — check by eye)" if r["stalled"] else ""))
        await asyncio.sleep(2)
""",
    },
    "slide": {
        "args": [("speed", int, 60), ("secs", float, 2.0)],
        "code": """
async def run():
    # THE MECANUM CHECK. slide_right for {secs}s, then slide_left, at {speed}.
    # This is the one thing this body can do that robot-bug cannot, and the
    # one thing a wrong corner map cannot fake.
    #
    # What a GOOD slide looks like: the body travels sideways, nose still
    # pointing the same way, and `turned` comes back near zero while `stir`
    # is clearly non-zero. Moving AND not turning is the whole signature.
    #
    # What the failures look like:
    #   turns instead of translating  -> two corners swapped in MOTOR_CORNER
    #   barely moves, motors loud     -> the rollers form a diamond, not an X;
    #                                    two wheels are physically in each
    #                                    other's corners. Software will not
    #                                    fix this one.
    #   travels FORWARD or BACK       -> a sign wrong in MOTOR_SIGN
    #
    # Sliding costs more than driving: the rollers scrub, so expect to need
    # more speed than forward needed, and expect carpet to defeat it.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("slide: right then left at {speed}. good = moves, does NOT turn.")
    while True:
        for name, verb in (("right", slide_right), ("left", slide_left)):
            verb({speed})
            await asyncio.sleep({secs})
            stop()
            await asyncio.sleep(1.2)
            r = Drive.last()
            if r:
                send("slide {{}} {speed} for {{}}s -> turned {{}} deg "
                     "(want ~0), stir {{}}{{}}".format(
                    name, r["for_s"], r["turned"], r["stir"],
                    " STALL" if r["stalled"] else ""))
        await asyncio.sleep(2)
""",
    },
    "box": {
        "args": [("speed", int, 60), ("side_s", float, 1.5)],
        "code": """
async def run():
    # THE SQUARE NO OTHER BODY IN THE MENAGERIE CAN DRIVE: forward, right,
    # back, left — a closed box with NO rotation anywhere in it. Only mecanum
    # wheels can do this, and it is the strongest single test that the corner
    # map, the signs and the mixer all agree.
    #
    # Read two things. By eye: does it come back to where it started, and is
    # the nose still pointing the same way? From the instrument: the four
    # `turned` values summed. They should sum near zero — every leg was meant
    # to be pure translation, so all of it is error.
    #
    # Put it on a floor with a metre of room and mark the starting corner with
    # a piece of tape. A box that closes is a calibration you can trust.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("box: fwd/right/back/left at {speed}, {side_s}s a side, no turning. "
         "mark the start.")
    LEGS = (("forward", forward), ("right", slide_right),
            ("back", backward), ("left", slide_left))
    while True:
        total = 0.0
        for name, verb in LEGS:
            verb({speed})
            await asyncio.sleep({side_s})
            stop()
            await asyncio.sleep(0.8)
            r = Drive.last()
            if r:
                total += r["turned"]
                send("{{}} -> turned {{}} deg, stir {{}}{{}}".format(
                    name, r["turned"], r["stir"],
                    " STALL" if r["stalled"] else ""))
        send("=== box closed with {{:.0f}} deg of unwanted rotation "
             "(0 is perfect) — and did it come home? ===".format(total))
        await asyncio.sleep(3)
""",
    },
    "square": {
        "args": [("speed", int, 50), ("side_s", float, 1.5)],
        "code": """
async def run():
    # The turning square, for comparison with `box`: forward + quarter-turn,
    # four times. Where `box` tests the slides, this tests that driving and
    # turning agree with each other — the same check robot-bug runs.
    #
    # The number to read is the four cw legs' `turned`: they should agree with
    # each other, and four of them should sum near 360. The forward legs'
    # `turned` is veer, and systematic veer is one side weaker than the other.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("square: forward + quarter-turn x4 at {speed}. watch it.")
    while True:
        total = 0.0
        for leg in range(4):
            forward({speed})
            await asyncio.sleep({side_s})
            stop()
            await asyncio.sleep(0.6)
            r = Drive.last()
            if r:
                send("leg {{}} fwd -> veer {{}} stir {{}}{{}}".format(
                    leg, r["turned"], r["stir"],
                    " STALL" if r["stalled"] else ""))
            cw({speed})
            await asyncio.sleep({side_s})
            stop()
            await asyncio.sleep(0.6)
            r = Drive.last()
            if r:
                total += r["turned"]
                send("leg {{}} cw -> turned {{}} ({{}} dps)".format(
                    leg, r["turned"], r["dps"]))
        send("=== four quarter-turns summed to {{:.0f}} deg (360 is "
             "perfect) ===".format(total))
        await asyncio.sleep(3)
""",
    },
    "drive": {
        "args": [("fwd", int, 0), ("strafe", int, 0), ("spin", int, 0),
                 ("secs", float, 2.0)],
        "code": """
async def run():
    # THE MIXER ITSELF: move(fwd={fwd}, strafe={strafe}, spin={spin}) held for
    # {secs}s, then off, scored, repeated. + is forward, + is to the RIGHT,
    # + is clockwise from above; all three compose, and the whole set is
    # scaled down together if the mix asks any wheel for more than 100.
    #
    # This is where a diagonal lives — move(50, 50, 0) is 45 degrees forward
    # and right with the nose still — and where you find out whether this body
    # can travel and turn at the same time on this floor, or whether the two
    # just fight.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    send("drive: fwd={fwd} strafe={strafe} spin={spin} for {secs}s, on repeat")
    while True:
        move({fwd}, {strafe}, {spin})
        await asyncio.sleep({secs})
        stop()
        await asyncio.sleep(1.2)
        r = Drive.last()
        if r:
            send("-> turned {{}} deg ({{}} dps), stir {{}}{{}}".format(
                r["turned"], r["dps"], r["stir"],
                " STALL" if r["stalled"] else ""))
        await asyncio.sleep(1)
""",
    },
    "tof": {
        "args": [],
        "code": """
async def run():
    # IS THE BEAM ALIVE, AND WHAT DOES IT SAY? The percept, streamed. This
    # recipe READS the organ and never touches the sensor — the pump owns the
    # VL53L0X, and a second hand on it would fight over the bus.
    #
    # Wave a hand: ~30 mm is as close as it can see, a wall answers to about
    # 1.5-2 m, and 0 is NO ECHO — which means "I do not know", never "far
    # away". The sentinel the raw hardware parks at (~8190) is collapsed to
    # that 0 by the runtime, on purpose.
    stop()
    send("tof: streaming. wave a hand in front of the beam.")
    last = None
    while True:
        mm = ToF.read_distance_mm()
        if mm is None:
            send("no ToF bound — run `scan`; if 0x29 answers there, reboot "
                 "the stick so boot can bind it")
            await asyncio.sleep(2)
            continue
        if mm == 0:
            send("no echo")
            last = None
        else:
            trend = " ({:+d})".format(mm - last) if last else ""
            send("{} mm{}  age {} ms".format(mm, trend, ToF.age_ms()))
            last = mm
        await asyncio.sleep(0.4)
""",
    },
    "blob": {
        "args": [("period_ms", int, 500)],
        "code": """
async def run():
    # BOTH SENSES ON ONE LINE, AT REST — the measurement instrument for
    # detection thresholds and the blob-area-vs-distance curve. Stand at a
    # known distance, read the line, move, read again; the pairs regress
    # into a curve later. No motion at all, so nothing contaminates the
    # readings. BtnA on the stick cycles the detection delta while this runs.
    stop()
    send("blob: thermal + tof at rest, every {period_ms} ms — no motion")
    while True:
        b = Thermal.blob()
        mm = ToF.read_distance_mm()
        if b["present"]:
            send("present area={{}} exc={{:.1f}} cx={{:.1f}} cy={{:.1f}} "
                 "amb={{:.1f}} tof={{}} tof_age={{}} blob_age={{}}".format(
                     b["area"], b["excess_c"], b["cx"], b["cy"],
                     b["ambient_c"], mm, ToF.age_ms(), b["age_ms"]))
        else:
            send("absent amb={{:.1f}} delta={{:.1f}} tof={{}}".format(
                b["ambient_c"], Thermal.delta(), mm))
        await asyncio.sleep_ms({period_ms})
""",
    },
    "wall": {
        "args": [("speed", int, 30), ("secs", float, 1.5)],
        "code": """
async def run():
    # THE WALL BENCH, leg by leg. Face me at a bare wall from 600-1000 mm:
    # one forward leg at {speed} for up to {secs}s, settle, one backward
    # leg, settle, repeat — each leg bracketed by the beam.
    #
    #   travelled  mm the gap really changed, read AFTER the body settles
    #   mm/s       what speed {speed} actually buys on this floor
    #   coast      mm that kept coming after stop() — the momentum every
    #              careful behaviour has to leave room for
    #   veer       the gyro's usual report, unchanged from stage 1
    #
    # The forward leg aborts early near the wall: this measures the body,
    # not the paintwork. If legs keep aborting, start further out or
    # shorten {secs}.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    if ToF.read_distance_mm() is None:
        send("REFUSING: no ToF bound. run `scan`; reboot if 0x29 answers.")
        while True:
            await asyncio.sleep(1)
    MIN_MM = 130

    def rng():
        mm = ToF.read_distance_mm()
        return mm if mm else None      # 0 = no echo = unusable

    send("wall: fwd/back at {speed}, {secs}s legs. face me at a wall, "
         "600-1000 mm out.")
    while True:
        for name, verb, sgn in (("forward", forward, 1),
                                ("backward", backward, -1)):
            d0 = rng()
            if d0 is None:
                send("no echo — nothing to measure against. face me at a "
                     "wall.")
                await asyncio.sleep(2)
                continue
            if sgn > 0 and d0 < MIN_MM + 80:
                send("only {{}} mm of room — skipping the forward "
                     "leg".format(d0))
                continue
            verb({speed})
            t0 = time.ticks_ms()
            early = False
            while time.ticks_diff(time.ticks_ms(), t0) < int({secs} * 1000):
                mm = rng()
                if sgn > 0 and mm is not None and mm < MIN_MM:
                    early = True
                    break
                await asyncio.sleep_ms(40)
            stop()
            d_stop = rng()
            await asyncio.sleep(0.8)          # let the coast finish
            d1 = rng()
            r = Drive.last()
            if d1 is None or d_stop is None or r is None:
                send("{{}} leg lost its echo mid-measure — nothing "
                     "scored".format(name))
                await asyncio.sleep(1)
                continue
            travelled = (d0 - d1) * sgn       # + = went the way it was told
            coast = (d_stop - d1) * sgn       # + = kept going after stop
            send("{{}} {speed} for {{}}s -> {{}} mm ({{:.0f}} mm/s), coast "
                 "{{}} mm, veer {{}} deg, stir {{}}{{}}{{}}".format(
                     name, r["for_s"], travelled,
                     travelled / r["for_s"] if r["for_s"] else 0.0,
                     coast, r["turned"], r["stir"],
                     " EARLY-STOP" if early else "",
                     " STALL" if r["stalled"] else ""))
            await asyncio.sleep(1.2)
        await asyncio.sleep(1)
""",
    },
    "step": {
        "args": [("speed", int, 25), ("ms", int, 150), ("n", int, 8)],
        "code": """
async def run():
    # THE SMALLEST STEP. {n} forward pulses of {ms} ms at {speed}, settling
    # after each, mm per pulse read off the wall — then one backward run to
    # give the room back. Three numbers come out:
    #
    #   the mean step   what "move a little" means on this body
    #   the spread      min..max — how repeatable "a little" is
    #   the zeros       pulses that bought nothing: {ms} ms at {speed} is
    #                   under this floor's start-from-rest cost
    #
    # Every slow, careful behaviour this creature will ever run is built
    # from exactly this move, so its size IS the resolution of "careful".
    # Try it at several speeds and pulse lengths; the map is the point.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    if ToF.read_distance_mm() is None:
        send("REFUSING: no ToF bound. run `scan`; reboot if 0x29 answers.")
        while True:
            await asyncio.sleep(1)
    MIN_MM = 130

    def rng():
        mm = ToF.read_distance_mm()
        return mm if mm else None

    async def settled():
        # The beam wobbles ~+/-12 mm on a fixed target (measured 2026-08-24),
        # and one pulse may buy less than that — so every per-pulse reading
        # is a MEAN of 5 samples, or the spread reported here is the beam's,
        # not the body's.
        vals = []
        for _ in range(5):
            v = rng()
            if v is not None:
                vals.append(v)
            await asyncio.sleep_ms(120)
        return sum(vals) / len(vals) if vals else None

    send("step: {n} pulses of {ms} ms at {speed}. face me at a wall with "
         "room to spare.")
    while True:
        d_prev = await settled()
        if d_prev is None or d_prev < MIN_MM + {n} * 40:
            send("want ~{{}} mm of clear run-up, have {{}} — back me "
                 "up".format(MIN_MM + {n} * 40, d_prev))
            await asyncio.sleep(2)
            continue
        steps = []
        for i in range({n}):
            forward({speed})
            await asyncio.sleep_ms({ms})
            stop()
            await asyncio.sleep(0.8)
            d = await settled()
            if d is None:
                send("pulse {{}}: echo lost".format(i))
                break
            steps.append(d_prev - d)
            send("pulse {{}}: {{:+.0f}} mm ({{:.0f}} -> {{:.0f}})".format(
                i, d_prev - d, d_prev, d))
            d_prev = d
            if d < MIN_MM:
                send("close enough to the wall — ending the run early")
                break
        if steps:
            zeros = sum(1 for s in steps if abs(s) <= 5)
            send("=== {{}} pulses of {ms} ms at {speed}: mean {{:.0f}} mm, "
                 "min {{:.0f}} max {{:.0f}}, {{}} bought nothing "
                 "(<=5 mm) ===".format(
                     len(steps), sum(steps) / len(steps), min(steps),
                     max(steps), zeros))
        # give the room back
        backward({speed})
        await asyncio.sleep(max(0.3, len(steps) * {ms} / 1000.0))
        stop()
        await asyncio.sleep(1.5)
""",
    },
    "vfloor": {
        "args": [("start", int, 10), ("step", int, 3), ("secs", float, 1.0)],
        "code": """
async def run():
    # THE STRAIGHT-LINE STICTION FLOOR — measured at last. Stage 1's floor
    # was a SPIN floor (21), because rotation was all it could measure. A
    # straight line fights different friction, so its floor is its own
    # number, and this ramp believes only the wall: MOVED means the gap
    # changed by more than the beam's own noise.
    #
    # Legs alternate forward/backward so the ramp stays in its lane instead
    # of marching across the room.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    if ToF.read_distance_mm() is None:
        send("REFUSING: no ToF bound. run `scan`; reboot if 0x29 answers.")
        while True:
            await asyncio.sleep(1)
    MOVED_MM = 10

    def rng():
        mm = ToF.read_distance_mm()
        return mm if mm else None

    async def settled():
        # The beam wobbles ~+/-12 mm on a fixed target (measured 2026-08-24,
        # 305..330 at ~319). A settled measurement is a MEAN of 5 samples,
        # not one — or this ramp calls the wobble MOVED and undercuts the
        # floor it exists to find.
        vals = []
        for _ in range(5):
            v = rng()
            if v is not None:
                vals.append(v)
            await asyncio.sleep_ms(120)
        return sum(vals) / len(vals) if vals else None

    send("vfloor: ramping a straight line from {start} in steps of {step}. "
         "the spin floor was 21 — expect this at or above it.")
    first = None
    s = {start}
    dirn = 1
    while s <= 100:
        d0 = await settled()
        if d0 is None:
            send("no echo — face me at a wall, 400-900 mm out")
            await asyncio.sleep(2)
            continue
        if d0 < 300:
            dirn = -1
        elif d0 > 900:
            dirn = 1
        verb = forward if dirn > 0 else backward
        verb(s)
        await asyncio.sleep({secs})
        stop()
        await asyncio.sleep(0.8)
        d1 = await settled()
        if d1 is None:
            send("speed {{}}: echo lost mid-leg — retrying it".format(s))
            continue
        moved = abs(d0 - d1)
        send("speed {{}} {{}} -> {{:+.0f}} mm {{}}".format(
            s, "fwd" if dirn > 0 else "back", (d0 - d1) * dirn,
            "MOVED" if moved >= MOVED_MM else "nothing"))
        if first is None and moved >= MOVED_MM:
            first = s
            send("*** straight-line floor = {{}} on this surface (spin "
                 "floor 21) ***".format(s))
        dirn = -dirn
        s += {step}
        await asyncio.sleep(0.5)
    send("done. straight-line floor = {{}} — worth a dated note in "
         "lib/drive.py".format(first))
    while True:
        await asyncio.sleep(1)
""",
    },
    "hold": {
        "args": [("target", int, 300), ("band", int, 30), ("speed", int, 25)],
        "code": """
async def run():
    # KEEP {target} mm — the dress rehearsal for keeping distance from a
    # person, run against something that cannot walk away. Read, pulse
    # toward the band, settle, read again. Between the step size and the
    # coast this body cannot hold a hair's breadth, so the honest questions
    # are: how wide a band CAN it hold, how often does it shoot straight
    # through, and does it ring?
    #
    # It learns mm-per-ms as it goes, so pulses shrink as the error does.
    # It reads only while STILL — a reading taken mid-pulse brackets
    # nothing. Once this holds a wall, push it: walk a book toward the beam
    # and watch it back away.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    if ToF.read_distance_mm() is None:
        send("REFUSING: no ToF bound. run `scan`; reboot if 0x29 answers.")
        while True:
            await asyncio.sleep(1)
    BAND = {band}
    rate = 0.15          # mm per ms at speed {speed}: first guess, learned
    cycles = 0
    in_band = 0
    crossings = 0
    was_side = 0
    worst = 0

    def rng():
        mm = ToF.read_distance_mm()
        return mm if mm else None

    send("hold: {target} +/- {band} mm at speed {speed}. face me at the "
         "wall.")
    while True:
        mm = rng()
        if mm is None:
            stop()
            send("no echo — holding still until the wall comes back")
            await asyncio.sleep(1)
            continue
        err = mm - {target}          # + = too far away, pulse forward
        side = 1 if err > BAND else (-1 if err < -BAND else 0)
        cycles += 1
        if abs(err) > worst:
            worst = abs(err)
        if side == 0:
            in_band += 1
        else:
            if was_side and side != was_side:
                crossings += 1
            was_side = side
            pulse = int(min(500, max(80, abs(err) / rate)))
            (forward if side > 0 else backward)({speed})
            await asyncio.sleep_ms(pulse)
            stop()
            await asyncio.sleep(0.6)
            d2 = rng()
            if d2 is not None:
                got = abs(mm - d2)
                if got > 4:
                    rate = 0.7 * rate + 0.3 * (got / pulse)
                send("err {{:+d}} -> pulse {{}} ms -> moved {{}} mm, now "
                     "{{}} (rate {{:.2f}} mm/ms)".format(
                         err, pulse, got, d2, rate))
        if cycles % 20 == 0:
            send("=== {{}} cycles: {{:.0f}}% in band, {{}} straight-through "
                 "crossings, worst {{}} mm off ===".format(
                     cycles, 100.0 * in_band / cycles, crossings, worst))
        await asyncio.sleep(0.4)
""",
    },
    "face": {
        "args": [("pace", int, 30), ("pulse_ms", int, 200), ("band_px", int, 2)],
        "code": """
async def run():
    # FACE THE WARMTH: turn in place to hold the blob's centre at CENTRE_X,
    # in pulses of {pulse_ms} ms at {pace}. robot_dog's `face`, minus the
    # gait — wheels turn crisper than legs, so the open questions are how
    # many DEGREES one pulse buys (Drive scores every one) and how many
    # PIXELS of centroid that is: px-per-deg, read straight off this log.
    #
    # WHICH WAY the camera hangs is not assumed: it guesses, checks whether
    # the error shrank, and flips its map when it grew or the shape vanished
    # — losing the blob right after a turn is itself evidence.
    if not Drive.calibrated():
        send("REFUSING: {{}}. run `motors` first.".format(Drive.fault()))
        while True:
            await asyncio.sleep(1)
    BAND = {band_px}
    CX = Thermal.CENTRE_X
    sign = 1              # +1: blob right of centre -> cw. flipped if wrong.
    quiet = 0
    send("face: holding the warm shape within +/-{band_px} px of centre. "
         "stand in view.")
    while True:
        b = Thermal.blob()
        if not b["present"] or b["age_ms"] > 600:
            stop()
            quiet += 1
            if quiet % 10 == 1:
                send("nothing warm in view (ambient {{:.1f}} C, delta "
                     "{{:.1f}})".format(b["ambient_c"], Thermal.delta()))
            await asyncio.sleep(0.5)
            continue
        quiet = 0
        off = b["cx"] - CX
        if abs(off) <= BAND:
            await asyncio.sleep(0.3)
            continue
        verb = cw if off * sign > 0 else ccw
        verb({pace})
        await asyncio.sleep_ms({pulse_ms})
        stop()
        await asyncio.sleep(0.5)
        r = Drive.last()
        b2 = Thermal.blob()
        turned = r["turned"] if r else 0.0
        if not b2["present"]:
            sign = -sign
            send("turned {{}} deg and LOST it — flipping my map".format(
                turned))
        else:
            off2 = b2["cx"] - CX
            if abs(off2) > abs(off) + 0.7:
                sign = -sign
                send("cx {{:.1f}} -> {{:.1f}} after {{}} deg: error GREW — "
                     "flipping my map".format(b["cx"], b2["cx"], turned))
            else:
                send("cx {{:.1f}} -> {{:.1f}} ({{:+.1f}} px toward centre) "
                     "for {{}} deg of turn".format(
                         b["cx"], b2["cx"], abs(off) - abs(off2), turned))
        await asyncio.sleep(0.2)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    # Raw IMU with the motors idle — the baseline for what "not moving" reads
    # like. STILL_DPS and STIR_G in lib/drive.py are the lines between moving
    # and not, and they should sit comfortably above the noise you see here.
    # Nudge the rover by hand while this runs: yaw should swing positive when
    # you twist it clockwise seen from above, and that is worth confirming
    # once, because every `turned` in every other recipe rests on it.
    stop()
    send("imulog: motors off. this is the noise floor. twist it by hand.")
    while True:
        a = Imu.getAccel()
        g = Imu.getGyro()
        send("accel=({:.3f},{:.3f},{:.3f}) gyro=({:.1f},{:.1f},{:.1f}) "
             "| yaw {:.1f} dps | stir {:.3f}".format(
                 a[0], a[1], a[2], g[0], g[1], g[2],
                 Drive.rot(), Drive.stir()))
        await asyncio.sleep(0.5)
""",
    },
    "vbat": {
        "args": [],
        "code": """
async def run():
    # Battery UNDER LOAD. Four motors draw far more than the stick does, and a
    # rover browning out mid-turn looks exactly like a rover with a bad corner
    # map: commands that do nothing, or do something once and never again.
    # Watch this while DRIVING, not while parked.
    stop()
    send("vbat: live. drive it around and watch this sag.")
    while True:
        send("vbat={}mV vbus={}mV chg={} | yaw {:.1f} dps stir {:.3f}".format(
            M5.Power.getBatteryVoltage(), M5.Power.getVBUSVoltage(),
            M5.Power.isCharging(), Drive.rot(), Drive.stir()))
        await asyncio.sleep(1)
""",
    },
    "off": {
        "args": [],
        "code": """
async def run():
    stop()
    send("silenced — motors off")
    while True:
        await asyncio.sleep(1)
""",
    },
}
