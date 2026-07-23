"""
recipes.py — instinct templates for the kata_master tuner.

This body senses with the IMU and speaks through the Grove SAM2695 GM synth.
The tuner's job before any kata is played: find the VOICE on real hardware —
the pan-flute gust and the six pose tones — and find the VOLUME the battery
can afford. The Unit-Synth's amp current tracks loudness, and a brownout
mid-session is worse than a quiet drum: every sound recipe therefore samples
the battery voltage while playing and reports the sag, so "how loud can it
be" is answered with numbers, not vibes.

Volume knobs, and which recipe sweeps them:
  CC 7   per-channel volume  — `swoosh` / `tones` take it as [vol]
  SysEx  GM master volume    — `mastervol <v>` (scales everything at once)
  sweeps: `swooshvol` / `tonevol` play at 25/50/75/100/127 back to back.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
Recipes with no args are sent verbatim, so single braces are fine there.
"""

INSTINCT_IDLE = """
async def run():
    send("idle: kata_master tuner")
    while True:
        x, y, z = Imu.getAccel()
        send("accel=({:.2f},{:.2f},{:.2f}) vbat={}mV bat={}%".format(
            x, y, z, M5.Power.getBatteryVoltage(), M5.Power.getBatteryLevel()))
        await asyncio.sleep_ms(3000)
"""

# One gust of the kata swoosh: pan flute scoop + vibrato over a seashore
# breath, ~400 ms, hard expression cut — the v5 sim seed's shape, verbatim.
_GUST = """
    Synth.control_change(FL, 1, 0)
    Synth.control_change(FL, 11, 127)
    Synth.control_change(BD, 11, 55)
    Synth.pitch_bend(FL, -2200)
    Synth.note_on(FL, 69, 105)
    Synth.note_on(BD, 55, 70)
    for j in range(1, 13):
        Synth.pitch_bend(FL, -2200 + j * 280)
        if j == 6:
            Synth.control_change(FL, 1, 55)
        await asyncio.sleep_ms(30)
        vb = M5.Power.getBatteryVoltage()
        if vb < vmin:
            vmin = vb
    Synth.control_change(FL, 11, 0)
    Synth.control_change(BD, 11, 0)
    Synth.note_off(FL, 69)
    Synth.note_off(BD, 55)
    Synth.pitch_bend(FL, 0)
"""

_SETUP_GUST = """
    FL, BD = 0, 1
    Synth.all_off()
    Synth.program(FL, 75)                # pan flute
    Synth.program(BD, 122)               # seashore breath under it
    Synth.control_change(FL, 101, 0)     # RPN 0: bend range...
    Synth.control_change(FL, 100, 0)
    Synth.control_change(FL, 6, 12)      # ...12 semitones for the scoop
"""

# Indented body reused inside a for-loop (one extra level).
_GUST_IN_LOOP = _GUST.replace("\n    ", "\n        ")

RECIPES = {
    "synthcheck": {
        "args": [],
        "code": """
async def run():
    # No feedback line exists from the SAM2695, so this probes actively:
    # power the Grove 5V rail, then play three loud notes through each
    # candidate TX pin — the config that SOUNDS is the right wiring.
    # StickS3 Grove data pins are G9/G10 (see test/STICKS3); G2/G1 was the
    # old driver default and is probably wrong.
    try:
        M5.Power.setExtOutput(True)
        send("grove 5V rail: on")
    except Exception as e:
        send("grove 5V rail: {} (fine on USB power)".format(e))
    from machine import UART, Pin
    send("synthcheck: 3 notes per pin config — note which config SOUNDS")
    for tx, rx in ((9, 10), (10, 9), (2, 1), (1, 2)):
        try:
            u = UART(1, baudrate=31250, tx=Pin(tx), rx=Pin(rx))
        except Exception as e:
            send("tx=G{} rx=G{}: UART init failed: {}".format(tx, rx, e))
            continue
        send("tx=G{}: three notes NOW".format(tx))
        u.write(bytearray([0xB0, 7, 127]))        # ch0 volume max
        u.write(bytearray([0xC0, 11]))            # vibraphone
        for n in (60, 67, 72):
            u.write(bytearray([0x90, n, 120]))
            await asyncio.sleep_ms(350)
            u.write(bytearray([0x80, n, 0]))
        try:
            u.deinit()
        except Exception:
            pass
        await asyncio.sleep_ms(900)
    send("synthcheck done — set SYNTH_TX_PIN in lib/synth.py to the G-pin "
         "that sounded, reflash, and rerun a sound command")
    while True:
        await asyncio.sleep(1)
""",
    },
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
    "vbat": {
        "args": [],
        "code": """
async def run():
    send("vbat: live battery while you play/charge")
    while True:
        send("vbat={}mV bat={}% charging={}".format(
            M5.Power.getBatteryVoltage(), M5.Power.getBatteryLevel(),
            M5.Power.isCharging()))
        await asyncio.sleep_ms(2000)
""",
    },
    "swoosh": {
        "args": [("vol", int, 90), ("reps", int, 3)],
        "code": """
async def run():
""" + _SETUP_GUST.replace("{", "{{").replace("}", "}}") + """
    Synth.control_change(FL, 7, {vol})
    Synth.control_change(BD, 7, {vol})
    send("swoosh: CC7 vol={vol}, {reps} gusts")
    for i in range({reps}):
        v0 = M5.Power.getBatteryVoltage()
        vmin = v0
""" + _GUST_IN_LOOP.replace("{", "{{").replace("}", "}}") + """
        send("gust {{}}: vbat {{}} -> {{}} mV (sag {{}})".format(
            i + 1, v0, vmin, v0 - vmin))
        await asyncio.sleep_ms(800)
    send("swoosh done")
    while True:
        await asyncio.sleep(1)
""",
    },
    "tones": {
        "args": [("vol", int, 90)],
        "code": """
async def run():
    Synth.all_off()
    CH = 2
    Synth.program(CH, 11)                # vibraphone: the pose tones
    Synth.control_change(CH, 7, {vol})
    TONES = [[60, "X+ fingers-dn"], [62, "Y+ blade"], [64, "Z+ palm-dn"],
             [67, "Z- palm-up"], [69, "Y- blade"], [72, "X- fingers-up"]]
    send("tones: CC7 vol={vol}, six faces low to high")
    v0 = M5.Power.getBatteryVoltage()
    vmin = v0
    for note, label in TONES:
        send("  " + label)
        Synth.note(CH, note, 500, 95)
        for _ in range(6):
            await asyncio.sleep_ms(100)
            vb = M5.Power.getBatteryVoltage()
            if vb < vmin:
                vmin = vb
    send("tones done: vbat {{}} -> {{}} mV (sag {{}})".format(v0, vmin, v0 - vmin))
    while True:
        await asyncio.sleep(1)
""",
    },
    "swooshvol": {
        "args": [],
        "code": """
async def run():
""" + _SETUP_GUST + """
    send("swooshvol: one gust at CC7 25/50/75/100/127, watch the sag")
    for vol in (25, 50, 75, 100, 127):
        Synth.control_change(FL, 7, vol)
        Synth.control_change(BD, 7, vol)
        v0 = M5.Power.getBatteryVoltage()
        vmin = v0
""" + _GUST_IN_LOOP + """
        send("vol {}: vbat {} -> {} mV (sag {})".format(vol, v0, vmin, v0 - vmin))
        await asyncio.sleep_ms(900)
    send("swooshvol done — pick the loudest vol whose sag is boring")
    while True:
        await asyncio.sleep(1)
""",
    },
    "tonevol": {
        "args": [],
        "code": """
async def run():
    Synth.all_off()
    CH = 2
    Synth.program(CH, 11)
    NOTES = (60, 62, 64, 67, 69, 72)
    send("tonevol: six tones at CC7 25/50/75/100/127, watch the sag")
    for vol in (25, 50, 75, 100, 127):
        Synth.control_change(CH, 7, vol)
        v0 = M5.Power.getBatteryVoltage()
        vmin = v0
        for note in NOTES:
            Synth.note(CH, note, 350, 95)
            for _ in range(4):
                await asyncio.sleep_ms(100)
                vb = M5.Power.getBatteryVoltage()
                if vb < vmin:
                    vmin = vb
        send("vol {}: vbat {} -> {} mV (sag {})".format(vol, v0, vmin, v0 - vmin))
        await asyncio.sleep_ms(600)
    send("tonevol done — pick the loudest vol whose sag is boring")
    while True:
        await asyncio.sleep(1)
""",
    },
    "mastervol": {
        "args": [("v", int, 100)],
        "code": """
async def run():
    Synth.master_volume({v})
    send("master volume -> {v} (SysEx, scales all channels); test tone follows")
    Synth.program(2, 11)
    Synth.note(2, 69, 600, 95)
    while True:
        await asyncio.sleep(1)
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
        "args": [("ch", int, 0), ("prog", int, 75)],
        "code": """
async def run():
    Synth.program({ch}, {prog})
    send("ch {ch} -> GM {prog}; test note")
    Synth.note({ch}, 69, 600, 95)
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    send("imulog: live accel + gyro. hold still, then move each axis...")
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
