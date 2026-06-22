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
    "autotrim": {
        # Per-leg touch-point search using the IMU.
        #
        # Step 1 — establish a belly-down reference. All four legs are folded
        # high so the chassis rests on its belly (flat). The gravity vector
        # in that pose IS the stick's mount-tilt offset; we subtract it from
        # later readings so any residual tilt comes purely from leg loading.
        #
        # Step 2 — sweep each leg from LO to HI. The angle of maximum tilt
        # deviation from the belly reference is the touch peak (where the
        # foot pushes hardest into the ground = horn closest to vertical).
        #
        # New TRIM offset = current_offset + direction * (peak_angle - 90).
        # Run on a flat surface.
        "args": [],
        "code": """
async def run():
    LO = 70
    HI = 110
    STEP = 1
    SETTLE_MS = 200
    SAMPLES = 4

    async def measure_vec():
        sx = sy = sz = 0.0
        for _ in range(SAMPLES):
            ax, ay, az = Imu.getAccel()
            sx += ax; sy += ay; sz += az
            await asyncio.sleep_ms(15)
        return sx / SAMPLES, sy / SAMPLES, sz / SAMPLES

    # Step 1: belly-down reference (rest pose — legs out to the sides).
    # Body rests on its belly; IMU reading IS the stick mount tilt.
    set_all(30, 30, 30, 30)
    await asyncio.sleep_ms(800)
    bx, by, bz = await measure_vec()
    send("autotrim: belly ref ax={:.3f} ay={:.3f} az={:.3f}".format(bx, by, bz))

    # Step 2: per-leg sweep with the other three legs kept at rest. The
    # chassis stays on its belly except where the sweeping leg pushes it
    # up. Tilt deviation from the belly reference peaks at the angle where
    # the horn is closest to vertical (max foot extension).
    peaks = {}
    for leg, name in ((FL, "FL"), (FR, "FR"), (BL, "BL"), (BR, "BR")):
        set_all(30, 30, 30, 30)
        await asyncio.sleep_ms(400)
        send("autotrim: sweeping " + name)
        best_angle = 90
        best_dev = -1.0
        for angle in range(LO, HI + 1, STEP):
            set_leg(leg, angle)
            await asyncio.sleep_ms(SETTLE_MS)
            ax, ay, az = await measure_vec()
            dx, dy, dz = ax - bx, ay - by, az - bz
            dev = math.sqrt(dx*dx + dy*dy + dz*dz)
            send("autotrim {} angle={} dev={:.4f}".format(name, angle, dev))
            if dev > best_dev:
                best_dev = dev
                best_angle = angle
        peaks[name] = best_angle
        send("autotrim {} peak_angle={} dev={:.4f}".format(name, best_angle, best_dev))

    send("autotrim: new TRIM offsets:")
    cal = {}
    for leg, name in ((FL, "FL"), (FR, "FR"), (BL, "BL"), (BR, "BR")):
        direction, current = TRIM[leg]
        new_off = current + direction * (peaks[name] - 90)
        send("    {}: ({:+d}, {:+d})  # was ({:+d}, {:+d}), peak={}".format(
            name, direction, new_off, direction, current, peaks[name]))
        TRIM[leg] = (direction, new_off)
        cal[name] = new_off

    center_all()
    try:
        import json
        with open("/flash/calibration.json", "w") as f:
            json.dump(cal, f)
        send("autotrim: saved /flash/calibration.json " + str(cal))
    except Exception as e:
        send("autotrim: save failed: " + repr(e))
    while True:
        await asyncio.sleep(1)
""",
    },
    "trimdump": {
        # One-shot dump of the live TRIM dict. The servo HAT takes one byte
        # per channel (see _write_servo in main.py), so int degrees IS the
        # native resolution — fractional commands would be quantised away.
        # For command 90, the written servo angle is simply 90 + offset
        # (direction only affects non-centre commands).
        "args": [],
        "code": """
async def run():
    send("trimdump:")
    for name, leg in (("FL", FL), ("FR", FR), ("BL", BL), ("BR", BR)):
        direction, offset = TRIM[leg]
        send("  {} dir={:+d} offset={:+d}  cmd=90 -> servo={}".format(
            name, direction, offset, 90 + offset))
    center_all()
    send("trimdump: centered")
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
    "tone": {
        # Play one tone for ms milliseconds. Hardware verification for the
        # speaker — does NOT touch servos or ToF.
        "args": [("freq", int, 440), ("ms", int, 500)],
        "code": """
async def run():
    Speaker.begin()
    Speaker.setVolume(64)
    send("tone freq={freq} ms={ms}")
    steps = max(1, {ms} // 50)
    for _ in range(steps):
        Speaker.tone({freq}, 80)
        M5.update()
        await asyncio.sleep_ms(50)
    Speaker.end()
    send("tone done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "toflog": {
        # Stream VL53L0X distance readings. Hardware verification for the ToF
        # — does NOT touch servos or speaker. Uses the driver's non-blocking
        # API: blocking .range raises OSError under concurrent asyncio/WiFi
        # load, async polling of reading_available() does not.
        "args": [],
        "code": """
async def run():
    if tof is None:
        send("toflog: sensor not available (check VL53L0X wiring)")
        while True:
            await asyncio.sleep(5)
    send("toflog: streaming distance")
    while True:
        tof.start_range_request()
        while not tof.reading_available():
            await asyncio.sleep_ms(5)
        d = tof.get_range_value()
        send("tof distance={} mm".format(d))
        await asyncio.sleep_ms(100)
""",
    },
    "theremin": {
        # Combined hardware test: ToF distance modulates speaker pitch.
        # Closer = higher pitch. Silent when out of range. No servo motion.
        # If all three subsystems (sound, ToF, instinct loop) work, you'll
        # hear pitch follow your hand smoothly.
        "args": [("min_mm", int, 30), ("max_mm", int, 600)],
        "code": """
async def run():
    if read_distance_mm() is None:
        send("theremin: ToF not available")
        while True:
            await asyncio.sleep(5)
    MIN_MM = {min_mm}
    MAX_MM = {max_mm}
    MIN_HZ = 200
    MAX_HZ = 1500
    Speaker.begin()
    Speaker.setVolume(64)
    send("theremin {min_mm}..{max_mm}mm -> 200..1500Hz")
    try:
        while True:
            d = read_distance_mm()
            if d is None or d <= 0 or d > MAX_MM:
                await asyncio.sleep_ms(40)
                continue
            d_clamped = max(MIN_MM, min(MAX_MM, d))
            frac = 1.0 - (d_clamped - MIN_MM) / (MAX_MM - MIN_MM)
            freq = int(MIN_HZ + frac * (MAX_HZ - MIN_HZ))
            Speaker.tone(freq, 80)
            M5.update()
            await asyncio.sleep_ms(40)
    finally:
        Speaker.end()
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
