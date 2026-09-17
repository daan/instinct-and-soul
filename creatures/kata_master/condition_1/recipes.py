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
    # THE RECORDER — a raw IMU trace on flash, for tuning offline.
    #
    # Nothing crosses the radio during a take: the WebSocket brings the
    # recipe in and carries the summary out, and everything between is the
    # board alone with its own clock. The trace comes off over USB
    # afterwards (pull_recordings.py), which is also what makes it a
    # RECORD — the same bytes replay through KataSense as many times as a
    # threshold sweep needs, where a live session can never be re-performed.
    #
    # RAM-first, deliberately: the whole take is packed into one
    # preallocated buffer and written to flash once, at the end. A flash
    # write mid-take stalls tens of milliseconds, and a stall during a
    # strike is exactly the sample you cannot afford to lose. The price is
    # that RAM bounds the take — the recipe measures free memory, reports
    # the seconds it can hold, and caps rather than truncating silently.
    #
    # Every take is bracketed by a SYNC MARK — a wood-block click and a
    # white screen flash issued at the same instant, whose tick IS the
    # file's t=0 — and closed by two of them. Line the camera up on either:
    # the click if the audio is clean, the flash if the room is loud. The
    # end mark carries the drift between the board's clock and the camera's.
    "record": {
        "args": [("label", str, "take"), ("secs", float, 30.0),
                 ("hz", int, 200)],
        "code": """
async def run():
    import gc
    import os

    LABEL = "{label}"
    SECS = {secs}
    HZ = {hz}
    PERIOD_US = int(1000000.0 / HZ)
    REC = 28              # per sample: t_us uint32 + ax..gz float32
    HDR = 64
    HEADROOM = 40000      # bytes of RAM left for the runtime to breathe
    CLICK_CH = 9          # GM percussion: sharp attack, program-independent
    TICK, SYNC = 77, 76   # low wood block (count-in) / high (the mark)

    def click(note, ms=70, vel=127):
        try:
            Synth.note(CLICK_CH, note, ms, vel)
        except Exception:
            pass

    def screen(white, msg=None):
        try:
            M5.Display.fillScreen(0xFFFFFF if white else 0x000000)
            if msg:
                M5.Display.drawString(msg, 5, 10)
        except Exception:
            pass

    def free_flash(d):
        try:
            st = os.statvfs(d)
            return st[0] * st[3]
        except Exception:
            return -1

    def next_index(d):
        n = 0
        try:
            for f in os.listdir(d):
                if f[:4] == "rec_" and f[-4:] == ".bin":
                    try:
                        v = int(f[4:7])
                        if v > n:
                            n = v
                    except ValueError:
                        pass
        except Exception:
            pass
        return n + 1

    # where the traces land: /flash if this build has it, else the root
    DIR = "/"
    try:
        os.listdir("/flash")
        DIR = "/flash"
    except Exception:
        pass

    # THE IMU MUST BE ALIVE BEFORE ANYTHING IS ARMED. Take aug20_1
    # (2026-08-20) was 2000 samples of perfect 5 ms timestamps and six flat
    # zero channels: the sampler read a dead Imu without noticing, and a
    # filmed kata session was spent recording nothing. Zeros are not an
    # exception, so they must be CHECKED — and the check is free: gravity
    # never sleeps, so |a| ~ 0 g on a resting board is not a reading, it is
    # a dead instrument.
    alive = False
    for _ in range(10):
        a = Imu.getAccel()
        if abs(a[0]) + abs(a[1]) + abs(a[2]) > 0.5:
            alive = True
            break
        await asyncio.sleep_ms(50)
    if not alive:
        send("record: REFUSING to arm — the IMU reads all zeros (a resting "
             "board must see ~1 g somewhere). Reboot the stick and rerun.")
        screen(False, "IMU DEAD")
        return

    Synth.all_off()
    gc.collect()
    free = gc.mem_free()
    cap = int((free - HEADROOM) / REC)
    if cap < HZ:
        send("record: {{}} B free — no room for even a second".format(free))
        screen(False, "NO RAM")
        return
    want = int(SECS * HZ)
    if want > cap:
        send("record: RAM holds {{:.1f}}s at {hz} Hz, not {secs}s — capping"
             .format(cap / float(HZ)))
        want = cap
    buf = bytearray(want * REC)

    send("record '{label}': ready for {{:.1f}}s takes at {hz} Hz "
         "({{}} samples, {{}} B RAM, {{}} B free on {{}}). BtnA starts a "
         "take: 3 count-in ticks, then CLICK+FLASH is t=0.".format(
             want / float(HZ), want, want * REC, free_flash(DIR), DIR))
    screen(False, "ARM: BtnA")

    while True:
        M5.update()
        if not M5.BtnA.wasPressed():
            await asyncio.sleep_ms(20)
            continue

        # ── count-in: three low ticks, one per second ────────────────────
        for i in range(3):
            click(TICK, 50, 100)
            screen(False, "{{}}...".format(3 - i))
            await asyncio.sleep_ms(1000)

        # ── THE SYNC MARK: click and flash together, and this tick is t=0 ─
        screen(True)
        click(SYNC, 90, 127)
        t0 = time.ticks_us()

        n = 0
        prev = t0
        next_us = t0
        max_gap = 0
        gaps = 0
        dead = 0     # samples where every channel read exactly zero
        lit = True
        while n < want:
            now = time.ticks_us()
            if time.ticks_diff(now, next_us) >= 0:
                a = Imu.getAccel()
                g = Imu.getGyro()
                if a[0] == 0.0 and a[1] == 0.0 and a[2] == 0.0 and \
                        g[0] == 0.0 and g[1] == 0.0 and g[2] == 0.0:
                    dead += 1
                if n:
                    dt = time.ticks_diff(now, prev)
                    if dt > max_gap:
                        max_gap = dt
                    if dt > PERIOD_US + PERIOD_US // 2:
                        gaps += 1
                prev = now
                struct.pack_into("<Iffffff", buf, n * REC,
                                 time.ticks_diff(now, t0),
                                 a[0], a[1], a[2], g[0], g[1], g[2])
                n += 1
                next_us = time.ticks_add(next_us, PERIOD_US)
                # fallen far behind (a long stall): resync rather than
                # firing a catch-up burst of samples at the wrong times
                if time.ticks_diff(now, next_us) > PERIOD_US * 4:
                    next_us = time.ticks_add(now, PERIOD_US)
            elif lit and time.ticks_diff(now, t0) > 120000:
                screen(False, "REC")   # the flash is over; the screen is
                lit = False            # then left alone — no jitter
            await asyncio.sleep_ms(0)

        # ── the end mark: two clicks, so the take is bracketed ───────────
        end_us = time.ticks_diff(time.ticks_us(), t0)
        screen(True)
        click(SYNC, 90, 127)
        await asyncio.sleep_ms(160)
        click(SYNC, 90, 127)
        await asyncio.sleep_ms(160)
        screen(False, "saving")

        idx = next_index(DIR)
        path = "{{}}/rec_{{:03d}}.bin".format("" if DIR == "/" else DIR, idx)
        hdr = bytearray(HDR)
        hdr[0:8] = b"KATAREC1"
        struct.pack_into("<HIIIIII", hdr, 8, HZ, n, end_us,
                         time.ticks_ms(), max_gap, gaps, PERIOD_US)
        lb = LABEL.encode()[:16]
        hdr[48:48 + len(lb)] = lb
        try:
            f = open(path, "wb")
            f.write(hdr)
            f.write(memoryview(buf)[:n * REC])
            f.close()
        except Exception as e:
            send("record: SAVE FAILED {{}}: {{}}".format(path, e))
            screen(False, "SAVE FAIL")
            await asyncio.sleep_ms(2000)
            screen(False, "ARM: BtnA")
            continue

        send("record: {{}} '{label}' {{}} samples {{:.1f}}s | worst gap "
             "{{:.1f}} ms, {{}} late (nominal {{:.1f}}) | flash free {{}} B"
             .format(path, n, end_us / 1000000.0, max_gap / 1000.0, gaps,
                     PERIOD_US / 1000.0, free_flash(DIR)))
        if dead == n:
            send("record: WARNING — every sample read all-zero. The take is "
                 "saved but it is a dead instrument's diary. Reboot and redo.")
            screen(False, "ALL ZERO!")
            await asyncio.sleep_ms(2500)
        elif dead > n // 10:
            send("record: WARNING — {{}} of {{}} samples read all-zero"
                 .format(dead, n))
        screen(False, "SAVED {{:03d}}".format(idx))
        await asyncio.sleep_ms(1500)
        screen(False, "ARM: BtnA")
        M5.update()
        M5.BtnA.wasPressed()   # swallow a bounce so the next take is yours
""",
    },
    # The rest-tone gate, with EVERY judgment number on the tuner line.
    # KataSense already holds the mechanism (lib/kata_sense.py, replayed by
    # test_kata_parity.py); it deliberately holds no numbers of its own, so
    # the thing left to find on a real hand is exactly the constructor —
    # which is what this recipe hands to the tuner. `feel quiet=0.15` is one
    # keystroke and one deploy from your hand, and the window report carries
    # the speed01 distribution the thresholds are set AGAINST, so the knobs
    # get moved on evidence rather than on feel-of-a-feel.
    "feel": {
        "args": [("quiet", float, 0.20), ("spent", float, 0.30),
                 ("rearm", float, 0.55), ("launch", float, 0.75),
                 ("dwell", float, 0.35), ("land_hold", float, 0.22),
                 ("refract", float, 0.20), ("max_flight", float, 1.2),
                 ("linger", float, 0.25), ("rot_fs", float, 600.0),
                 ("acc_fs", float, 25.0), ("speed_tau", float, 0.04),
                 ("grav_tau", float, 0.12), ("act_tau", float, 2.0),
                 ("cone", float, 25.0), ("hold", float, 0.30),
                 ("gap", float, 0.5), ("report", float, 10.0),
                 ("vol", int, 100)],
        "code": """
async def run():
    # THE REST-TONE GATE. Sounds exactly ONE thing: a STABLE REST POSITION,
    # the moment it is detected. No swoosh, no strike coupling. Move however
    # you like: silence. Come to rest and hold: that face's tone, once. Roll
    # slowly to another face while at rest: its tone, once. Leave rest and
    # come back: the tone again. Inside `cone` of a true axis the tone rings
    # full; outside it lands as a dull smudge — the cone edge stays feelable.
    #
    # Faces, mounted on the back of the hand with X toward the wrist:
    #   X- fingers up -> C5    X+ fingers down -> C4
    #   Z+ palm down  -> E4    Z- palm up      -> G4
    #   Y+/Y- hand blade (chop pose) -> D4 / A4  (which edge is which sign
    #   depends on the hand it rides — label it from the first session)
    SENSE = dict(quiet={quiet}, spent={spent}, rearm={rearm},
                 launch={launch}, set_dwell_s={dwell},
                 land_hold_s={land_hold}, refract_s={refract},
                 max_flight_s={max_flight}, set_linger_s={linger},
                 rot_fs={rot_fs}, acc_fs={acc_fs},
                 speed_tau_s={speed_tau}, grav_tau_s={grav_tau},
                 act_tau_s={act_tau})
    CONE_DEG = {cone}      # a rest within this of orthogonal is TRUE
    FACE_HOLD_S = {hold}   # the face must persist this long at rest
    REST_GAP_S = {gap}     # a shorter absence doesn't re-arm the same face
    TONES = {{"X-": 72, "X+": 60, "Z+": 64, "Z-": 67, "Y+": 62, "Y-": 69}}

    sense = KataSense(Calc, **SENSE)
    # Rest is the sense's own "set" band, rebuilt out here where this gate
    # can read it: state False = fallen below `quiet` and held `dwell`. The
    # dead band up to `spent` lets a landing hover keep counting as a pose.
    # Latency from stopping to tone is dwell + hold; if that feels sluggish
    # live, those are the two knobs, in that order.
    set_g = Calc.Gate(SENSE["quiet"], SENSE["spent"], rise_hold_s=0.0,
                      fall_hold_s=SENSE["set_dwell_s"])

    CH = 2
    Synth.all_off()
    Synth.program(CH, 11)               # vibraphone: a struck tone that rings
    Synth.control_change(CH, 11, 127)   # never trust inherited CC state: the
    Synth.control_change(CH, 7, {vol})  # gust seeds zero expression and the
    Synth.pitch_bend(CH, 0)             # vol sweeps leave CC7 anywhere
    Synth.note(CH, 60, 150, 90)         # hello: a rising third. silence here
    await asyncio.sleep_ms(200)         # is the synth path, not the gate
    Synth.note(CH, 64, 250, 90)
    send("feel: quiet={quiet} spent={spent} dwell={dwell} hold={hold} "
         "cone={cone} gap={gap} — rest and hold to sound a face")

    sounded = None       # face already sounded for the current rest
    unset_since = None   # when rest was left (None while resting)
    cand = None          # (face, since) awaiting FACE_HOLD_S

    win_start = time.ticks_ms() / 1000.0
    offs = {{}}          # face -> [off_deg, ...] this window
    inside = 0
    outside = 0
    ticks = 0
    rest_ticks = 0
    s_peak = 0.0         # loudest speed01 this window
    s_rest = 0.0         # loudest speed01 while AT REST — the number `quiet`
                         # has to clear: if it approaches quiet, rest breaks
    nl = 0               # the ladder's own events, counted but never sounded
    nd = 0               # at this stage: launches / lands / overruns
    no = 0

    while True:
        now = time.ticks_ms() / 1000.0
        a = Imu.getAccel()
        g = Imu.getGyro()

        ev = sense.step(a, g, now)
        set_g.update(sense.speed01, now)
        at_rest = not set_g.state
        s = sense.speed01
        ticks += 1
        if s > s_peak:
            s_peak = s
        if ev is not None:
            if ev[0] == "launch":
                nl += 1
            elif ev[0] == "land":
                nd += 1
            else:
                no += 1

        if at_rest:
            rest_ticks += 1
            if s > s_rest:
                s_rest = s
            unset_since = None
            face, off = sense.pose()
            if face is None:
                cand = None
            elif cand is None or cand[0] != face:
                cand = (face, now)
            elif now - cand[1] >= FACE_HOLD_S and face != sounded:
                # a stable rest position, newly reached: sound it NOW
                note = TONES.get(face, 60)
                if off <= CONE_DEG:
                    Synth.note(CH, note, 600, 95)
                    inside += 1
                else:            # the smudge: same tone, dull and short —
                    Synth.note(CH, note, 120, 40)    # the cone edge, felt
                    outside += 1
                offs.setdefault(face, []).append(off)
                sounded = face
        else:
            cand = None
            if unset_since is None:
                unset_since = now
            elif now - unset_since > REST_GAP_S:
                sounded = None   # a real departure: the next rest sounds

        # THE EVIDENCE the knobs get moved on: where the rests landed, how
        # far off, and the speed01 distribution the thresholds sit in.
        if now - win_start > {report}:
            if offs:
                per_face = " ".join(
                    "{{}}:{{}} med {{:.0f}} max {{:.0f}}".format(
                        f, len(v), sorted(v)[len(v) // 2], max(v))
                    for f, v in sorted(offs.items()))
                stats = ("{{}} in / {{}} out of {cone} deg | off_deg {{}}"
                         .format(inside, outside, per_face))
            else:
                stats = "NO RESTS SOUNDED"
            send("feel {{:.0f}}s: {{}} | speed01 peak {{:.2f}} rest-max "
                 "{{:.3f}} (quiet {quiet}) | at rest {{:.0f}}% | ladder "
                 "{{}}L/{{}}D/{{}}O | pose {{}} act {{:.1f}}".format(
                     now - win_start, stats, s_peak, s_rest,
                     100.0 * rest_ticks / max(1, ticks), nl, nd, no,
                     sense.pose(), sense.activity))
            win_start = now
            offs = {{}}
            inside = 0
            outside = 0
            ticks = 0
            rest_ticks = 0
            s_peak = 0.0
            s_rest = 0.0
            nl = 0
            nd = 0
            no = 0

        await asyncio.sleep_ms(5)    # 200 Hz polling
""",
    },
}
