"""
recipes.py — instinct templates for the robot-bug tuner.

This body is an M5StickS3 on a BugC HAT: four DC motors and two RGB LEDs
behind an STM32 at I2C 0x38, on the same SoftI2C bus robot_dog drives its
legs on.

THE TUNER'S JOB, IN ORDER. Nothing in this creature works until two things
are measured, and both are measured here:

  1. `motors`  — which register index drives which corner, and which sign is
                 forward. The BugC documentation does not say. Until it is
                 known the verbs REFUSE to move, because a guessed sign map
                 drives a rover in a direction nobody predicted, and a rover
                 that goes the wrong way goes off a table.
  2. `floor`   — the slowest speed that actually breaks stiction on this
                 surface. Geared DC motors do not start below roughly a third
                 of full; under it they buzz and nothing happens. This is a
                 property of the FLOOR as much as the body, so it is worth
                 re-running on carpet and on a desk.

Then `square` and `spin` check the calibration held.

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
    send("idle: robot-bug tuner")
    while True:
        send("rot {:.1f} dps | commanded {} | calibrated {}".format(
            Drive.rot(), Drive.commanded(), Drive.calibrated()))
        await asyncio.sleep(2)
"""

RECIPES = {
    "motors": {
        "args": [("speed", int, 60), ("secs", float, 1.5)],
        "code": """
async def run():
    # WHICH WHEEL IS WHICH. Spins ONE motor index at a time at {speed} for
    # {secs}s, announcing each before it moves.
    #
    # Put the rover ON A BOOK or a mug so the wheels spin free — you are
    # reading the wheels, not driving the body. For each index write down:
    #   * which corner turned         -> its MOTOR_SIDE entry (-1 L, +1 R)
    #   * whether it turned FORWARD   -> its MOTOR_SIGN entry (+1 or -1)
    #
    # Then put both 4-tuples into lib/organs.py and reflash lib/. This recipe
    # writes the motors directly, bypassing the verbs, because the verbs
    # refuse to move until exactly this is known.
    send("motors: rover ON A BOOK, wheels free. one index at a time.")
    await asyncio.sleep(2)
    while True:
        for idx in range(4):
            send("--- index {{}}: POSITIVE {speed} — which wheel, which way? "
                 "---".format(idx))
            b = [0, 0, 0, 0]
            b[idx] = {speed}
            i2c_hat.writeto_mem(0x38, 0x00, struct.pack("bbbb", *b))
            await asyncio.sleep({secs})
            i2c_hat.writeto_mem(0x38, 0x00, struct.pack("bbbb", 0, 0, 0, 0))
            await asyncio.sleep(1.5)
        send("=== round done. `off` to stop, or watch it again ===")
        await asyncio.sleep(2)
""",
    },
    "floor": {
        "args": [("step", int, 5), ("secs", float, 1.2)],
        "code": """
async def run():
    # THE STICTION FLOOR — the slowest speed that actually moves this body on
    # THIS surface. Ramps cw upward in steps of {step}, holding each {secs}s.
    # The first speed reporting MOVED is your SPEED_FLOOR.
    #
    # Rover ON THE FLOOR for this one, not on a book: stiction depends on the
    # surface and on the weight the wheels carry. Run it again on carpet and
    # on a desk — the numbers will differ, and that difference is the point.
    if not Drive.calibrated():
        send("REFUSING: run `motors` first and set MOTOR_SIDE/MOTOR_SIGN. "
             "Until then every command below is a no-op.")
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
    send("done. floor={{}} — put it in lib/organs.py".format(first))
    while True:
        await asyncio.sleep(1)
""",
    },
    "square": {
        "args": [("speed", int, 50), ("side_s", float, 1.5)],
        "code": """
async def run():
    # DOES THE CALIBRATION HOLD? forward + quarter-turn, four times. With a
    # correct sign map it comes back near where it began; with one sign
    # flipped it does something obviously wrong on the first leg — which is
    # why this belongs on a table you are watching.
    #
    # The number to read is the four cw legs' `turned`: they should agree,
    # and four of them should sum near 360. Systematic drift between the
    # forward legs is veer — one side weaker than the other.
    if not Drive.calibrated():
        send("REFUSING: run `motors` first.")
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
                send("leg {{}} fwd -> stir {{}} {{}}".format(
                    leg, r["stir"], "STALL" if r["stalled"] else ""))
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
    "spin": {
        "args": [("speed", int, 50), ("secs", float, 3.0)],
        "code": """
async def run():
    # WHAT DOES THIS SPEED BUY? One long cw spin at {speed} for {secs}s, then
    # the same ccw. The two dps figures should match. If cw is consistently
    # faster than ccw the sides are not balanced, and that asymmetry will
    # show up as veer in everything else this body does.
    if not Drive.calibrated():
        send("REFUSING: run `motors` first.")
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
                send("{{}} {speed} -> turned {{}} in {{}}s = {{}} dps".format(
                    name, r["turned"], r["for_s"], r["dps"]))
        await asyncio.sleep(2)
""",
    },
    "led": {
        "args": [],
        "code": """
async def run():
    # The two RGB LEDs on the base: index 0 left, 1 right. Worth running FIRST
    # after a flash — it proves the HAT bus is talking without moving
    # anything, so a dead bus and a wrong sign map cannot be confused.
    stop()
    send("led: cycling both. nothing lights => the HAT bus is the problem.")
    COLORS = ((80, 0, 0), (0, 80, 0), (0, 0, 80), (60, 60, 0), (0, 0, 0))
    while True:
        for (r, g, b) in COLORS:
            set_led(0, r, g, b)
            set_led(1, b, r, g)
            send("led ({}, {}, {})".format(r, g, b))
            await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    # Raw IMU with the motors idle — the baseline for what "not moving" reads
    # like. STILL_DPS and STIR_G in organs.py are the lines between moving and
    # not, and they should sit comfortably above the noise you see here.
    stop()
    send("imulog: motors off. this is the noise floor.")
    while True:
        a = Imu.getAccel()
        g = Imu.getGyro()
        send("accel=({:.3f},{:.3f},{:.3f}) gyro=({:.1f},{:.1f},{:.1f}) "
             "| rot {:.1f}".format(a[0], a[1], a[2], g[0], g[1], g[2],
                                   Drive.rot()))
        await asyncio.sleep(0.5)
""",
    },
    "vbat": {
        "args": [],
        "code": """
async def run():
    # Battery UNDER LOAD. The BugC carries its own 16340 (750mAh) and the
    # motors draw ~200mA running, ~280mA stalled — so watch this while
    # driving, not while parked. A rover browning out mid-turn looks exactly
    # like a rover with a bad sign map.
    stop()
    send("vbat: live. drive it around and watch this sag.")
    while True:
        send("vbat={}mV vbus={}mV chg={} | rot {:.1f} dps".format(
            M5.Power.getBatteryVoltage(), M5.Power.getVBUSVoltage(),
            M5.Power.isCharging(), Drive.rot()))
        await asyncio.sleep(1)
""",
    },
    "off": {
        "args": [],
        "code": """
async def run():
    stop()
    set_led(0, 0, 0, 0)
    set_led(1, 0, 0, 0)
    send("silenced — motors off, lights off")
    while True:
        await asyncio.sleep(1)
""",
    },
}
