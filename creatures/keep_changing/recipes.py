"""
recipes.py — instinct templates for the sticks3 tuner.

This body has no vibration motor — only sound (speaker) and IMU. Recipes
are limited to those two surfaces.

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
        x, y, z = Imu.getAccel()
        mag = (x*x + y*y + z*z) ** 0.5
        send("accel x={:.4f} y={:.4f} z={:.4f} mag={:.4f}".format(x, y, z, mag))
        await asyncio.sleep_ms(2000)
"""

RECIPES = {
    "off": {
        "args": [],
        "code": """
async def run():
    Speaker.stop()
    Speaker.end()
    send("speaker stopped")
    while True:
        await asyncio.sleep(1)
""",
    },
    "tone": {
        "args": [("freq", int, 440), ("ms", int, 200), ("vol", int, 64)],
        "code": """
async def run():
    Speaker.begin()
    Speaker.setVolume({vol})
    send("tone freq={freq} ms={ms} vol={vol}/255")
    ms = {ms}
    loops = ms // 50
    if loops < 1:
        loops = 1
    for _ in range(loops):
        Speaker.tone({freq}, 80)
        M5.update()
        await asyncio.sleep_ms(50)
    Speaker.end()
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
        send("chirp freq={{}}".format(freq))
        for _ in range(3):
            Speaker.tone(freq, 80)
            M5.update()
            await asyncio.sleep_ms(50)
    Speaker.end()
    send("chirp done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    send("imulog: live accel variance. pick it up, hold, shake...")
    WINDOW = 30
    bx, by, bz = [], [], []
    while True:
        x, y, z = Imu.getAccel()
        bx.append(x)
        by.append(y)
        bz.append(z)
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
            total = vx + vy + vz
            send("var_x={:.6f} var_y={:.6f} var_z={:.6f} total={:.6f}".format(vx, vy, vz, total))
            bx.clear()
            by.clear()
            bz.clear()
        await asyncio.sleep_ms(10)
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
            # StickS3 needs a tight loop; one short burst per frame keeps it alive
            Speaker.tone(freq, 80)
            M5.update()
            send("motion={{:.3f}} freq={{}}".format(motion, freq))
        await asyncio.sleep_ms(50)
""",
    },
}
