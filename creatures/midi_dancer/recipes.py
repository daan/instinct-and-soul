"""
recipes.py — instinct templates for the midi_dancer tuner.

This body senses with the IMU and speaks through the Grove SAM2695 GM synth.
Recipes cover both surfaces: IMU logging (to check the sensor and learn which
axis is which) and synth exercises (to check the MIDI voice — pitch, velocity,
instrument, channels, drums), plus a joint motion->note recipe that tunes the
coupling between them.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
Recipes with no args are sent verbatim, so single braces are fine there.
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
    Synth.all_off()
    send("synth silenced (all notes off)")
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    send("imulog: live accel + gyro variance. hold still, then move each axis...")
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
            va = [sum((v[i] - ma[i]) ** 2 for v in ba) / n for i in range(3)]
            mg = [sum(v[i] for v in bg) / n for i in range(3)]
            send("accel mean=({:.3f},{:.3f},{:.3f}) var=({:.5f},{:.5f},{:.5f})".format(
                ma[0], ma[1], ma[2], va[0], va[1], va[2]))
            send("gyro  mean=({:.2f},{:.2f},{:.2f})".format(mg[0], mg[1], mg[2]))
            ba.clear()
            bg.clear()
        await asyncio.sleep_ms(10)
""",
    },
    "note": {
        "args": [("ch", int, 0), ("note", int, 60), ("ms", int, 500), ("vel", int, 90)],
        "code": """
async def run():
    send("note ch={ch} note={note} ms={ms} vel={vel}")
    Synth.note({ch}, {note}, {ms}, {vel})
    await asyncio.sleep_ms({ms} + 100)
    send("note done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "program": {
        "args": [("ch", int, 0), ("prog", int, 11)],
        "code": """
async def run():
    Synth.program({ch}, {prog})
    send("program ch={ch} -> GM {prog}; playing test triad")
    for n in (60, 64, 67):
        Synth.note({ch}, n, 400, 90)
        await asyncio.sleep_ms(450)
    send("program test done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "chord": {
        "args": [("root", int, 60), ("ms", int, 800), ("vel", int, 80)],
        "code": """
async def run():
    send("chord root={root} ms={ms} vel={vel} (major triad on ch 0)")
    notes = ({root}, {root} + 4, {root} + 7)
    for n in notes:
        Synth.note_on(0, n, {vel})
    await asyncio.sleep_ms({ms})
    for n in notes:
        Synth.note_off(0, n)
    send("chord done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "arp": {
        "args": [("ch", int, 0), ("prog", int, 11), ("vel", int, 90)],
        "code": """
async def run():
    Synth.program({ch}, {prog})
    send("arp: C major scale on GM {prog}, ch {ch}")
    scale = (60, 62, 64, 65, 67, 69, 71, 72)
    for n in scale:
        Synth.note({ch}, n, 220, {vel})
        await asyncio.sleep_ms(240)
    send("arp done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "drum": {
        "args": [("vel", int, 100)],
        "code": """
async def run():
    send("drum: kick/snare/hat pattern on ch 9, vel {vel}")
    pattern = ((36, 0), (42, 1), (38, 2), (42, 3)) * 2
    for note, _ in pattern:
        Synth.note(9, note, 100, {vel})
        await asyncio.sleep_ms(250)
    send("drum done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "shake": {
        "args": [("ch", int, 0), ("prog", int, 11)],
        "code": """
async def run():
    Synth.program({ch}, {prog})
    send("shake: motion -> note (GM {prog}, ch {ch}). deviation from gravity picks pitch+velocity")
    THRESHOLD = 0.12
    MOTION_MAX = 2.0
    while True:
        ax, ay, az = Imu.getAccel()
        motion = (ax * ax + ay * ay + (az - 1.0) ** 2) ** 0.5
        if motion > THRESHOLD:
            m = motion if motion < MOTION_MAX else MOTION_MAX
            span = MOTION_MAX - THRESHOLD
            frac = (m - THRESHOLD) / span
            note = 48 + int(frac * 36)
            vel = 40 + int(frac * 80)
            Synth.note({ch}, note, 180, vel)
            send("motion={{:.3f}} note={{}} vel={{}}".format(motion, note, vel))
        await asyncio.sleep_ms(120)
""",
    },
}
