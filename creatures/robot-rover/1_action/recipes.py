"""
recipes.py — instinct templates for the robot-rover tuner.

This body is an M5StickS3 on an M5Stack RoverC: four MECANUM wheels behind an
STM32 at I2C 0x38, on the same SoftI2C bus robot_dog drives its legs on and
robot-bug its motors. The RoverC is sold for the StickC; the pins in main.py
are the StickS3 mapping, already proven on this header by the other two.

THE TUNER'S JOB, IN ORDER. Nothing in this creature works until three things
are measured, and all three are measured here:

  1. `motors`   — which register index drives which CORNER, and which sign is
                  forward. The protocol says reg 0x00..0x03 are the four
                  motors; it does not say which motor is which wheel. On a
                  mecanum base that is not cosmetic: the mixer sends opposite
                  signs to the two front wheels when sliding, so a corner map
                  that is merely plausible drives forward beautifully and then
                  crabs sideways into the table leg. Until it is known the
                  verbs REFUSE to move.
  2. `slide`    — does the X hold? Four mecanum wheels only strafe if their
                  rollers form an X seen from above. This is the recipe that
                  says whether the wheels are in the right corners, and it is
                  the one check robot-bug never needed.
  3. `floor`    — the slowest speed that actually breaks stiction on THIS
                  surface. Geared DC motors do not start below roughly a
                  third of full; under it they buzz and nothing happens. A
                  property of the FLOOR as much as of the body, so it is worth
                  re-running on carpet and on a desk.

Then `straight`, `spin`, `box` and `square` check that the calibration held.

WHAT THE INSTRUMENT CAN AND CANNOT SAY. Rotation is measured — the gyro,
integrated about the found vertical, signed, + clockwise from above. Distance
is NOT: there is no odometry and no ToF in stage 1. So a turn is scored
honestly, while a straight line is only ever witnessed as "the body was being
shaken" (`stir`) or "it was not" (`stalled`), plus the veer the gyro catches.
That is why `floor` ramps a SPIN and not a straight line.

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
    send("idle: robot-rover tuner")
    while True:
        send("yaw {:.1f} dps | stir {:.3f} | commanded {} | calibrated {} "
             "({})".format(Drive.rot(), Drive.stir(), Drive.commanded(),
                           Drive.calibrated(), Drive.fault() or "ok"))
        await asyncio.sleep(2)
"""

RECIPES = {
    "scan": {
        "args": [],
        "code": """
async def run():
    # IS THE ROVER EVEN THERE? Scans the HAT bus and says what answered. The
    # RoverC's STM32 should show up at 0x38 (56 decimal).
    #
    # RUN THIS FIRST, EVERY SESSION. The rover has its OWN POWER SWITCH and
    # its own battery: with it off, the stick boots happily on USB, wifi
    # comes up, the tuner connects, every command is accepted — and nothing
    # moves, because the thing the bytes are addressed to is not powered.
    # That failure looks EXACTLY like a wrong corner map, a stiction floor
    # you are under, and a flat rover battery. This is the one reading that
    # tells them apart: no 0x38 means nobody is listening, and no amount of
    # calibration fixes it.
    #
    # An empty scan, in likely order: rover switched OFF; rover battery flat;
    # stick not seated all the way down on the 8-pin header; wrong pins.
    stop()
    send("scan: looking for the RoverC on the HAT bus. want 0x38.")
    while True:
        try:
            found = i2c_hat.scan()
        except Exception as e:
            send("scan: BUS ERROR {} — the pins themselves are unhappy".format(e))
            await asyncio.sleep(2)
            continue
        if not found:
            send("scan: NOBODY HOME. is the rover's power switch on? is its "
                 "battery flat? is the stick seated?")
        else:
            send("scan: {} | rover at 0x38: {}".format(
                [hex(a) for a in found], 0x38 in found))
        await asyncio.sleep(2)
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
            send("{} {} for {}s -> turned {} ({} dps), stir {}{}".format(
                r["kind"], r["speed"], r["for_s"], r["turned"], r["dps"],
                r["stir"], " STALL" if r["stalled"] else ""))
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
