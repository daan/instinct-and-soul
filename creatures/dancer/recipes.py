"""
recipes.py — instinct templates for the CORES3 tuner.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
"""

INSTINCT_IDLE = """
async def run():
    send("idle")
    while True:
        ax, ay, az = Imu.getAccel()
        light = Als.getLightSensorData()
        prox = Als.getProximitySensorData()
        send("accel x={:.4f} y={:.4f} z={:.4f} light={} prox={}".format(
            ax, ay, az, light, prox))
        await asyncio.sleep_ms(2000)
"""

RECIPES = {
    "off": {
        "args": [],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)
    Speaker.stop()
    send("motor off, speaker stopped")
    while True:
        await asyncio.sleep(1)
""",
    },
    "constant": {
        "args": [("duty", int, 0)],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty={duty})
    send("motor duty={duty}")
    while True:
        await asyncio.sleep(1)
""",
    },
    "sweep": {
        "args": [],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)
    send("sweep: duty 0 -> 1023, step 25, 3s each")
    for d in range(0, 1024, 25):
        motor.duty(d)
        send("sweep duty={}".format(d))
        await asyncio.sleep_ms(3000)
    motor.duty(0)
    send("sweep done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "heartbeat": {
        "args": [("duty", int, 500)],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)
    duty = {duty}
    send("heartbeat duty={{}}".format(duty))
    while True:
        # thump
        motor.duty(duty)
        await asyncio.sleep_ms(100)
        motor.duty(0)
        await asyncio.sleep_ms(120)
        # thump
        motor.duty(duty)
        await asyncio.sleep_ms(100)
        motor.duty(0)
        # pause
        await asyncio.sleep_ms(700)
""",
    },
    "breathe": {
        "args": [("duty", int, 500)],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)
    peak = {duty}
    send("breathe peak={{}}".format(peak))
    step = 0
    while True:
        d = int(peak * (math.sin(step * 0.033) ** 2))
        motor.duty(d)
        step += 1
        if step > 190:
            step = 0
        await asyncio.sleep_ms(16)
""",
    },
    "pulse": {
        "args": [("duty", int, 500), ("ms", int, 300)],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)
    duty = {duty}
    ms = {ms}
    send("pulse duty={{}} on/off={{}}ms".format(duty, ms))
    while True:
        motor.duty(duty)
        await asyncio.sleep_ms(ms)
        motor.duty(0)
        await asyncio.sleep_ms(ms)
""",
    },
    "tone": {
        "args": [("freq", int, 440), ("ms", int, 300), ("vol", int, 64)],
        "code": """
async def run():
    Speaker.begin()
    Speaker.setVolume({vol})
    send("tone {freq}Hz {ms}ms vol={vol}/255")
    Speaker.tone({freq}, {ms})
    await asyncio.sleep_ms({ms} + 50)
    send("tone done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "chirp": {
        "args": [("vol", int, 64)],
        "code": """
async def run():
    Speaker.begin()
    Speaker.setVolume({vol})
    send("chirp 200..2000Hz vol={vol}/255")
    for freq in range(200, 2100, 100):
        Speaker.tone(freq, 80)
        await asyncio.sleep_ms(110)
    Speaker.stop()
    send("chirp done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    PWM(Pin(1), freq=5000, duty=0)
    send("imulog: live IMU + ALS, motor off. pick it up, hold, shake...")
    WINDOW = 30
    bx, by, bz = [], [], []
    while True:
        ax, ay, az = Imu.getAccel()
        bx.append(ax)
        by.append(ay)
        bz.append(az)
        if len(bx) > WINDOW:
            bx.pop(0)
            by.pop(0)
            bz.pop(0)
        if len(bx) == WINDOW:
            mx = sum(bx) / WINDOW
            my = sum(by) / WINDOW
            mz = sum(bz) / WINDOW
            vx = sum((v - mx) ** 2 for v in bx) / WINDOW
            vy = sum((v - my) ** 2 for v in by) / WINDOW
            vz = sum((v - mz) ** 2 for v in bz) / WINDOW
            light = Als.getLightSensorData()
            prox = Als.getProximitySensorData()
            send("var={:.6f} light={} prox={}".format(vx + vy + vz, light, prox))
            bx.clear()
            by.clear()
            bz.clear()
        await asyncio.sleep_ms(10)
""",
    },
    "imutune": {
        "args": [],
        "code": """
async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)

    async def measure_variance(n=60):
        bx, by, bz = [], [], []
        for _ in range(n):
            x, y, z = Imu.getAccel()
            bx.append(x)
            by.append(y)
            bz.append(z)
            await asyncio.sleep_ms(10)
        mx = sum(bx) / n
        my = sum(by) / n
        mz = sum(bz) / n
        vx = sum((v - mx) ** 2 for v in bx) / n
        vy = sum((v - my) ** 2 for v in by) / n
        vz = sum((v - mz) ** 2 for v in bz) / n
        return vx, vy, vz

    send("imutune: DO NOT TOUCH during this test")
    await asyncio.sleep_ms(2000)

    vx, vy, vz = await measure_variance()
    send("duty=0 (baseline) total={:.8f}".format(vx + vy + vz))

    for duty in [50, 100, 150, 200, 300, 400, 500, 600, 700, 800, 900, 1023]:
        motor.duty(duty)
        await asyncio.sleep_ms(500)
        vx, vy, vz = await measure_variance()
        send("duty={} total={:.8f}".format(duty, vx + vy + vz))
        motor.duty(0)
        await asyncio.sleep_ms(1000)

    send("imutune done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "alslog": {
        "args": [],
        "code": """
async def run():
    send("alslog: light + proximity, 5 Hz")
    while True:
        light = Als.getLightSensorData()
        prox = Als.getProximitySensorData()
        send("light={} prox={}".format(light, prox))
        await asyncio.sleep_ms(200)
""",
    },
    "shake": {
        "args": [("vol", int, 32)],
        "code": """
async def run():
    Speaker.begin()
    Speaker.setVolume({vol})
    send("shake: motion -> tone (vol {vol}/255)")
    THRESHOLD = 0.15
    MOTION_MAX = 2.0
    FREQ_MIN = 200
    FREQ_MAX = 1500
    while True:
        ax, ay, az = Imu.getAccel()
        motion = (ax * ax + ay * ay + (az - 1.0) ** 2) ** 0.5
        if motion > THRESHOLD:
            m = motion if motion < MOTION_MAX else MOTION_MAX
            span = MOTION_MAX - THRESHOLD
            freq = FREQ_MIN + int((m - THRESHOLD) / span * (FREQ_MAX - FREQ_MIN))
            Speaker.tone(freq, 80)
            send("motion={{:.3f}} freq={{}}".format(motion, freq))
        await asyncio.sleep_ms(50)
""",
    },
}
