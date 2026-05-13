"""
recipes.py — instinct templates for the BLE example creature tuner.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
"""

INSTINCT_IDLE = """
async def run():
    while True:
        bpm = Hr.get()
        if bpm is None:
            send("hr: not connected")
        else:
            send("hr: bpm={{}}".format(bpm))
        await asyncio.sleep(2)
"""

RECIPES = {
    "idle": {
        "args": [],
        "code": INSTINCT_IDLE,
    },
}
