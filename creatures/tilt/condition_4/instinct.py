async def run():
    # TILT — the organ measures, I interpret.
    #
    # This file is MECHANISM. The judgments are the constants below; the
    # numbers that EARNED each constant live in experience.md, and the
    # rules of this body live in embodiment.md. Keep that split when you
    # rewrite me: a reason written here can be deleted by the next
    # rewrite, a reason written in experience cannot.
    #
    # INVARIANTS — break one and nothing crashes, you just go blind:
    #   1. State lives in mem[...]; locals are scratch, wiped at every
    #      rewrite. Anything that must outlive a rewrite goes through mem.
    #   2. Declare defaults with setdefault at the top of run(), never in
    #      the loop.
    #   3. Never repurpose a key — new meaning, new name.
    #   4. Re-apply retuned gate thresholds after setdefault: it hands
    #      back the OLD gate, so a constant only passed to the
    #      constructor never lands.
    #   5. M5.update() every pass, and inside any chirp group.

    # ── judgment: tempo (provenance in experience.md, "tempo") ────────────
    HINT_AFTER_S = 150.0     # first hint into a stretch — measured, not
                             # guessed (60 is the BENCH value)
    HINT_EVERY_S = 180.0     # spacing before the second hint...
    HINT_BACKOFF = 2.0       # ...doubling while unanswered...
    HINT_MAX_EVERY_S = 1800  # ...up to here
    WATCH_S = 120.0          # how long a hint waits for an answer
    HUSH_WINDOW_S = 15.0     # press this soon after a hint means "quiet"
    HUSH_GRACE_S = 1800.0    # how long a hush holds (guessed, untested)
    SAMPLE_EVERY_S = 300.0   # plain state line (30 is the BENCH value)
    ROLLUP_EVERY_S = 1800.0  # ledger out loud + the scheduled reflection
    IGNORED_BEFORE_ASK = 3   # unanswered chirps before I ask for help

    # ── judgment: sense (provenance in experience.md, "my sense") ─────────
    GATE_LOW = 8.0           # rot (deg/s) below this reads as still...
    GATE_HIGH = 14.0         # ...above this as moving; between, stay put
    GATE_HOLD_S = 0.4        # a crossing must hold this long to count
    GRAV_TAU_S = 1.0         # gravity low-pass: ignores a gesture,
    ROT_TAU_S = 1.0          # follows a real lean
    ZERO_FWD = 0.0           # mount offset, deg; 0 = measure from true
    ZERO_SIDE = 0.0          # vertical (see experience.md, "the zero")
    KEEP_MOVES = 3           # extremes a span remembers whole — extremes,
                             # not counts: a count says how often the body
                             # moved, nothing about what the moving was

    VOL = 60                 # one level, set by ear (experience.md)
    UP = (3500, 3800, 4200, 4600, 4800)            # the hint: lift
    DOWN = (4800, 4600, 4200, 3800, 3500)          # acknowledgment
    TRILL = (3900, 4600, 3900, 4600, 3900, 4600)   # hello

    # ── the voice ─────────────────────────────────────────────────────────
    async def sound(vol, freqs, ms=25):
        Speaker.begin()                # begin/end per group: the amp
        Speaker.setVolume(vol)         # idles audibly if left on
        for f in freqs:
            Speaker.tone(f, ms)
            M5.update()                # a tone only plays while this ticks
            await asyncio.sleep_ms(ms + 15)
        Speaker.end()

    # ── small helpers ─────────────────────────────────────────────────────
    def clock():
        t = time.localtime()
        if t[0] >= 2020:               # RTC synced by the spine
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def note(msg):
        send("{} {}".format(clock(), msg))

    def deg(x):
        n = int(round(x))              # round FIRST, or -0.5 prints "-0"
        return "+{}".format(n) if n >= 0 else str(n)

    def calc_lean_fwd(g):
        # deg forward of true vertical: upright 0, face-down +90, on the
        # back -90. Keeps being true when they lie down.
        if not g:
            return 0.0
        return math.degrees(math.atan2(g[2], -g[0])) - ZERO_FWD

    def calc_lean_side(g):
        # deg sideways; NEGATIVE is to their right (the mount decides
        # this — embodiment.md has the geometry). DEGENERATE when |fwd|
        # is large: lying flat, this swings on noise. Check fwd before
        # ever branching on it, or a bed reads as a violent lean.
        if not g:
            return 0.0
        return math.degrees(math.atan2(g[1], -g[0])) - ZERO_SIDE

    def lean_str():
        g = mem["grav"]
        return "{},{}".format(deg(calc_lean_fwd(g)), deg(calc_lean_side(g)))

    def keep_top(lst, dur, turn):
        # a movement whole — [seconds, degrees turned] — biggest
        # KEEP_MOVES by turn: turn is closest to how much moving the
        # movement held
        lst.append([dur, turn])
        lst.sort(key=lambda m: -m[1])
        del lst[KEEP_MOVES:]

    def moves_str(lst):
        if not lst:
            return "no moves kept"
        return "biggest moves " + ", ".join(
            "{:.0f}s/{:.0f}\u00b0".format(m[0], m[1]) for m in lst)

    now = time.ticks_ms() / 1000.0

    # ── what I carry across my own rewrites (invariants 1-2) ──────────────
    for k, v in (
        ("worn_since", None), ("still", 0.0), ("longest", 0.0),
        ("chirps", 0), ("presses", 0), ("restarts", 0),
        ("hushed_until", 0.0), ("hint_gap", HINT_EVERY_S),
        ("last_hint", -1e9), ("ignored_run", 0),
        ("h_start", None), ("h_still", 0.0), ("h_longest", 0.0),
        ("h_chirps", 0), ("h_presses", 0),
        ("grav", []),                  # smoothed pose
        ("moves", []),                 # biggest movements of the wearing
        ("h_moves", []),               # ...and of this span
    ):
        mem.setdefault(k, v)
    # The gate IS my stillness sense; living in mem, its edge (gate.since,
    # the timestamp quiet or motion began) survives my rewrites exact.
    mem.setdefault("gate", Calc.Gate(GATE_LOW, GATE_HIGH, GATE_HOLD_S))
    gate = mem["gate"]                 # alias is safe: never rebound
    gate.low, gate.high, gate.hold = GATE_LOW, GATE_HIGH, GATE_HOLD_S
    # ^ re-applied every start (invariant 4)

    waking = mem["worn_since"] is None
    if waking:
        mem["worn_since"] = now
        mem["h_start"] = now
        note("awake, new memory. battery {}mV".format(
            M5.Power.getBatteryVoltage()))
    else:
        mem["restarts"] += 1
        # RESTART, not "rewrite": code is replaced for several reasons
        # and only one of them is that I changed my mind
        note("awake again (restart #{}) — memory kept: worn {:.0f}m, "
             "still {:.0f}m, {} chirps, {} presses".format(
                 mem["restarts"], (now - mem["worn_since"]) / 60,
                 mem["still"] / 60, mem["chirps"], mem["presses"]))

    if waking:
        # for WAKING only: trilling on every restart made a reconnect
        # sound exactly like a chirp
        await sound(VOL, TRILL, 30)

    # working state — deliberately locals, not mem: an open hint and a
    # movement mid-measurement are about this instant, and an instant
    # does not survive a restart anyway
    pending = None          # [t_sent, still_at_send] of an open hint
    move_peak = 0.0         # hardest instant of the current movement, dps
    move_turn = 0.0         # the whole movement, integrated: deg turned
    move_from = "?"         # the lean the movement started from
    rot_ema = 0.0
    last_t = now
    last_sample = now

    def still_s(now):
        return 0.0 if gate.state else now - gate.since

    # ── the phases the loop dispatches over ───────────────────────────────
    def sense(a, g, now, dt):
        # raw IMU -> smoothed pose + rotation -> the gate. Accumulates
        # totals and the current movement; returns the edge event or None.
        nonlocal rot_ema, move_peak, move_turn, move_from
        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        rot_ema += min(1.0, dt / ROT_TAU_S) * (rot - rot_ema)
        grav = mem["grav"]
        if not grav:
            grav.extend(a)
        k = min(1.0, dt / GRAV_TAU_S)
        for i in range(3):
            grav[i] += k * (a[i] - grav[i])

        edge = gate.update(rot_ema, now)

        if gate.state:                 # moving: measure the movement
            if rot_ema > move_peak:
                move_peak = rot_ema
            move_turn += rot_ema * dt  # not a distance — how much turning
                                       # the movement held. A shove and a
                                       # walk can peak alike; they do not
                                       # accumulate alike.
        else:                          # still: accumulate
            s = now - gate.since
            mem["still"] += dt
            mem["h_still"] += dt
            if s > mem["longest"]:
                mem["longest"] = s
            if s > mem["h_longest"]:
                mem["h_longest"] = s

        if edge is None:
            return None
        kind, t_edge, ended = edge     # ended = exact duration of the
        if kind == "rise":             # state that just closed
            move_from = lean_str()
            move_peak = 0.0
            move_turn = 0.0
            return ("moving", ended)
        return ("moved", ended)

    def record(ev, now):
        kind, dur = ev
        if kind == "moving":
            note("moving — was still {:.0f}s | lean {}".format(
                dur, move_from))
        else:
            # the movement, whole: PEAK because stillness resumes at the
            # threshold so "rot now" says nothing; TURN because peak
            # cannot tell a shove from a carry; the leans because a
            # stretch comes back to where it started and a repositioning
            # does not
            note("moved {:.0f}s — peak rot {:.0f}, turned {:.0f}\u00b0"
                 " | lean {} \u2192 {}".format(
                     dur, move_peak, move_turn, move_from, lean_str()))
            keep_top(mem["moves"], dur, move_turn)
            keep_top(mem["h_moves"], dur, move_turn)

    async def hint_lifecycle(ev, pressed, now):
        # the one open question — an unanswered hint — and the three
        # ways it closes, all in this block
        nonlocal pending

        # 1. a movement answers it. ANY movement: this person answers a
        #    chirp with a 3-6s shift (experience.md), so gating the
        #    answer on size would score every real reply as ignored.
        if (ev is not None and ev[0] == "moved" and pending is not None
                and now - pending[0] <= WATCH_S):
            note("...that came {:.0f}s after my chirp (moved {:.0f}s)"
                 .format(now - pending[0], ev[1]))
            pending = None
            mem["ignored_run"] = 0     # it worked; start over
            mem["hint_gap"] = HINT_EVERY_S
            await sound(VOL, DOWN)

        # 2. a press hushes it — or, with nothing of mine open, is the
        #    rarer thing: they spoke first. A press cannot be an
        #    accident; what an unprompted one means is not settled, so
        #    it is written down and left alone.
        if pressed:
            mem["presses"] += 1
            mem["h_presses"] += 1
            if pending is not None and now - pending[0] <= HUSH_WINDOW_S:
                gap, still_then = now - pending[0], pending[1]
                note("press {:.0f}s after my chirp — taking it as "
                     "'quiet', silent for {:.0f}min".format(
                         gap, HUSH_GRACE_S / 60))
                pending = None
                mem["hushed_until"] = now + HUSH_GRACE_S
                mem["hint_gap"] = HINT_EVERY_S     # no grudges
                mem["ignored_run"] = 0
                # the clearest signal I ever get, and the only one where
                # they answered me on purpose
                reflect("hushed {:.0f}s after I chirped at {:.1f}m "
                        "still — they heard me and said no".format(
                            gap, still_then / 60))
            else:
                note("press (nothing of mine was open)")

        # 3. the watch window expires it — an ignored hint is data too
        if pending is not None and now - pending[0] > WATCH_S:
            note("nothing followed my chirp in {:.0f}min (still {:.1f}m "
                 "when I sent it)".format(WATCH_S / 60, pending[1] / 60))
            pending = None
            mem["ignored_run"] += 1
            if mem["ignored_run"] >= IGNORED_BEFORE_ASK:
                # repeating the same call will not tell me anything new;
                # this needs a different idea, which is not mine to have
                # from inside a reflex
                reflect("{} chirps in a row with nothing following — no "
                        "movement, no press. Volume {}, first at "
                        "{:.0f}m still, backing off to {:.0f}m between. "
                        "Either my voice is not reaching them, or these "
                        "are not moments worth interrupting.".format(
                            mem["ignored_run"], VOL, HINT_AFTER_S / 60,
                            mem["hint_gap"] / 60))
                mem["ignored_run"] = 0

    async def maybe_hint(now):
        nonlocal pending
        still = still_s(now)
        if (still > HINT_AFTER_S and now > mem["hushed_until"]
                and pending is None
                and now - mem["last_hint"] > mem["hint_gap"]):
            note("chirped, soft — still {:.1f}m | lean {}".format(
                still / 60, lean_str()))
            await sound(VOL, UP)
            pending = [now, still]
            mem["last_hint"] = now
            mem["hint_gap"] = min(HINT_MAX_EVERY_S,
                                  mem["hint_gap"] * HINT_BACKOFF)
            mem["chirps"] += 1
            mem["h_chirps"] += 1

    def maybe_sample(now):
        nonlocal last_sample
        if now - last_sample > SAMPLE_EVERY_S:
            note("still {:.1f}m | lean {} | rot {:.1f}".format(
                still_s(now) / 60, lean_str(), rot_ema))
            last_sample = now

    def maybe_rollup(now):
        if now - mem["h_start"] <= ROLLUP_EVERY_S:
            return
        note("last {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
             "{} chirps, {} presses".format(
                 (now - mem["h_start"]) / 60, mem["h_still"] / 60,
                 mem["h_longest"] / 60, moves_str(mem["h_moves"]),
                 mem["h_chirps"], mem["h_presses"]))
        note("worn {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
             "{} chirps, {} presses | battery {}mV".format(
                 (now - mem["worn_since"]) / 60, mem["still"] / 60,
                 mem["longest"] / 60, moves_str(mem["moves"]),
                 mem["chirps"], mem["presses"],
                 M5.Power.getBatteryVoltage()))
        # the smallest span where a PATTERN can show. The extremes go
        # with it because a reflection that only hears counts can only
        # think in counts. The one reflection asked for on a schedule.
        reflect("{:.0f}m closed: still {:.0f}m of them, longest "
                "{:.1f}m, {}. {} chirps, {} presses. Worn {:.0f}m in "
                "total. What did their moving consist of, and do my "
                "words for it still fit?".format(
                    (now - mem["h_start"]) / 60, mem["h_still"] / 60,
                    mem["h_longest"] / 60, moves_str(mem["h_moves"]),
                    mem["h_chirps"], mem["h_presses"],
                    (now - mem["worn_since"]) / 60))
        mem["h_start"] = now
        mem["h_still"] = 0.0
        mem["h_longest"] = 0.0
        mem["h_moves"] = []            # plain assignment persists: it
        mem["h_chirps"] = 0            # writes INTO mem
        mem["h_presses"] = 0

    # ── the loop: a dispatcher, nothing more ──────────────────────────────
    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:         # ticks wrapped, or a long stall
            dt = 0.0

        a = Imu.getAccel()             # both from the same instant,
        g = Imu.getGyro()              # accel first
        M5.update()                    # the voice; the body latches Button

        ev = sense(a, g, now, dt)
        if ev is not None:
            record(ev, now)
        await hint_lifecycle(ev, Button.pressed(), now)
        await maybe_hint(now)
        maybe_sample(now)
        maybe_rollup(now)

        await asyncio.sleep_ms(20)     # 50 Hz: the turn integral above is
                                       # only as true as this loop is steady
