"""
recipes.py — instinct templates for the tilt tuner.

This body is a PLAIN StickS3 — internal speaker and IMU, nothing attached.
The tuner's jobs before anyone wears it for real: find the CRICKET (a chirp
subtle enough to be missable — five designs to audition, each looping so
you can live with it a while) and calibrate the POSTURE read on a real back
(capture upright, watch the angle while sitting well and slouching).

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
    n = 0
    while True:
        Imu.getAccel()
        Imu.getGyro()
        n += 1
        if n % 60 == 0:
            a = Posture.angle()
            send("posture={} still={:.0f}s vbat={}mV".format(
                a if a is not None else "no-ref", Posture.still_s(),
                M5.Power.getBatteryVoltage()))
        await asyncio.sleep_ms(50)
"""

RECIPES = {
    "state": {
        "args": [],
        "code": """
async def run():
    # The condition_2 calibration view: exactly the three numbers the seed
    # journals. Sit, fidget, walk, tap. Watch that (a) rot settles to a few
    # dps when you hold still, (b) lean reads ~0,0 after the capture below,
    # and (c) your taps land. STILL_DPS is the line between still and not;
    # TAP_G is the line between a tap and body motion.
    send("state: capturing upright in 3s — sit the way you mean it...")
    t0 = time.ticks_ms()
    while time.ticks_ms() - t0 < 3000:
        Imu.getAccel()
        Imu.getGyro()
        await asyncio.sleep_ms(20)
    send("upright captured" if Posture.set_upright() else "capture FAILED")
    n = 0
    while True:
        Imu.getAccel()
        Imu.getGyro()
        if Tap.tapped():
            send("TAP")
        n += 1
        if n % 50 == 0:      # ~1 s at 50 Hz
            lr = Posture.lean_ref()
            send("still {:5.1f}s | lean {:+.1f},{:+.1f} | rot {:5.1f} | up {}".format(
                Posture.still_s(), lr[0] if lr else 0.0, lr[1] if lr else 0.0,
                Posture.rot(), Posture.up_axis()))
        await asyncio.sleep_ms(20)
""",
    },
    "posture": {
        "args": [],
        "code": """
async def run():
    # Anatomical frame (measured worn): upright = 0; bending FORWARD is
    # positive, +90 = lying on the belly; bending BACK negative, -90 =
    # lying on the back. Upright gravity sits on X- for this mounting.
    send("posture: live. sit well, slouch fwd/back, lean side, walk")
    if not Posture.has_ref():
        send("NO UPRIGHT REFERENCE — sit the way you'd like to be reminded "
             "toward, hold still, then run `setref`")
    warned = False
    while True:
        Imu.getAccel()
        Imu.getGyro()
        a = Posture.angle()
        lean = Posture.lean()
        up = Posture.up_axis()
        if lean:
            send("fwd/back={:+.0f} side={:+.0f} | vs-ref={} | up={} | still={:.1f}s".format(
                lean[0], lean[1], a if a is not None else "no-ref",
                up, Posture.still_s()))
        if up and up != "X-" and Posture.still_s() > 3.0 and not warned:
            send("MOUNTING CHECK: upright should read up=X-, but I read "
                 "up={} — is the stick worn with the X axis along the spine?".format(up))
            warned = True
        await asyncio.sleep_ms(1000)
""",
    },
    "setref": {
        "args": [],
        "code": """
async def run():
    send("capturing upright in 3s — sit the way you mean it...")
    t0 = time.ticks_ms()
    while time.ticks_ms() - t0 < 3000:
        Imu.getAccel()
        Imu.getGyro()
        await asyncio.sleep_ms(20)
    ok = Posture.set_upright()
    send("upright captured" if ok else "capture FAILED (no gravity read yet)")
    while True:
        Imu.getAccel()
        Imu.getGyro()
        a = Posture.angle()
        send("angle={} deg | still={:.1f}s".format(
            a if a is not None else "no-ref", Posture.still_s()))
        await asyncio.sleep_ms(1000)
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
    "verbs": {
        "args": [],
        "code": """
async def run():
    # Movement-verb tuning, worn: sit still, fidget, shift your lean,
    # stretch big, stand up and walk off — each settled episode gets named.
    # No upright reference needed (verbs compare pose-to-pose). Thresholds
    # to tune in organs.py: SHIFT_DEG, STRETCH_DEG, AWAY_S, EP_SETTLE_S.
    send("verbs: move and watch. fidget / lean / stretch / walk off...")
    n = 0
    while True:
        Imu.getAccel()
        Imu.getGyro()
        v = Posture.verb()
        if v:
            send("{}({})".format(v[0], v[1]) if v[1] else v[0])
        n += 1
        if n % 150 == 0:   # every ~3s at 50Hz: the ongoing state
            send("... {} | still {:.0f}s | lean fwd {:+.0f} side {:+.0f}".format(
                Posture.flavor(), Posture.still_s(), *(Posture.lean() or (0, 0))))
        await asyncio.sleep_ms(20)
""",
    },
    "tap": {
        "args": [],
        "code": """
async def run():
    # Tap test: polls FAST (200 Hz — spikes are short) and reports every
    # burst plus a rolling 2 s peak so TAP_G (organs.py) can be calibrated:
    # your taps should read well above the peaks of walking/adjusting.
    send("tap test: tap once, tap twice, walk around — watch the numbers")
    last_report = time.ticks_ms()
    while True:
        Imu.getAccel()
        Imu.getGyro()
        b = Tap.burst()
        if b:
            send("TAP x{} !".format(b[1]))
        if time.ticks_ms() - last_report > 2000:
            send("2s peak: {:.2f} g   (tap threshold TAP_G = 1.2)".format(Tap.peak()))
            last_report = time.ticks_ms()
        await asyncio.sleep_ms(5)
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
    # collapsing with the flip = the 5V input really cut out (flaky jack,
    # or a smart charger's low-current auto-off).
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
    "imulog": {
        "args": [],
        "code": """
async def run():
    send("imulog: live accel + gyro means")
    WINDOW = 30
    ba = []
    bg = []
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
            send("accel=({:.3f},{:.3f},{:.3f}) gyro=({:.1f},{:.1f},{:.1f})".format(
                ma[0], ma[1], ma[2], mg[0], mg[1], mg[2]))
            ba.clear()
            bg.clear()
        await asyncio.sleep_ms(10)
""",
    },
}
