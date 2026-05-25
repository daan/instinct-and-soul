"""
recipes.py — instinct templates for the puppyc tuner.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.

All gait recipes go through set_leg/set_all so per-leg TRIM (calibrated in
main.py) is always respected.
"""

INSTINCT_IDLE = """
async def run():
    center_all()
    while True:
        ax, ay, az = Imu.getAccel()
        send("idle ax={:.3f} ay={:.3f} az={:.3f}".format(ax, ay, az))
        await asyncio.sleep(2)
"""

RECIPES = {
    "center": {
        "args": [],
        "code": """
async def run():
    center_all()
    send("centered")
    while True:
        await asyncio.sleep(1)
""",
    },
    "pose": {
        "args": [("fl", int, 90), ("fr", int, 90), ("bl", int, 90), ("br", int, 90)],
        "code": """
async def run():
    set_all({fl}, {fr}, {bl}, {br})
    send("pose fl={fl} fr={fr} bl={bl} br={br}")
    while True:
        await asyncio.sleep(1)
""",
    },
    "wiggle": {
        "args": [("leg", int, 0), ("amp", int, 30)],
        "code": """
async def run():
    center_all()
    await asyncio.sleep_ms(300)
    leg = {leg}
    amp = {amp}
    send("wiggle leg={leg} amp={amp}")
    import math as _math
    i = 0
    while True:
        v = int(amp * _math.sin(i * 0.2))
        set_leg(leg, 90 + v)
        i += 1
        await asyncio.sleep_ms(40)
""",
    },
    "calibrate": {
        "args": [("amp", int, 40)],
        "code": """
async def run():
    amp = {amp}
    center_all()
    await asyncio.sleep(1)
    for label, leg in (("FL", FL), ("FR", FR), ("BL", BL), ("BR", BR)):
        send("calibrate " + label + " forward")
        for a in range(0, amp + 1, 2):
            set_leg(leg, 90 + a)
            await asyncio.sleep_ms(20)
        await asyncio.sleep(1)
        for a in range(amp, -1, -2):
            set_leg(leg, 90 + a)
            await asyncio.sleep_ms(20)
        await asyncio.sleep_ms(400)
    send("calibrate done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "trot": {
        "args": [("amp", int, 40), ("period", int, 500), ("duty", int, 65)],
        "code": """
async def run():
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    def phase(t):
        t = t % 1.0
        if t < DUTY:
            return AMP - 2 * AMP * (t / DUTY)
        return -AMP + 2 * AMP * ((t - DUTY) / (1 - DUTY))
    center_all()
    await asyncio.sleep_ms(300)
    send("trot amp={amp} period={period} duty={duty}/100")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        a = phase(t)
        b = phase(t + 0.5)
        set_all(90 + a, 90 + b, 90 + b, 90 + a)
        if i % 50 == 0:
            ax, ay, az = Imu.getAccel()
            send("trot tick={{}} ax={{:.2f}} ay={{:.2f}} az={{:.2f}}".format(i, ax, ay, az))
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "pronk": {
        "args": [("amp", int, 35), ("period", int, 450), ("duty", int, 60)],
        "code": """
async def run():
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    def phase(t):
        t = t % 1.0
        if t < DUTY:
            return AMP - 2 * AMP * (t / DUTY)
        return -AMP + 2 * AMP * ((t - DUTY) / (1 - DUTY))
    center_all()
    await asyncio.sleep_ms(300)
    send("pronk amp={amp} period={period} duty={duty}/100")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        a = phase(t)
        set_all(90 + a, 90 + a, 90 + a, 90 + a)
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "walk": {
        "args": [("amp", int, 35), ("period", int, 800), ("duty", int, 75)],
        "code": """
async def run():
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    def phase(t):
        t = t % 1.0
        if t < DUTY:
            return AMP - 2 * AMP * (t / DUTY)
        return -AMP + 2 * AMP * ((t - DUTY) / (1 - DUTY))
    OFFSETS = {{FL: 0.0, BR: 0.25, FR: 0.5, BL: 0.75}}
    center_all()
    await asyncio.sleep_ms(300)
    send("walk amp={amp} period={period} duty={duty}/100")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        fl = 90 + phase(t + OFFSETS[FL])
        fr = 90 + phase(t + OFFSETS[FR])
        bl = 90 + phase(t + OFFSETS[BL])
        br = 90 + phase(t + OFFSETS[BR])
        set_all(fl, fr, bl, br)
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "wave": {
        "args": [("leg", int, 0)],
        "code": """
async def run():
    import math as _math
    center_all()
    await asyncio.sleep_ms(300)
    leg = {leg}
    send("wave leg=" + str(leg))
    # one-paw hello: cycle that leg up/forward while others hold
    for k in range(4):
        for i in range(40):
            v = int(40 * _math.sin(i * 0.16))
            set_leg(leg, 90 + 30 + v)
            await asyncio.sleep_ms(30)
    set_leg(leg, 90)
    send("wave done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "sit": {
        "args": [],
        "code": """
async def run():
    # legs tucked back: front centred, rear folded
    set_all(90, 90, 50, 50)
    send("sit")
    while True:
        await asyncio.sleep(1)
""",
    },
    "stand": {
        "args": [],
        "code": """
async def run():
    set_all(90, 90, 90, 90)
    send("stand")
    while True:
        await asyncio.sleep(1)
""",
    },
    "rest": {
        "args": [],
        "code": """
async def run():
    # legs out to the sides — relieves servo load for storage
    set_all(30, 30, 30, 30)
    send("rest")
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    center_all()
    send("imulog: streaming accel + gyro")
    while True:
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()
        send("accel x={:.3f} y={:.3f} z={:.3f} gyro x={:.1f} y={:.1f} z={:.1f}".format(
            ax, ay, az, gx, gy, gz))
        await asyncio.sleep_ms(100)
""",
    },
    "miclog": {
        # Stream peak + RMS amplitude of the PDM mic in short windows.
        # Tune thresholds for clap / voice detection, then commit a value
        # to the seed_instinct.
        # Mic shares I2S with Speaker — Speaker.end() first to free the bus.
        "args": [("rate", int, 16000), ("window_ms", int, 50)],
        "code": """
async def run():
    import struct as _struct
    try:
        from M5 import Mic
    except ImportError:
        send("CRASH: M5.Mic not available in this UIFlow build")
        return

    rate = {rate}
    window_ms = {window_ms}
    samples = (rate * window_ms) // 1000
    buf = bytearray(samples * 2)

    try:
        Speaker.end()
    except Exception:
        pass

    try:
        Mic.begin()
    except Exception as e:
        send("CRASH: Mic.begin failed: " + str(e))
        return

    send("miclog rate={rate} window_ms={window_ms} samples=" + str(samples))
    try:
        while True:
            try:
                Mic.record(buf, rate, False)
            except Exception as e:
                send("mic record error: " + str(e))
                await asyncio.sleep(1)
                continue
            peak = 0
            sq_sum = 0
            for i in range(0, len(buf), 2):
                v = _struct.unpack_from('<h', buf, i)[0]
                a = v if v >= 0 else -v
                if a > peak:
                    peak = a
                sq_sum += v * v
            rms = int((sq_sum / samples) ** 0.5)
            send("mic peak={{}} rms={{}}".format(peak, rms))
            await asyncio.sleep_ms(0)
    finally:
        try:
            Mic.end()
        except Exception:
            pass
""",
    },
    "stop": {
        "args": [],
        "code": """
async def run():
    center_all()
    send("stopped")
    while True:
        await asyncio.sleep(5)
""",
    },
    "back": {
        "args": [("amp", int, 40), ("period", int, 500), ("duty", int, 65)],
        "code": """
async def run():
    AMP = -{amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    def phase(t):
        t = t % 1.0
        if t < DUTY:
            return AMP - 2 * AMP * (t / DUTY)
        return -AMP + 2 * AMP * ((t - DUTY) / (1 - DUTY))
    center_all()
    await asyncio.sleep_ms(300)
    send("back amp={amp} period={period} duty={duty}/100")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        a = phase(t)
        b = phase(t + 0.5)
        set_all(90 + a, 90 + b, 90 + b, 90 + a)
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "rotate": {
        # sign: +1 = ccw (left turn), -1 = cw (right turn).
        # Both sides keep the propulsive (slow-stance, fast-swing) shape so
        # the curved legs always grip; left side trots forward, right side
        # trots backward (or vice versa via sign).
        "args": [("sign", int, 1), ("seconds", int, 4), ("amp", int, 40),
                 ("period", int, 500), ("duty", int, 65)],
        "code": """
async def run():
    SIGN = {sign}
    SECONDS = {seconds}
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    AMP_L = SIGN * AMP          # left legs (FL, BL) — sign of amp = direction
    AMP_R = -SIGN * AMP         # right legs (FR, BR) — opposite direction
    def phase(t, amp):
        t = t % 1.0
        if t < DUTY:
            return amp - 2 * amp * (t / DUTY)
        return -amp + 2 * amp * ((t - DUTY) / (1 - DUTY))
    center_all()
    await asyncio.sleep_ms(300)
    label = "ccw" if SIGN > 0 else "cw"
    send("rotate " + label + " for {seconds}s amp={amp} period={period}")
    steps = int(SECONDS * 1000 / DT_MS)
    for i in range(steps):
        t = (i * DT_MS / PERIOD_MS)
        # Diagonal trot pairing preserved: FL+BR get phase t, FR+BL get t+0.5
        fl = 90 + phase(t,       AMP_L)
        br = 90 + phase(t,       AMP_R)
        fr = 90 + phase(t + 0.5, AMP_R)
        bl = 90 + phase(t + 0.5, AMP_L)
        set_all(fl, fr, bl, br)
        await asyncio.sleep_ms(DT_MS)
    center_all()
    send("rotate done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "circle": {
        # Tilt in a circle in place. Each leg's angle traces a sine wave,
        # with FL/FR/BR/BL lagged by 0/0.25/0.5/0.75 of a cycle. The peak
        # leg position orbits the corners; the body rocks in a circle.
        # No translation — set_leg displacement is symmetric, so net force
        # averages out.
        "args": [("sign", int, 1), ("amp", int, 25), ("period", int, 2000)],
        "code": """
async def run():
    import math as _math
    SIGN = {sign}            # +1 cw orbit (FL -> FR -> BR -> BL), -1 ccw
    AMP = {amp}
    PERIOD_MS = {period}
    DT_MS = 20
    TWO_PI = 2 * _math.pi
    LAGS = (0.0, 0.25, 0.5, 0.75)   # FL, FR, BR, BL
    center_all()
    await asyncio.sleep_ms(300)
    label = "cw" if SIGN > 0 else "ccw"
    send("circle " + label + " amp={amp} period={period}ms")
    i = 0
    while True:
        t = i * DT_MS / PERIOD_MS
        fl = 90 + AMP * _math.sin(TWO_PI * SIGN * (t - LAGS[0]))
        fr = 90 + AMP * _math.sin(TWO_PI * SIGN * (t - LAGS[1]))
        br = 90 + AMP * _math.sin(TWO_PI * SIGN * (t - LAGS[2]))
        bl = 90 + AMP * _math.sin(TWO_PI * SIGN * (t - LAGS[3]))
        set_all(fl, fr, bl, br)
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "rotate180": {
        # Closed-loop rotation: integrate gyro Z until target_deg is reached.
        # No magnetometer needed — we only need *relative* yaw from start.
        # First calibrates gz bias for ~0.5s at rest.
        "args": [("sign", int, 1), ("target_deg", int, 180), ("amp", int, 40),
                 ("period", int, 500), ("duty", int, 65), ("timeout_s", int, 12)],
        "code": """
async def run():
    SIGN = {sign}
    TARGET_DEG = {target_deg}
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    DT_MS = 20
    AMP_L = SIGN * AMP
    AMP_R = -SIGN * AMP

    def phase(t, amp):
        t = t % 1.0
        if t < DUTY:
            return amp - 2 * amp * (t / DUTY)
        return -amp + 2 * amp * ((t - DUTY) / (1 - DUTY))

    center_all()
    await asyncio.sleep_ms(500)

    # 1) Calibrate gyro Z bias at rest (~0.5s).
    samples = 0
    bias_sum = 0.0
    for _ in range(25):
        _, _, gz = Imu.getGyro()
        bias_sum += gz
        samples += 1
        await asyncio.sleep_ms(20)
    gz_bias = bias_sum / samples
    send("rotate180 bias={{:.3f}} deg/s target={target_deg} sign={sign}".format(gz_bias))

    # 2) Rotate until |yaw| >= target_deg, with a timeout safety net.
    yaw = 0.0
    started_ms = time.ticks_ms()
    last_ms = started_ms
    timeout_ms = {timeout_s} * 1000
    i = 0
    while abs(yaw) < TARGET_DEG:
        now = time.ticks_ms()
        if time.ticks_diff(now, started_ms) > timeout_ms:
            send("rotate180 TIMEOUT at yaw={{:.1f}}".format(yaw))
            break
        _, _, gz = Imu.getGyro()
        dt = time.ticks_diff(now, last_ms) / 1000.0
        last_ms = now
        yaw += (gz - gz_bias) * dt

        t = (i * DT_MS / PERIOD_MS)
        fl = 90 + phase(t,       AMP_L)
        br = 90 + phase(t,       AMP_R)
        fr = 90 + phase(t + 0.5, AMP_R)
        bl = 90 + phase(t + 0.5, AMP_L)
        set_all(fl, fr, bl, br)

        if i % 25 == 0:
            send("rotate180 yaw={{:.1f}}".format(yaw))
        i += 1
        await asyncio.sleep_ms(DT_MS)

    center_all()
    send("rotate180 done yaw={{:.1f}}".format(yaw))
    while True:
        await asyncio.sleep(1)
""",
    },
}
