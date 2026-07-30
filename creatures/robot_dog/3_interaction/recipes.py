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
        # A TRAVEL AND TRIM CHECK, not a gait — one leg at a time, nothing
        # locomotes. `amp` is how far forward of its trimmed centre each leg
        # sweeps, in degrees: 0 -> +amp -> hold 1 s -> back to 0, at 2° per
        # 20 ms (~95 °/s). The default is 40 on purpose — it is the trot's
        # amplitude, so what you are checking is exactly the range the gait
        # will use: does the leg reach +40° without binding on a mechanical
        # limit, and does it come back to a level stance. Raise it only to
        # find where the travel actually ends (>50° risks the servo stop).
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
        "args": [("amp", int, 30), ("period", int, 1000), ("duty", int, 65),
                 ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY                  # 0..1 through the slow stance
        else:
            u = (u - DUTY) / (1 - DUTY)   # 0..1 through the fast swing
            amp = -amp
        if SMOOTH:
            # Cosine ends: commanded VELOCITY is zero at both reversals, so
            # the servo never receives a step change of direction. BUT zero
            # velocity at the reversal IS a dwell at the extreme leg angle —
            # 46% of the cycle beyond 80% of amp, against the triangle's 23%
            # — and on a tall chassis (camera upright) that dwell outlasts the
            # pendulum time constant and tips the body over. Default is OFF;
            # use PERIOD, not the waveform, to get gentle. See tune.py.
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u          # the triangle: brief at the extremes
    center_all()
    await asyncio.sleep_ms(300)
    send("trot amp={amp} period={period} duty={duty}/100 smooth={smooth}")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        # Soft start: from a dead stop, the first swing at full amplitude was
        # the most violent event of the whole run. Ease it in.
        g = min(1.0, t / RAMP_CYCLES)
        a = g * phase(t, AMP)
        b = g * phase(t + 0.5, AMP)
        set_all(90 + a, 90 + b, 90 + b, 90 + a)
        if i % 50 == 0:
            ax, ay, az = Imu.getAccel()
            send("trot tick={{}} ax={{:.2f}} ay={{:.2f}} az={{:.2f}}".format(i, ax, ay, az))
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "pronk": {
        "args": [("amp", int, 35), ("period", int, 450), ("duty", int, 60),
                 ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u
    center_all()
    await asyncio.sleep_ms(300)
    send("pronk amp={amp} period={period} duty={duty}/100 smooth={smooth}")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        g = min(1.0, t / RAMP_CYCLES)
        a = g * phase(t, AMP)
        set_all(90 + a, 90 + a, 90 + a, 90 + a)
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "walk": {
        "args": [("amp", int, 35), ("period", int, 800), ("duty", int, 75),
                 ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u
    OFFSETS = {{FL: 0.0, BR: 0.25, FR: 0.5, BL: 0.75}}
    center_all()
    await asyncio.sleep_ms(300)
    send("walk amp={amp} period={period} duty={duty}/100 smooth={smooth}")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        g = min(1.0, t / RAMP_CYCLES)
        fl = 90 + g * phase(t + OFFSETS[FL], AMP)
        fr = 90 + g * phase(t + OFFSETS[FR], AMP)
        bl = 90 + g * phase(t + OFFSETS[BL], AMP)
        br = 90 + g * phase(t + OFFSETS[BR], AMP)
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
        # Stream the ToF percept. In this stage the perception pump OWNS the
        # sensor, so an instinct must not drive it — start_range_request() from
        # here would fight the pump for the Grove bus. Read the organ instead;
        # this verifies the pump as well as the sensor.
        "args": [],
        "code": """
async def run():
    if ToF.read_distance_mm() is None:
        send("toflog: no ToF (check VL53L0X wiring)")
        while True:
            await asyncio.sleep(5)
    send("toflog: streaming the ToF percept")
    while True:
        send("tof distance={{}} mm age={{}} ms".format(
            ToF.read_distance_mm(), ToF.age_ms()))
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
    if ToF.read_distance_mm() is None:
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
            d = ToF.read_distance_mm()
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
    Legs.stop()
    center_all()
    send("stopped")
    while True:
        await asyncio.sleep(5)
""",
    },

    # ── Behaviours (blob + ToF) ────────────────────────────────────────────
    # These are the first recipes that CLOSE THE LOOP between the senses and
    # the legs, so three shared rules apply to all of them, and to anything
    # added beside them:
    #
    #   MOVE, THEN LOOK. While the legs run, the thermal centroid sloshes and
    #   the nose beam pitches with every stride. A reading taken mid-phrase is
    #   not news about the world. Every behaviour below stops, waits for
    #   Legs.since_still_ms() to pass SETTLE_MS, and only then reads. This
    #   makes them dog-like rather than smooth, and that is the honest shape.
    #
    #   THE TWO SENSES DISAGREE, AND THAT IS DATA. The camera is wide and only
    #   ordinal; the beam is metric but narrow. "Blob present, no echo" is the
    #   normal case at an angle, not a fault — it is reported, never averaged
    #   away or silently treated as "far".
    #
    #   RANGES ARE ROUNDED-OFF GUESSES. The mm thresholds here are drafted for
    #   a tabletop and a hand and have NOT been measured on this body (README
    #   missing item 6). They are tuner arguments precisely so you can find the
    #   real ones.

    "perc": {
        # The measurement instrument for the missing zone thresholds and the
        # blob-area-vs-distance curve: both senses on one line, at rest, so the
        # pairs can be regressed later. Put a hand at a known distance, read
        # the line, move the hand. No motion at all — the legs never run, so
        # nothing contaminates the readings.
        "args": [("period_ms", int, 500)],
        "code": """
async def run():
    Legs.stop()
    center_all()
    send("perc: blob + tof at rest, every {period_ms}ms — no motion")
    while True:
        b = Thermal.blob()
        mm = ToF.read_distance_mm()
        if b["present"]:
            send("perc present area={{}} exc={{:.1f}} cx={{:.1f}} cy={{:.1f}} "
                 "amb={{:.1f}} tof={{}} tof_age={{}} blob_age={{}}".format(
                     b["area"], b["excess_c"], b["cx"], b["cy"], b["ambient_c"],
                     mm, ToF.age_ms(), b["age_ms"]))
        else:
            send("perc absent amb={{:.1f}} delta={{:.1f}} tof={{}}".format(
                b["ambient_c"], Thermal.delta(), mm))
        await asyncio.sleep_ms({period_ms})
""",
    },

    "find": {
        # Sweep in place until a warm shape is BOTH visible and within range.
        # Turns in short phrases and looks between them, because a reading
        # taken while turning is worthless (see the shared rules above).
        #
        # It also integrates gyro-z through each phrase so it knows roughly how
        # far it has swept, and gives up after sweep_deg rather than spinning
        # forever. That yaw figure is honest but rough: the bias is sampled
        # only briefly and there is no compass to correct against.
        "args": [("max_mm", int, 500), ("pace", int, 60), ("sweep_deg", int, 360),
                 ("dir", int, 1)],
        "code": """
async def run():
    MAX_MM = {max_mm}
    PACE = {pace} / 100.0
    SWEEP_DEG = {sweep_deg}
    D = "ccw" if {dir} > 0 else "cw"
    SETTLE_MS = 400
    # Short enough not to sweep straight past a shape, but it MUST outlast the
    # organ's soft-start ramp (GAIT_RAMP_CYCLES) or the phrase ends before the
    # stride reaches full amplitude and the dog only twitches.
    PHRASE_CYCLES = 1.0

    Legs.stop()
    center_all()
    await asyncio.sleep_ms(600)

    # gyro-z bias, sampled at rest. Without this the yaw estimate drifts one
    # way regardless of which way we turn.
    bias = 0.0
    for _ in range(25):
        _gx, _gy, gz = Imu.getGyro()
        bias += gz
        await asyncio.sleep_ms(20)
    bias /= 25.0
    send("find: sweeping {{}} for a warm shape within {{}}mm "
         "(gz bias {{:.2f}} deg/s)".format(D, MAX_MM, bias))

    async def look():
        Legs.stop()
        while Legs.since_still_ms() < SETTLE_MS:
            await asyncio.sleep_ms(50)
        return Thermal.blob(), ToF.read_distance_mm()

    yaw = 0.0
    while True:
        b, mm = await look()
        if b["present"]:
            if mm is not None and 0 < mm <= MAX_MM:
                send("find: FOUND at tof={{}}mm area={{}} cx={{:.1f}} "
                     "after ~{{:.0f}} deg".format(mm, b["area"], b["cx"], yaw))
                Legs.stop()
                center_all()
                while True:
                    await asyncio.sleep(5)
            elif mm is None or mm <= 0:
                # The wide sense sees it, the narrow one does not. Expected at
                # an angle — keep turning to bring it onto the beam.
                send("find: shape at cx={{:.1f}} area={{}} but no echo — "
                     "turning it onto the beam (~{{:.0f}} deg)".format(
                         b["cx"], b["area"], yaw))
            else:
                send("find: shape at {{}}mm, beyond {{}} — keeping on "
                     "(~{{:.0f}} deg)".format(mm, MAX_MM, yaw))
        else:
            send("find: nothing warm (~{{:.0f}} deg swept)".format(yaw))

        if abs(yaw) >= SWEEP_DEG:
            send("find: swept ~{{:.0f}} deg and found nothing within {{}}mm — "
                 "stopping".format(yaw, MAX_MM))
            Legs.stop()
            center_all()
            while True:
                await asyncio.sleep(5)

        # one turning phrase, integrating gyro-z as we go
        Legs.turn(D, PACE)
        last = time.ticks_ms()
        while Legs.cycles() < PHRASE_CYCLES:
            if Legs.tipped():
                send("find: went over — stopping the sweep")
                return
            await asyncio.sleep_ms(20)
            now = time.ticks_ms()
            _gx, _gy, gz = Imu.getGyro()
            yaw += (gz - bias) * (time.ticks_diff(now, last) / 1000.0)
            last = now
        Legs.stop()
""",
    },

    "face": {
        # Rotate in place to hold the warm shape at frame centre. NO
        # translation ever — the bearing half of `keep`, on its own, so that
        # "can it find the bearing" fails separately from "can it hold a
        # range". Tangled together they are hard to tell apart.
        #
        # It will never look as smooth as `turn`, and that is deliberate: it
        # must STOP to read, because a centroid measured mid-stride is partly a
        # report of its own legs (the efference gate). Move, stop, look. What
        # it can avoid is being needlessly rough, which means two things:
        #
        #   SIZED CORRECTIONS. A fixed 1-cycle phrase turns ~18 deg and slides
        #   the centroid several px — more than the band — so a fixed phrase
        #   hunts around centre forever. This learns px-per-degree and
        #   degrees-per-cycle as it goes and asks for the phrase the error
        #   actually needs, shaving pace when the phrase would be shorter than
        #   the organ's soft-start ramp can deliver.
        #
        #   SELF-CALIBRATED HANDEDNESS. Which physical side camera column 0 is
        #   on depends on how the camera was mounted. This does not assume: it
        #   turns, checks whether the error shrank, and flips if it grew OR if
        #   the shape vanished (losing it right after a turn is itself evidence
        #   the turn went the wrong way). `dir` is only the FIRST guess.
        "args": [("band_px", int, 3), ("pace", int, 60), ("dir", int, -1)],
        "code": """
async def run():
    BAND = {band_px}
    PACE = {pace} / 100.0
    SETTLE_MS = 400
    NOISE_PX = 1.0
    MAX_FLIPS = 2
    MIN_CY = 0.5        # shorter than this and the organ's ramp eats the phrase
    MAX_CY = 2.0
    MIN_PACE = 0.35     # the organ's floor; below it the legs lack authority
    sign = 1 if {dir} > 0 else -1
    flips = 0

    # Learned in flight, so corrections can be sized rather than fixed.
    px_per_deg = None
    deg_per_cy = None

    Legs.stop()
    await asyncio.sleep_ms(600)

    bias = 0.0
    for _ in range(25):
        _gx, _gy, gz = Imu.getGyro()
        bias += gz
        await asyncio.sleep_ms(20)
    bias /= 25.0

    async def look():
        Legs.stop()
        while Legs.since_still_ms() < SETTLE_MS:
            await asyncio.sleep_ms(50)
        return Thermal.blob()

    async def turn_phrase(d, cycles, pace):
        Legs.turn(d, pace)
        last = time.ticks_ms()
        yaw = 0.0
        while Legs.cycles() < cycles:
            if Legs.tipped():
                break
            await asyncio.sleep_ms(20)
            now = time.ticks_ms()
            _gx, _gy, gz = Imu.getGyro()
            yaw += (gz - bias) * (time.ticks_diff(now, last) / 1000.0)
            last = now
        n = Legs.cycles()
        Legs.stop()
        return n, yaw

    def plan(off):
        \"\"\"cycles and pace for this much error, from what we have learned.\"\"\"
        if not px_per_deg or not deg_per_cy or px_per_deg < 0.01 or deg_per_cy < 1.0:
            return 1.0, PACE          # nothing measured yet: one honest phrase
        want_deg = (abs(off) - BAND * 0.5) / px_per_deg
        if want_deg < 0:
            want_deg = 0.0
        cy = want_deg / deg_per_cy
        if cy > MAX_CY:
            return MAX_CY, PACE
        if cy < MIN_CY:
            # Cannot shorten the phrase further without the ramp swallowing it,
            # so take the degrees out of AMPLITUDE instead.
            sc = cy / MIN_CY
            p = PACE * sc
            return MIN_CY, (MIN_PACE if p < MIN_PACE else p)
        return cy, PACE

    send("face: hold the shape within +/-{band_px}px of centre, pace {pace}%, "
         "gz bias {{:.2f}} deg/s".format(bias))

    while True:
        b = await look()
        if not b["present"]:
            send("face: nothing warm in view — holding still")
            await asyncio.sleep_ms(500)
            continue

        off = b["cx"] - Thermal.CENTRE_X
        if abs(off) <= BAND:
            send("face: CENTRED cx={{:.1f}} (off {{:+.1f}}px) area={{}} "
                 "exc={{:.1f}}".format(b["cx"], off, b["area"], b["excess_c"]))
            await asyncio.sleep_ms(400)
            continue

        cy, pace = plan(off)
        d = "ccw" if (off * sign) < 0 else "cw"
        n, yaw = await turn_phrase(d, cy, pace)
        if Legs.tipped():
            send("face: went over — stopping")
            return

        b2 = await look()
        if not b2["present"]:
            # Losing it right after turning is EVIDENCE, not merely a failure:
            # it was in view, I turned, it is gone — so I turned AWAY from it.
            # This is the only signal available when the error measurement is
            # not, and without it the behaviour dead-ends: wrong way, target
            # pushed off the frame, "nothing warm in view" forever.
            if flips < MAX_FLIPS:
                sign = -sign
                flips += 1
                back = "cw" if d == "ccw" else "ccw"
                send("face: turned {{}} ({{:+.0f}} deg) and LOST it — wrong way. "
                     "Flipping, turning {{}} to get it back".format(d, yaw, back))
                await turn_phrase(back, n if n > MIN_CY else MIN_CY, pace)
            else:
                send("face: lost the shape turning {{}} ({{:+.0f}} deg), out of "
                     "flips — it may simply have left".format(d, yaw))
                await asyncio.sleep_ms(600)
            continue

        new_off = b2["cx"] - Thermal.CENTRE_X
        removed = abs(off) - abs(new_off)

        # Learn from what just happened, whichever way it went: the magnitude of
        # centroid travel per degree is valid regardless of direction.
        if abs(yaw) > 1.0:
            if n > 0.05:
                dpc = abs(yaw) / n
                deg_per_cy = dpc if deg_per_cy is None else deg_per_cy + (dpc - deg_per_cy) * 0.4
            ppd = abs(off - new_off) / abs(yaw)
            if ppd > 0.01:
                px_per_deg = ppd if px_per_deg is None else px_per_deg + (ppd - px_per_deg) * 0.4

        send("face: {{}} {{:.2f}}cy pace {{:.2f}} ({{:+.0f}} deg), off {{:+.1f}} -> "
             "{{:+.1f}}px, removed {{:+.1f}}px | {{}} px/deg, {{}} deg/cy".format(
                 d, n, pace, yaw, off, new_off, removed,
                 "?" if px_per_deg is None else "{{:.2f}}".format(px_per_deg),
                 "?" if deg_per_cy is None else "{{:.0f}}".format(deg_per_cy)))

        if removed < -NOISE_PX:
            if flips < MAX_FLIPS:
                sign = -sign
                flips += 1
                send("face: that made it worse — camera x runs the OTHER way. "
                     "Flipping: column 0 is on the {{}} side".format(
                         "cw" if sign < 0 else "ccw"))
            else:
                send("face: still getting worse after {{}} flips. Either the "
                     "shape is moving faster than I turn, or the beam and the "
                     "camera are not looking the same way.".format(flips))
                await asyncio.sleep_ms(800)
""",
    },

    "hand": {
        # Fore-and-aft only, keyed on the nose beam: back off when the hand
        # comes closer than target, follow when it goes away, hold in between.
        # The simplest contingency demo this body can perform — and the one
        # where a human can feel the coupling immediately, because they are
        # driving one axis and the dog answers on the same axis.
        #
        # Why ToF-ONLY and not blob+ToF like `keep`: at hand distance the warm
        # shape SATURATES the frame (a hand at 30 cm already near-fills a 32x24
        # view), so its centroid stops meaning "which way is it" and a facing
        # step would just spin. The camera is still used, but only as a coarse
        # "something is filling my view" check to disambiguate a no-echo —
        # see below, it is the difference between "nothing there" and "pressed
        # against my nose", which the beam alone cannot tell apart.
        "args": [("target_mm", int, 100), ("band_mm", int, 20), ("pace", int, 60)],
        "code": """
async def run():
    TARGET = {target_mm}
    BAND = {band_mm}
    PACE = {pace} / 100.0
    SETTLE_MS = 400
    STEP_CYCLES = 1.0
    FILLED_PX = 300      # blob this big means something is right in my face

    async def look():
        Legs.stop()
        while Legs.since_still_ms() < SETTLE_MS:
            await asyncio.sleep_ms(50)
        return ToF.read_distance_mm(), Thermal.blob()

    async def phrase(mode, cycles):
        if mode == "forward":
            Legs.forward(PACE)
        else:
            Legs.back(PACE)
        while Legs.cycles() < cycles:
            if Legs.tipped():
                break
            await asyncio.sleep_ms(50)
        n = Legs.cycles()
        Legs.stop()
        return n

    Legs.stop()
    center_all()
    send("hand: hold {target_mm}mm +/-{band_mm}mm on the nose beam, pace {pace}%")
    while True:
        mm, b = await look()

        if mm is None:
            send("hand: no ToF fitted — nothing to follow")
            await asyncio.sleep(5)
            continue

        if mm <= 0:
            # No echo. Two very different worlds look identical to the beam:
            # nothing in front of me, or something too close/oblique to return.
            # The wide sense breaks the tie.
            if b["present"] and b["area"] >= FILLED_PX:
                send("hand: no echo but the view is FULL (area={{}}) — "
                     "something is on my nose, backing off".format(b["area"]))
                n = await phrase("back", STEP_CYCLES)
                send("hand: backed {{:.2f}} cycles blind".format(n))
            else:
                send("hand: no echo, view empty (area={{}}) — holding".format(
                    b["area"]))
                await asyncio.sleep_ms(500)
            continue

        err = mm - TARGET
        if abs(err) <= BAND:
            send("hand: holding at {{}}mm (err {{:+}}mm, band +/-{{}})".format(
                mm, err, BAND))
            await asyncio.sleep_ms(400)
            continue

        mode = "forward" if err > 0 else "back"
        n = await phrase(mode, STEP_CYCLES)
        after, _b2 = await look()
        closed = (mm - after) if (after is not None and after > 0) else None
        send("hand: {{}} {{:.2f}} cycles, err was {{:+}}mm, nose {{}} -> {{}} "
             "(closed {{}}) — mm/cycle pair".format(
                 mode, n, err, mm, after, "?" if closed is None else closed))
""",
    },

    "keep": {
        # Hold a distance from the warm shape: face it, close if it is beyond
        # target+band, open if it is inside target-band, hold in between.
        #
        # This is the smallest behaviour that is genuinely INTERACTIVE — the
        # human moves and the dog answers — and it is also the cleanest way to
        # measure mm/cycle, because every phrase reports the cycles commanded
        # beside the range before and after. Those pairs ARE the measurement
        # (README missing item 1).
        "args": [("target_mm", int, 350), ("band_mm", int, 60), ("pace", int, 70)],
        "code": """
async def run():
    TARGET = {target_mm}
    BAND = {band_mm}
    PACE = {pace} / 100.0
    SETTLE_MS = 400
    CENTRED_PX = 5
    STEP_CYCLES = 1.0

    async def look():
        Legs.stop()
        while Legs.since_still_ms() < SETTLE_MS:
            await asyncio.sleep_ms(50)
        return Thermal.blob(), ToF.read_distance_mm()

    async def phrase(mode, pace, cycles):
        if mode == "forward":
            Legs.forward(pace)
        elif mode == "back":
            Legs.back(pace)
        else:
            Legs.turn(mode, pace)
        while Legs.cycles() < cycles:
            if Legs.tipped():
                break
            await asyncio.sleep_ms(50)
        n = Legs.cycles()
        Legs.stop()
        return n

    Legs.stop()
    center_all()
    send("keep: target={target_mm}mm band=+/-{band_mm}mm pace={pace}%")
    while True:
        b, mm = await look()

        if not b["present"]:
            send("keep: no warm shape (tof={{}}) — holding".format(mm))
            await asyncio.sleep_ms(500)
            continue

        off = b["cx"] - Thermal.CENTRE_X
        if abs(off) > CENTRED_PX:
            d = "ccw" if off < 0 else "cw"
            n = await phrase(d, PACE * 0.6, 1.0)
            send("keep: faced {{}} (off {{:+.1f}}px) {{:.2f}} cycles".format(d, off, n))
            continue

        if mm is None or mm <= 0:
            send("keep: shape ahead (area={{}}) but NO ECHO — the beam is "
                 "missing what the camera sees".format(b["area"]))
            await asyncio.sleep_ms(400)
            continue

        err = mm - TARGET
        if abs(err) <= BAND:
            send("keep: holding at {{}}mm (err {{:+}}mm, inside +/-{{}})".format(
                mm, err, BAND))
            await asyncio.sleep_ms(500)
            continue

        mode = "forward" if err > 0 else "back"
        n = await phrase(mode, PACE, STEP_CYCLES)
        _b2, after = await look()
        moved = (mm - after) if (after is not None and after > 0) else None
        send("keep: {{}} {{:.2f}} cycles, err was {{:+}}mm, nose {{}} -> {{}} "
             "(closed {{}}) — mm/cycle pair".format(
                 mode, n, err, mm, after,
                 "?" if moved is None else moved))
""",
    },
    "turn": {
        # CONTINUOUS turn, the third member of the trot/back family: it runs
        # until something else is deployed (`stop`). Same differential stride
        # as `rotate`, but open-ended — because what this body actually has is
        # "it turns", not "it turns N degrees" (deg/cycle is unmeasured; see
        # 3_interaction/README missing item 2). Use `turnto` when you need a
        # closed loop on an angle.
        "args": [("sign", int, 1), ("amp", int, 30), ("period", int, 1000),
                 ("duty", int, 65), ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    SIGN = {sign}
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    AMP_L = SIGN * AMP          # left legs (FL, BL)
    AMP_R = -SIGN * AMP         # right legs (FR, BR) — opposite direction
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u
    center_all()
    await asyncio.sleep_ms(300)
    label = "ccw" if SIGN > 0 else "cw"
    send("turn " + label + " amp={amp} period={period} duty={duty}/100 smooth={smooth}")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        g = min(1.0, t / RAMP_CYCLES)
        # Diagonal trot pairing preserved: FL+BR on phase t, FR+BL on t+0.5
        fl = 90 + g * phase(t,       AMP_L)
        br = 90 + g * phase(t,       AMP_R)
        fr = 90 + g * phase(t + 0.5, AMP_R)
        bl = 90 + g * phase(t + 0.5, AMP_L)
        set_all(fl, fr, bl, br)
        if i % 50 == 0:
            _, _, gz = Imu.getGyro()
            send("turn " + label + " tick={{}} gz={{:.1f}}".format(i, gz))
        i += 1
        await asyncio.sleep_ms(DT_MS)
""",
    },
    "back": {
        "args": [("amp", int, 30), ("period", int, 1000), ("duty", int, 65),
                 ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    AMP = -{amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u
    center_all()
    await asyncio.sleep_ms(300)
    send("back amp={amp} period={period} duty={duty}/100 smooth={smooth}")
    i = 0
    while True:
        t = (i * DT_MS / PERIOD_MS)
        g = min(1.0, t / RAMP_CYCLES)
        a = g * phase(t, AMP)
        b = g * phase(t + 0.5, AMP)
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
        "args": [("sign", int, 1), ("seconds", int, 4), ("amp", int, 30),
                 ("period", int, 1000), ("duty", int, 65), ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    SIGN = {sign}
    SECONDS = {seconds}
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    RAMP_CYCLES = 2.0
    AMP_L = SIGN * AMP          # left legs (FL, BL) — sign of amp = direction
    AMP_R = -SIGN * AMP         # right legs (FR, BR) — opposite direction
    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u
    center_all()
    await asyncio.sleep_ms(300)
    label = "ccw" if SIGN > 0 else "cw"
    send("rotate " + label + " for {seconds}s amp={amp} period={period} smooth={smooth}")
    steps = int(SECONDS * 1000 / DT_MS)
    for i in range(steps):
        t = (i * DT_MS / PERIOD_MS)
        g = min(1.0, t / RAMP_CYCLES)
        # Diagonal trot pairing preserved: FL+BR get phase t, FR+BL get t+0.5
        fl = 90 + g * phase(t,       AMP_L)
        br = 90 + g * phase(t,       AMP_R)
        fr = 90 + g * phase(t + 0.5, AMP_R)
        bl = 90 + g * phase(t + 0.5, AMP_L)
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
        "args": [("sign", int, 1), ("target_deg", int, 180), ("amp", int, 30),
                 ("period", int, 1000), ("duty", int, 65), ("timeout_s", int, 12),
                 ("smooth", int, 0)],
        "code": """
async def run():
    import math as _math
    SIGN = {sign}
    TARGET_DEG = {target_deg}
    AMP = {amp}
    PERIOD_MS = {period}
    DUTY = {duty} / 100.0
    SMOOTH = {smooth}
    DT_MS = 20
    AMP_L = SIGN * AMP
    AMP_R = -SIGN * AMP

    def phase(t, amp):
        u = t % 1.0
        if u < DUTY:
            u = u / DUTY
        else:
            u = (u - DUTY) / (1 - DUTY)
            amp = -amp
        if SMOOTH:
            return amp * _math.cos(_math.pi * u)
        return amp - 2 * amp * u

    # One cycle, not the two the continuous gaits use: a turn is short and
    # needs leg authority early, or a small target expires inside its own
    # ramp and the timeout fires having barely moved.
    RAMP_CYCLES = 1.0
    # Approach taper: ease the amplitude down over the last TAPER_DEG so the
    # turn ARRIVES rather than slamming into its target. For a small N this is
    # the difference between stopping at 20 deg and sailing straight through
    # it — and an abrupt stop is a lurch this tall chassis does not need.
    # Never below MIN_SCALE: under that the legs lose the authority to turn
    # at all and the last few degrees never close.
    TAPER_DEG = min(20.0, TARGET_DEG * 0.5)
    MIN_SCALE = 0.4

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
    send("rotate180 bias={{:.3f}} deg/s target={target_deg} sign={sign} amp={amp} period={period} smooth={smooth}".format(gz_bias))

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
        left = TARGET_DEG - abs(yaw)
        g_in = min(1.0, t / RAMP_CYCLES)
        g_out = 1.0 if left > TAPER_DEG else max(MIN_SCALE, left / TAPER_DEG)
        g = min(g_in, g_out)
        fl = 90 + g * phase(t,       AMP_L)
        br = 90 + g * phase(t,       AMP_R)
        fr = 90 + g * phase(t + 0.5, AMP_R)
        bl = 90 + g * phase(t + 0.5, AMP_L)
        set_all(fl, fr, bl, br)

        if i % 25 == 0:
            send("rotate180 yaw={{:.1f}} left={{:.1f}} gain={{:.2f}}".format(yaw, left, g))
        i += 1
        await asyncio.sleep_ms(DT_MS)

    center_all()
    yaw_at_stop = yaw
    # Keep integrating through the settle. The body coasts after the legs
    # stop, and for a small target that coast is a LARGE fraction of the turn
    # — reporting only the yaw at the break would hide the overshoot that
    # matters most exactly when the target is small.
    for _ in range(30):
        now = time.ticks_ms()
        _, _, gz = Imu.getGyro()
        dt = time.ticks_diff(now, last_ms) / 1000.0
        last_ms = now
        yaw += (gz - gz_bias) * dt
        await asyncio.sleep_ms(DT_MS)
    send("rotate180 done yaw={{:.1f}} (at stop {{:.1f}}, coast {{:+.1f}}) target={target_deg} err={{:+.1f}}".format(
        yaw, yaw_at_stop, yaw - yaw_at_stop, abs(yaw) - TARGET_DEG))
    while True:
        await asyncio.sleep(1)
""",
    },
}
