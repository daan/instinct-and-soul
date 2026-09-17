"""
recipes.py — instinct templates for the desk tuner.

The body is a CoreS3 on the desk surface with an ultrasonic unit on Port A
and a Linak desk over BLE (or the virtual one). The tuner's jobs before the
first real day: see that the RANGE reads what a person at this desk reads
(and what the empty chair reads), find the ACTIVITY level typing produces
on this frame, and drive the DESK by hand to confirm the link and the body
rule.

Each entry maps a recipe name to a spec:
  "args" — list of (arg_name, type, default) tuples used to fill {placeholders}
  "code" — async def run() coroutine string to deploy on the board

Templates use Python str.format substitution: `{name}` is filled at dispatch
time, `{{...}}` survives as `{...}` for the runtime's own .format() calls.
Recipes with no args are sent verbatim, so single braces are fine there.
"""

INSTINCT_IDLE = """
async def run():
    send("idle: desk tuner — desk {} {} at {} | range {}".format(
        Desk.kind(), "linked" if Desk.connected() else "UNLINKED",
        Desk.height_mm(), Range.mm()))
    n = 0
    while True:
        n += 1
        if n % 100 == 0:
            h = Desk.height_mm()
            send("desk {} | range {} | {}".format(
                "?" if h is None else "{:.0f}mm".format(h), Range.mm(),
                "moving" if Desk.moving() else "still"))
        await asyncio.sleep_ms(50)
"""

RECIPES = {
    "scan": {
        "args": [],
        "code": """
async def run():
    # Who is on Grove Port A? The ultrasonic unit answers at 0x57. The
    # runtime tried both pin orders at boot; this shows the bus it kept.
    from machine import I2C, Pin
    for scl, sda in ((1, 2), (2, 1)):
        try:
            bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=100000)
            found = bus.scan()
            send("port a scl={} sda={}: {}".format(
                scl, sda, [hex(a) for a in found] or "nothing"))
        except Exception as e:
            send("port a scl={} sda={}: {}".format(scl, sda, e))
    send("runtime says range {}".format("ok" if Range.ok() else "ABSENT"))
    while True:
        await asyncio.sleep(1)
""",
    },
    "range": {
        "args": [("present_mm", float, 850.0), ("absent_mm", float, 1100.0)],
        "code": """
async def run():
    # THE PRESENCE VIEW — the beam, raw, plus the seed's gate at
    # present<{present_mm} / absent>{absent_mm} so you see where the
    # edges fall. Sit, lean back, reach for a drawer, stand up, walk away,
    # come back. Watch that:
    #   (a) sitting and standing both read a few hundred mm
    #   (b) the empty chair reads over a metre, or 0 (no echo)
    #   (c) a lean-back stays inside the dead band, not past it
    # The gate uses the seed's holds (5 s arrive, 90 s leave), so an edge
    # arrives late on purpose.
    gate = Calc.Gate(-{absent_mm}, -{present_mm}, rise_hold_s=5.0, fall_hold_s=90.0)
    send("range view: present<{present_mm} absent>{absent_mm}")
    n = 0
    while True:
        now = time.ticks_ms() / 1000.0
        mm = Range.mm()
        if mm is None:
            send("no ultrasonic unit — check `scan`")
            await asyncio.sleep(5)
            continue
        edge = gate.update(-mm if mm > 0 else -{absent_mm} - 1, now)
        if edge is not None:
            send("=== {{}} after {{:.0f}}s ===".format(
                "ARRIVED" if edge[0] == "rise" else "LEFT", edge[2]))
        n += 1
        if n % 5 == 0:
            send("range {{:>5}} | {{}} | age {{}}ms".format(
                "echo-" if mm == 0 else "{{:.0f}}".format(mm),
                "present" if gate.state else "absent", Range.age_ms()))
        await asyncio.sleep_ms(200)
""",
    },
    "activity": {
        "args": [],
        "code": """
async def run():
    # THE ACTIVITY VIEW — exactly the seed's sense: std of |accel| over
    # ~1 s at 20 Hz, in milli-g, smoothed over 10 s. Hands off, then type,
    # then mouse, then set a mug down. ACT_MG should sit between "hands
    # off" and "typing" with room on both sides. Prints the 10 s smooth
    # AND the raw 1 s figure, so a single knock is visible too.
    win = Calc.Running(20)
    ema = Calc.Ema(10.0)
    peak = 0.0
    n = 0
    send("activity view: hands off first, then type")
    while True:
        now = time.ticks_ms() / 1000.0
        a = Imu.getAccel()
        win.push(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]))
        raw = win.std() * 1000.0
        act = ema.update(raw, now)
        if raw > peak:
            peak = raw
        n += 1
        if n % 20 == 0:
            send("act {:5.2f}mg (10s) | raw {:5.2f}mg (1s) | peak {:5.2f}".format(
                act, raw, peak))
            peak = 0.0
        await asyncio.sleep_ms(50)
""",
    },
    "desk": {
        "args": [],
        "code": """
async def run():
    # THE DESK VIEW — height, speed, link, whose move. Press the paddle:
    # the height should change with commanded=False. `goto` from the
    # tuner: commanded=True until it arrives, then result() reports.
    send("desk view: {} — press the paddle, or `goto <cm>`".format(Desk.kind()))
    last = None
    while True:
        h = Desk.height_mm()
        r = Desk.result()
        if r is not None:
            send("=== move {} : {} -> {} in {:.1f}s ===".format(
                r[0], r[1], "?" if r[2] is None else "{:.0f}".format(r[2]), r[3]))
        line = "{} | {:+.0f}mm/s | {} | {}{}".format(
            "?" if h is None else "{:.0f}mm".format(h), Desk.speed_mms(),
            "linked" if Desk.connected() else "UNLINKED",
            "MINE -> {:.0f}".format(Desk.target_mm()) if Desk.commanded()
            else ("THEIRS" if Desk.moving() else "still"),
            "" if Range.mm() is None else " | range {}".format(Range.mm()))
        if line != last:
            send(line)
            last = line
        await asyncio.sleep_ms(250)
""",
    },
    "goto": {
        "args": [("mm", float, 720.0)],
        "code": """
async def run():
    # Drive the desk to {mm} mm, then watch. The body rule applies: with
    # someone within a metre the runtime refuses and journals why.
    ok = Desk.move_to({mm})
    send("goto {mm}: {{}}".format("accepted" if ok else "REFUSED"))
    while True:
        r = Desk.result()
        if r is not None:
            send("=== move {{}} : {{:.0f}} -> {{:.0f}} in {{:.1f}}s ===".format(
                r[0], r[1] or 0, r[2] or 0, r[3]))
        h = Desk.height_mm()
        send("{{}} | {{}}".format(
            "?" if h is None else "{{:.0f}}mm".format(h),
            "moving" if Desk.moving() else "still"))
        await asyncio.sleep_ms(500)
""",
    },
    "stop": {
        "args": [],
        "code": """
async def run():
    Desk.stop()
    send("stop sent")
    while True:
        await asyncio.sleep(1)
""",
    },
    "touch": {
        "args": [],
        "code": """
async def run():
    # The explicit channel, end to end: every tap should land exactly once.
    send("touch test: tap the screen, slowly then fast")
    n = 0
    while True:
        if Touch.pressed():
            n += 1
            send("TAP #{} — last_s now {:.2f}".format(n, Touch.last_s()))
        await asyncio.sleep_ms(20)
""",
    },
    "tone": {
        "args": [("vol", int, 64)],
        "code": """
async def run():
    # A three-note figure at volume {vol}, every 5 s — the CoreS3 idiom:
    # one tone() call plays its whole duration by itself.
    send("tone at vol {vol} every 5s; `off` to stop")
    while True:
        Speaker.begin()
        Speaker.setVolume({vol})
        for f in (880, 1100, 1320):
            Speaker.tone(f, 120)
            await asyncio.sleep_ms(150)
        await asyncio.sleep_ms(5000)
""",
    },
    "blescan": {
        "args": [("secs", int, 10)],
        "code": """
async def run():
    # Find the desk's address: every advertiser seen in {secs} s, name and
    # MAC. A Linak DPG usually advertises as "Desk 1234" or similar. Put
    # the MAC into DESK_MAC in main.py and reflash.
    import aioble
    send("ble scan for {secs}s...")
    seen = {{}}
    async with aioble.scan(duration_ms={secs} * 1000, interval_us=30000,
                           window_us=30000, active=True) as scanner:
        async for r in scanner:
            mac = ":".join("{{:02X}}".format(b) for b in bytes(r.device.addr))
            name = r.name() or ""
            if mac not in seen or (name and not seen[mac]):
                seen[mac] = name
                send("  {{}}  {{}}  rssi {{}}".format(mac, name or "(no name)", r.rssi))
    send("scan done: {{}} devices".format(len(seen)))
    while True:
        await asyncio.sleep(1)
""",
    },
    "imulog": {
        "args": [],
        "code": """
async def run():
    send("imulog: raw accel means over 30 samples")
    WINDOW = 30
    ba = []
    while True:
        ba.append(Imu.getAccel())
        if len(ba) == WINDOW:
            ma = [sum(v[i] for v in ba) / WINDOW for i in range(3)]
            send("accel=({:.3f},{:.3f},{:.3f})".format(ma[0], ma[1], ma[2]))
            ba.clear()
        await asyncio.sleep_ms(10)
""",
    },
    "off": {
        "args": [],
        "code": """
async def run():
    try:
        Speaker.stop()
        Speaker.end()
    except Exception:
        pass
    Desk.stop()
    send("silenced, desk stopped")
    while True:
        await asyncio.sleep(1)
""",
    },
}
