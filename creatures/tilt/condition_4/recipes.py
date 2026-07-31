"""
recipes.py — instinct templates for the tilt tuner.

This body is a PLAIN StickS3 — internal speaker and IMU, nothing attached.

NO ORGAN IN THIS ARM. condition_1/2/3 had a Posture module in the body and
these recipes called it. Here the sense is fourteen lines of arithmetic that
live in the instinct, so each recipe below carries its own copy. That is not
duplication to be tidied away — it is the point. A recipe is instinct code,
and a recipe you can read end to end is a recipe whose numbers you can trust.

It also changes how you tune. There is no `set STILL_DPS 8` any more, because
there is no module attribute to patch: the thresholds are ARGUMENTS. `state 8`
runs the whole sense at STILL_DPS=8 and you watch what happens. Explicit, per
run, and exactly what the instinct will do with that number.

The tuner's jobs before anyone wears it: find the CRICKET (a chirp subtle
enough to be missable) and see the POSTURE arithmetic behave on a real back —
that gravity settles, that lean reads near zero when they sit upright, and
that the still/moving line falls where a person would put it.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
Recipes with no args are sent verbatim, so single braces are fine there.
"""

INSTINCT_IDLE = """
async def run():
    send("idle: tilt tuner")
    grav = None
    n = 0
    while True:
        a = Imu.getAccel()
        if grav is None:
            grav = list(a)
        for i in range(3):
            grav[i] += 0.02 * (a[i] - grav[i])
        n += 1
        if n % 60 == 0:
            send("gravity=({:.2f},{:.2f},{:.2f}) vbat={}mV".format(
                grav[0], grav[1], grav[2], M5.Power.getBatteryVoltage()))
        await asyncio.sleep_ms(50)
"""

RECIPES = {
    "state": {
        "args": [("still_dps", float, 10.0)],
        "code": """
async def run():
    # THE CALIBRATION VIEW — exactly the sense the seed runs, at
    # STILL_DPS={still_dps}, printing the three numbers it journals.
    #
    # Sit, fidget, walk, press. Watch that:
    #   (a) rot settles to a few dps when you hold still
    #   (b) lean reads near 0,0 when you sit the way you mean to — and note
    #       how far off zero it actually sits, because THAT is your mount
    #       offset, the constant few degrees from hanging on a neck
    #   (c) still climbs while you hold and snaps to 0 when you move
    #   (d) up reads X-. Anything else and it is not on a back.
    #
    # If the still/moving line falls in the wrong place, re-run with a
    # different number: `state 8` is more sensitive, `state 14` less.
    STILL_DPS = {still_dps}
    GRAV_TAU_S, ROT_TAU_S = 1.0, 1.0
    grav, rot_ema, still_since, last_t = None, 0.0, None, time.ticks_ms() / 1000.0
    send("state: sense running at STILL_DPS={still_dps}")
    n = 0
    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:
            dt = 0.0
        a = Imu.getAccel()
        g = Imu.getGyro()
        M5.update()
        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        rot_ema += min(1.0, dt / ROT_TAU_S) * (rot - rot_ema)
        if grav is None:
            grav = list(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            grav[i] += k * (a[i] - grav[i])
        quiet = rot_ema < STILL_DPS
        if quiet and still_since is None:
            still_since = now
        elif not quiet:
            still_since = None
        still = 0.0 if still_since is None else now - still_since
        if Button.pressed():
            send("PRESS")
        n += 1
        if n % 50 == 0:      # ~1 s at 50 Hz
            fwd = math.degrees(math.atan2(grav[2], -grav[0]))
            side = math.degrees(math.atan2(grav[1], -grav[0]))
            i = 0
            if abs(grav[1]) > abs(grav[i]):
                i = 1
            if abs(grav[2]) > abs(grav[i]):
                i = 2
            up = "XYZ"[i] + ("+" if grav[i] > 0 else "-")
            send("still {{:5.1f}}s | lean {{:+.1f}},{{:+.1f}} | rot {{:5.1f}}"
                 " | up {{}}".format(still, fwd, side, rot_ema, up))
        await asyncio.sleep_ms(20)
""",
    },
    "offset": {
        "args": [("secs", float, 20.0)],
        "code": """
async def run():
    # YOUR MOUNT OFFSET, measured directly. Stand up and stay standing for
    # {secs}s. Standing, your spine is near true vertical, so whatever lean
    # this reads is not your posture — it is where the strap hangs.
    #
    # This is the same measurement the seed takes for free from every walk to
    # the coffee machine; doing it deliberately once tells you what to expect
    # and whether the walk estimate agrees. Run it again after re-mounting to
    # see how much placement actually varies.
    #
    # The two numbers it prints are ZERO_FWD and ZERO_SIDE in the seed.
    GRAV_TAU_S = 1.0
    grav, last_t = None, time.ticks_ms() / 1000.0
    send("offset: STAND UP and hold still for {secs}s...")
    t0 = time.ticks_ms() / 1000.0
    fwds = Calc.Running(200)
    sides = Calc.Running(200)
    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:
            dt = 0.0
        a = Imu.getAccel()
        if grav is None:
            grav = list(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            grav[i] += k * (a[i] - grav[i])
        if now - t0 > 2.0:           # let gravity converge before counting
            fwds.push(math.degrees(math.atan2(grav[2], -grav[0])))
            sides.push(math.degrees(math.atan2(grav[1], -grav[0])))
        if now - t0 > {secs}:
            send("=== ZERO_FWD = {{:+.1f}}  ZERO_SIDE = {{:+.1f}}  "
                 "(spread {{:.1f}},{{:.1f}} over {{}} samples) ===".format(
                     fwds.mean(), sides.mean(), fwds.std(), sides.std(),
                     len(fwds.buf)))
            send("put those in the seed's ZERO_FWD / ZERO_SIDE")
            while True:
                await asyncio.sleep(1)
        await asyncio.sleep_ms(20)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    # Raw IMU, unsmoothed — the noise floor the sense sits on. STILL_DPS
    # should be comfortably above the gyro magnitude you see here holding
    # still, and comfortably below what a real movement produces.
    send("imulog: raw accel + gyro means")
    WINDOW = 30
    ba, bg = [], []
    while True:
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()
        ba.append((ax, ay, az))
        bg.append((gx, gy, gz))
        if len(ba) > WINDOW:
            ba.pop(0)
            bg.pop(0)
        if len(ba) == WINDOW:
            n = WINDOW
            ma = [sum(v[i] for v in ba) / n for i in range(3)]
            mg = [sum(v[i] for v in bg) / n for i in range(3)]
            mag = math.sqrt(sum(x * x for x in mg))
            send("accel=({:.3f},{:.3f},{:.3f}) gyro=({:.1f},{:.1f},{:.1f}) "
                 "|gyro|={:.1f}".format(ma[0], ma[1], ma[2],
                                        mg[0], mg[1], mg[2], mag))
            ba.clear()
            bg.clear()
        await asyncio.sleep_ms(10)
""",
    },
    "cricket": {
        "args": [("variant", int, 1), ("vol", int, 60)],
        "code": """
async def run():
    # The cricket VOCABULARY on the internal speaker: variant {variant} at
    # volume {vol} (0..255), one call every 4 s, forever. The direction is
    # the meaning:
    #   1 trill — level, alternating: presence without direction
    #   2 up    — rising sweep: the reminder ("lift")
    #   3 down  — falling sweep: the release ("there you are")
    # StickS3 speaker gotcha: tones sound only while M5.update() ticks.
    V = {variant}
    SHAPES = {{
        1: ((3900, 4600, 3900, 4600, 3900, 4600), 30),
        2: ((3500, 3800, 4200, 4600, 4800), 25),
        3: ((4800, 4600, 4200, 3800, 3500), 25),
    }}
    freqs, ms = SHAPES[V]
    send("cricket variant {variant} vol {vol} — every 4s; `off` to stop")
    while True:
        Speaker.begin()                # begin/end per call: the amp
        Speaker.setVolume({vol})       # idles audibly if left on
        for f in freqs:
            Speaker.tone(f, ms)
            M5.update()
            await asyncio.sleep_ms(ms + 15)
        Speaker.end()
        await asyncio.sleep_ms(4000)
""",
    },
    "button": {
        "args": [],
        "code": """
async def run():
    # The explicit channel, end to end. Button.pressed() is True once per
    # press, latched by the body and consumed on read — so a press is never
    # reported twice and never missed by a slow poll. last_s() is seconds
    # since the most recent press, and is NOT consumed by reading it.
    #
    # Confirmed working on hardware 2026-07-30 with btn=cb:WAS_PRESSED, so
    # the driver callback fires on the press edge. The BOOT line still names
    # which edge is live.
    send("button test: press BtnA. Slowly first, then as fast as you can.")
    n = 0
    while True:
        if Button.pressed():
            n += 1
            send("PRESS #{} — last_s now {:.2f}".format(n, Button.last_s()))
        await asyncio.sleep_ms(20)
""",
    },
    "lowbat": {
        "args": [("vol", int, 100)],
        "code": """
async def run():
    # The dying cricket — the low-battery alarm, at volume {vol} (0..255),
    # repeating every 6 s so you can judge it; `off` to stop. In real life
    # it plays ONCE, right before the final battery sync.
    send("lowbat alarm audition at vol {vol} — every 6s; `off` to stop")
    while True:
        Speaker.begin()
        Speaker.setVolume({vol})
        for _ in range(2):
            for f in (3000, 2400, 1800):
                Speaker.tone(f, 130)
                M5.update()
                await asyncio.sleep_ms(150)
            await asyncio.sleep_ms(350)
        Speaker.end()
        await asyncio.sleep_ms(6000)
""",
    },
    "vbat": {
        "args": [],
        "code": """
async def run():
    send("vbat: live battery")
    while True:
        send("vbat={}mV bat={}% charging={}".format(
            M5.Power.getBatteryVoltage(), M5.Power.getBatteryLevel(),
            M5.Power.isCharging()))
        await asyncio.sleep_ms(2000)
""",
    },
    "power": {
        "args": [],
        "code": """
async def run():
    # Charging-flag forensics: isCharging() flipping while plugged in is
    # benign top-off cycling ONLY if VBUS holds ~5V through the flip. VBUS
    # collapsing with the flip = the 5V input really cut out (flaky jack, a
    # smart charger's low-current auto-off, or a bank that has decided you
    # are not drawing enough to be worth staying awake for — measured
    # 2026-07-30, which is what the PowerBoost replaced).
    send("power: 1Hz vbus/vbat/chg — watch VBUS when chg flips")
    try:
        M5.Power.getBatteryCurrent()
        has_i = True
    except Exception:
        has_i = False
        send("(no getBatteryCurrent on this PMIC — logging without it)")
    last = None
    while True:
        vbus = M5.Power.getVBUSVoltage()
        vbat = M5.Power.getBatteryVoltage()
        chg = M5.Power.isCharging()
        extra = " i={}mA".format(M5.Power.getBatteryCurrent()) if has_i else ""
        if last is not None and chg != last:
            send("CHG FLIP {}->{}  vbus={}mV vbat={}mV{}".format(
                last, chg, vbus, vbat, extra))
        last = chg
        send("pwr vbus={}mV vbat={}mV chg={}{}".format(vbus, vbat, chg, extra))
        await asyncio.sleep_ms(1000)
""",
    },
    "off": {
        "args": [],
        "code": """
async def run():
    try:
        Speaker.end()
    except Exception:
        pass
    send("silenced")
    while True:
        await asyncio.sleep(1)
""",
    },
}
