"""
recipes.py — instinct templates for the memory-example tuner.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates with no args are sent verbatim. Templates with args use Python
str.format substitution: `{name}` is filled at dispatch time, `{{...}}`
survives as `{...}` for the runtime's own .format() calls.
"""

INSTINCT_IDLE = """
async def run():
    while True:
        ax, ay, az = Imu.getAccel()
        dev = ((ax) ** 2 + (ay) ** 2 + (az - 1) ** 2) ** 0.5
        Mem.push("dev", dev, maxlen=300)
        await asyncio.sleep_ms(33)
"""

RECIPES = {
    "idle": {
        "args": [],
        "code": INSTINCT_IDLE,
    },
    "summary": {
        "args": [],
        "code": """
async def run():
    while True:
        await asyncio.sleep(2)
        for slot in Mem.slots():
            entries = Mem.recent(slot)
            send("slot " + slot + ": " + str(len(entries)) + " entries, latest=" + str(Mem.latest(slot)))
""",
    },
    "clear": {
        "args": [],
        "code": """
async def run():
    Mem.clear()
    send("Mem cleared")
    while True:
        await asyncio.sleep(10)
""",
    },
}
