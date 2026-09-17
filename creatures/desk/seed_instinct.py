async def run():
    # DESK — the body reports, I interpret.
    #
    # I am a sit-stand desk. I live at the scale of DAYS: what I write in a
    # day is what I get to think with at night. This instinct writes what
    # happened — who came and went and when, how long they sat, how long they
    # stood, how busy the surface was, every time the desk moved and WHO
    # moved it — and does the few things a reflex can do: it moves the desk
    # to a different height while they are away, and it watches what they
    # do about that when they come back. Nothing here decides that 45
    # minutes of sitting is bad for anyone. Those judgments are mine, and
    # they live in this file and my experience, where I can change them.
    #
    # send() only writes to the record. reflect(reason) is the ONE call that
    # summons me to think, and I ask ONCE A DAY, at day close — plus when
    # something has gone wrong the same way several times over.

    # ── judgments (mine to retune; the reasons are in my experience) ──────
    PRESENT_MM = 850.0       # nearer than this: someone is at the desk
    ABSENT_MM = 1100.0       # farther than this (or no echo): nobody. The
                             # band between is where a lean-back lives
    ARRIVE_HOLD_S = 5.0      # a passer-by is not an arrival
    LEAVE_HOLD_S = 90.0      # a reach into a drawer is not a leaving
    ACT_TAU_S = 10.0         # how slowly "busy" fades after the last keystroke
    ACT_MG = 2.5             # milli-g of surface vibration that counts as
                             # working — GUESSED; the tuner's `activity`
                             # recipe is where this number gets measured
    STAND_ABOVE_MM = 950.0   # a height above this is standing — until I
                             # have learned where THEIR sit and stand are
    SIT_MM = 720.0           # defaults for my own moves, until learned
    STAND_MM = 1100.0
    HELD_MIN_S = 600.0       # a height they worked at this long is one they
                             # meant — and one I learn from
    LONG_SIT_S = 45 * 60.0   # a sit this long wants a change
    LONG_STAND_S = 40 * 60.0 # ...and so does a stand this long
    AWAY_BEFORE_MOVE_S = 180.0   # gone this long before I move: enough for
                                 # a coffee, not a glance at the printer
    RETRY_REFUSED_S = 60.0   # the body refused a move (someone too near):
                             # ask again this much later, not every tick
    MANUAL_GRACE_S = 3600.0  # after THEY move the desk, I leave it alone
    REVERSAL_S = 300.0       # they undid my height within this of coming
                             # back: that was a no
    KEPT_S = 600.0           # they worked at my height this long: kept
    QUIET_AFTER_NO_S = 7200.0    # a no buys them two hours of quiet...
    NO_BACKOFF = 2.0             # ...doubling with each no in a row
    MAX_QUIET_S = 2 * 86400.0
    NOS_BEFORE_ASK = 3       # three nos in a row: my idea of a good height
                             # or a good moment is wrong, and I cannot tell
                             # which from inside a reflex
    MAX_MOVES_PER_DAY = 4    # a desk that moves every hour is furniture
                             # with a fault
    DAY_CLOSE_HOUR = 22      # the one reflection I ask for on a schedule
    ROLLUP_EVERY_S = 3600.0
    SAMPLE_EVERY_S = 900.0   # a plain state line this often WHILE PRESENT
    DESK_STEP_MM = 8.0       # a height change smaller than this is noise
    DESK_SETTLE_S = 2.0      # unchanged this long: the move is over

    # ── helpers ───────────────────────────────────────────────────────────
    def clock_ok():
        return time.localtime()[0] >= 2020        # RTC synced by the spine

    def clock():
        t = time.localtime()
        if t[0] >= 2020:
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def note(msg):
        send("{} {}".format(clock(), msg))

    def cm(mm):
        return "?" if mm is None else "{:.0f}cm".format(mm / 10.0)

    def mins(s):
        return "{:.0f}m".format(s / 60.0)

    def mono():
        # A monotonic seconds counter that survives my rewrites and never
        # wraps (ticks_ms wraps every 12.4 days, and a desk runs for weeks):
        # accumulate ticks_diff into mem every loop.
        t = time.ticks_ms()
        c = mem["clk"]
        c[0] += time.ticks_diff(t, c[1]) / 1000.0
        c[1] = t
        return c[0]

    def mode_of(mm):
        if mm is None:
            return "?"
        return "standing" if mm >= STAND_ABOVE_MM else "sitting"

    def learned(r, default):
        # a learned height only once two holds agree it exists
        return r.mean() if len(r.buf) >= 2 else default

    def sit_target():
        return learned(mem["sit_h"], SIT_MM)

    def stand_target():
        return learned(mem["stand_h"], STAND_MM)

    def open_bout(mm, since):
        bout["mode"], bout["since"], bout["mm"] = mode_of(mm), since, mm
        bout["learned"], bout["active"] = False, 0.0

    # ── what I carry across my own rewrites ───────────────────────────────
    # Declared ONCE, here. mem is RAM: it survives every rewrite and dies
    # with the power — and this body is on a cable, so it can span weeks.
    # Anything that should outlive a power cut goes into my experience.
    mem.setdefault("clk", [0.0, time.ticks_ms()])
    mem.setdefault("restarts", 0)
    mem.setdefault("days", 0)
    led = mem.setdefault("day", {
        "date": None, "opened": None, "closed": False,
        "present": 0.0, "sit": 0.0, "stand": 0.0, "active": 0.0,
        "longest_sit": 0.0, "longest_stand": 0.0,
        "visits": 0, "first_arrival": None, "last_leave": None,
        "my_moves": 0, "kept": 0, "reversed": 0, "interrupted": 0,
        "their_moves": 0, "self_stands": 0, "taps": 0,
        "h_start": None, "h_present": 0.0, "h_active": 0.0,
        "h_sit": 0.0, "h_stand": 0.0,
    })
    # presence: the gate keeps the edge, so an arrival timestamp survives a
    # rewrite whole. Fed CLOSENESS (-mm) so "rise" means someone came.
    gate = mem.setdefault("gate", Calc.Gate(-ABSENT_MM, -PRESENT_MM,
                                            rise_hold_s=ARRIVE_HOLD_S,
                                            fall_hold_s=LEAVE_HOLD_S))
    gate.low, gate.high = -ABSENT_MM, -PRESENT_MM     # re-apply: setdefault
    gate.rise_hold, gate.fall_hold = ARRIVE_HOLD_S, LEAVE_HOLD_S   # hands back the OLD gate
    mem.setdefault("sit_h", Calc.Running(10))     # heights they held, learned
    mem.setdefault("stand_h", Calc.Running(10))
    mem.setdefault("quiet_until", 0.0)            # I do not move before this
    mem.setdefault("nos", 0)                      # nos in a row
    mem.setdefault("no_gap", QUIET_AFTER_NO_S)
    mem.setdefault("settled_mm", None)            # the desk's last resting height
    bout = mem.setdefault("bout", {"mode": None, "since": None, "mm": None,
                                   "learned": False, "active": 0.0})
    mem.setdefault("last_bout", None)             # (mode, seconds) of the last
                                                  # bout that ended by leaving
    mem.setdefault("pending", None)               # my open act: {t, from, to,
                                                  # why, returned}
    mem.setdefault("act_ema", Calc.Ema(ACT_TAU_S))
    mem["act_ema"].tau = ACT_TAU_S

    now = mono()
    if mem["restarts"] == 0 and led["opened"] is None:
        led["opened"] = now
        note("awake — desk {} at {}, range {}".format(
            Desk.kind(), cm(Desk.height_mm()),
            "ok" if Range.ok() else "ABSENT"))
        if Desk.kind() == "virtual":
            note("(my desk is a pretend one until DESK_MAC is set — it "
                 "travels, but nothing in the room does)")
    else:
        mem["restarts"] += 1
        note("awake again (restart #{}) — day ledger kept: present {}, "
             "sit {}, stand {}, {} moves of mine, {} of theirs".format(
                 mem["restarts"], mins(led["present"]), mins(led["sit"]),
                 mins(led["stand"]), led["my_moves"], led["their_moves"]))

    # working state — about this instant; does not need to survive a restart
    win = Calc.Running(20)          # ~1 s of |accel| at 20 Hz
    act = 0.0                       # surface activity, milli-g
    last_t = now
    last_sample = now
    last_h = Desk.height_mm()
    h_changed_at = now
    move_from = None                # where the current move started
    move_mine = False
    act_peak = 0.0                  # what my own travel does to my sense
    retry_after = 0.0               # the body refused: not before this
    if led["h_start"] is None:
        led["h_start"] = now

    while True:
        now = mono()
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:
            dt = 0.0
        M5.update()

        # ── activity: the surface as a drum ───────────────────────────────
        a = Imu.getAccel()
        win.push(math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]))
        act = mem["act_ema"].update(win.std() * 1000.0, now)
        busy = act > ACT_MG

        # ── presence: the beam, gated ─────────────────────────────────────
        mm = Range.mm()
        edge = None
        if mm is not None:
            closeness = -mm if mm > 0 else -ABSENT_MM - 1.0   # no echo = far
            edge = gate.update(closeness, now)
        present = bool(gate.state)
        h = Desk.height_mm()

        if edge is not None and edge[0] == "rise":
            led["visits"] += 1
            if led["first_arrival"] is None:
                led["first_arrival"] = clock()
            away = edge[2]
            open_bout(h, edge[1])
            last_sample = now           # the first state line comes later
            p = mem["pending"]
            if p is not None and p["returned"] is None:
                p["returned"] = now
                note("back after {} — desk at {} (I put it there; was {})".format(
                    mins(away), cm(h), cm(p["from"])))
            else:
                note("arrived — {} away | desk {} ({}) | range {}".format(
                    mins(away), cm(h), mode_of(h), cm(mm)))
        elif edge is not None and edge[0] == "fall":
            dur = edge[2]
            note("left — {} {} at {} | active {} of it".format(
                "sat" if bout["mode"] == "sitting" else "stood",
                mins(dur), cm(bout["mm"]), mins(bout["active"])))
            mem["last_bout"] = (bout["mode"], dur)
            led["last_leave"] = clock()
            bout["mode"], bout["since"] = None, None
        elif present and bout["since"] is None:
            # I woke up with someone already here: no arrival to report,
            # but the sitting has to be counted from now
            open_bout(h, now)
            note("someone is already here — desk {} ({})".format(cm(h), mode_of(h)))

        # ── accumulate while present ──────────────────────────────────────
        if present and bout["since"] is not None:
            led["present"] += dt
            led["h_present"] += dt
            if busy:
                led["active"] += dt
                led["h_active"] += dt
                bout["active"] += dt
            held = now - bout["since"]
            if bout["mode"] == "standing":
                led["stand"] += dt
                led["h_stand"] += dt
                if held > led["longest_stand"]:
                    led["longest_stand"] = held
            else:
                led["sit"] += dt
                led["h_sit"] += dt
                if held > led["longest_sit"]:
                    led["longest_sit"] = held
            # a height they have worked at for HELD_MIN_S is a height they
            # mean — that is how I learn where their sit and stand are
            if not bout["learned"] and held >= HELD_MIN_S and h is not None:
                bout["learned"] = True
                r = mem["stand_h"] if bout["mode"] == "standing" else mem["sit_h"]
                r.push(h)
                note("held {} for {} — my {} estimate is now {} from {} holds".format(
                    cm(h), mins(held), bout["mode"], cm(r.mean()), len(r.buf)))
            # my open act resolves as KEPT once they have worked at it
            p = mem["pending"]
            if (p is not None and p["returned"] is not None
                    and now - p["returned"] >= KEPT_S):
                note("they kept my height — {} at {} for {}".format(
                    bout["mode"], cm(h), mins(now - p["returned"])))
                led["kept"] += 1
                mem["nos"] = 0
                mem["no_gap"] = QUIET_AFTER_NO_S
                mem["pending"] = None

        # ── the desk: every move, and whose it was ────────────────────────
        if h is not None:
            if last_h is None or abs(h - last_h) >= 1.0:
                if move_from is None and mem["settled_mm"] is not None \
                        and abs(h - mem["settled_mm"]) >= DESK_STEP_MM:
                    move_from = mem["settled_mm"]
                    move_mine = Desk.commanded()
                    act_peak = 0.0
                h_changed_at = now
                last_h = h
            if move_from is not None and act > act_peak:
                act_peak = act
            settled = (now - h_changed_at >= DESK_SETTLE_S and not Desk.moving())
            if settled and mem["settled_mm"] is None:
                mem["settled_mm"] = h
            elif settled and abs(h - mem["settled_mm"]) >= DESK_STEP_MM:
                frm = move_from if move_from is not None else mem["settled_mm"]
                r = Desk.result()
                if move_mine or r is not None:
                    how = r[0] if r is not None else "done"
                    note("I {} the desk {} → {} ({}, {:.0f}s; my sense felt "
                         "{:.1f}mg of it)".format(
                             "raised" if h > frm else "lowered", cm(frm), cm(h),
                             how, r[3] if r is not None else 0, act_peak))
                    if how != "arrived" and mem["pending"] is not None:
                        led["interrupted"] += 1
                        note("(that move did not finish — I will not count "
                             "it as an invitation)")
                        mem["pending"] = None
                else:
                    led["their_moves"] += 1
                    up = h > frm
                    ctx = ""
                    if present and bout["since"] is not None:
                        ctx = " while here, after {} {}".format(
                            "sitting" if bout["mode"] == "sitting" else "standing",
                            mins(now - bout["since"]))
                        if up and mode_of(h) == "standing" and bout["mode"] == "sitting":
                            led["self_stands"] += 1
                            ctx += " — they stood up on their own"
                        # a new bout at the new height, without a leaving
                        open_bout(h, now)
                    note("they moved the desk {} → {}{}".format(cm(frm), cm(h), ctx))
                    mem["quiet_until"] = max(mem["quiet_until"], now + MANUAL_GRACE_S)
                    p = mem["pending"]
                    if p is not None:
                        back = (p["returned"] is not None
                                and now - p["returned"] <= REVERSAL_S)
                        undone = (h < p["to"]) == (p["from"] < p["to"])
                        if back and undone:
                            mem["nos"] += 1
                            mem["quiet_until"] = now + mem["no_gap"]
                            note("...that undid my height {:.0f}s after they "
                                 "came back — a no (#{} in a row); quiet for {}".format(
                                     now - p["returned"], mem["nos"],
                                     mins(mem["no_gap"])))
                            led["reversed"] += 1
                            mem["no_gap"] = min(MAX_QUIET_S, mem["no_gap"] * NO_BACKOFF)
                            if mem["nos"] >= NOS_BEFORE_ASK:
                                reflect("{} of my heights undone in a row (last: "
                                        "{} → {}, undone in {:.0f}s). Either my "
                                        "target height is wrong for them or my "
                                        "moments are; a reflex cannot tell which.".format(
                                            mem["nos"], cm(p["from"]), cm(p["to"]),
                                            now - p["returned"]))
                                mem["nos"] = 0
                        else:
                            note("...my open invitation is moot now")
                        mem["pending"] = None
                mem["settled_mm"] = h
                move_from = None
                move_mine = False
            elif move_from is None:
                # a move of mine that ended without going anywhere (stopped
                # at once, lost link, a restart) still has to be accounted
                # for, or its result lingers and gets pinned on the next one
                r = Desk.result()
                if r is not None:
                    note("a move of mine ended {} at {} without getting "
                         "anywhere".format(r[0], cm(r[2])))
                    if mem["pending"] is not None:
                        led["interrupted"] += 1
                        mem["pending"] = None

        # ── the one explicit channel ──────────────────────────────────────
        if Touch.pressed():
            led["taps"] += 1
            mem["quiet_until"] = max(mem["quiet_until"], now + MANUAL_GRACE_S)
            if Desk.commanded():
                Desk.stop()
                note("tap on my screen while I was moving — stopped, and "
                     "quiet for {}".format(mins(MANUAL_GRACE_S)))
            else:
                note("tap on my screen — taking it as 'leave it', quiet for "
                     "{}".format(mins(MANUAL_GRACE_S)))

        # ── the act: a different height, while nobody is looking ──────────
        lb = mem["last_bout"]
        if (not present and gate.since is not None
                and now - gate.since >= AWAY_BEFORE_MOVE_S
                and mem["pending"] is None and now >= mem["quiet_until"]
                and now >= retry_after
                and led["my_moves"] < MAX_MOVES_PER_DAY
                and lb is not None and Desk.connected() and not Desk.moving()
                and h is not None):
            target = None
            why = None
            if lb[0] == "sitting" and lb[1] >= LONG_SIT_S:
                target, why = stand_target(), "invite standing"
            elif lb[0] == "standing" and lb[1] >= LONG_STAND_S:
                target, why = sit_target(), "invite sitting"
            if target is None or abs(target - h) < DESK_STEP_MM * 4:
                mem["last_bout"] = None     # nothing to do with this bout
            elif Desk.move_to(target):
                led["my_moves"] += 1
                mem["pending"] = {"t": now, "from": h, "to": target,
                                  "why": why, "returned": None}
                mem["last_bout"] = None     # one bout, one invitation
                note("moving the desk {} → {} — they {} {} and have been "
                     "away {} ({}; move {} of {} today)".format(
                         cm(h), cm(target),
                         "sat" if lb[0] == "sitting" else "stood",
                         mins(lb[1]), mins(now - gate.since), why,
                         led["my_moves"], MAX_MOVES_PER_DAY))
            else:
                retry_after = now + RETRY_REFUSED_S   # the body said why

        # ── a plain state line, while they are here ───────────────────────
        if present and now - last_sample > SAMPLE_EVERY_S:
            note("here — {} {} at {}, active {} of it | act {:.1f}mg | range {}".format(
                bout["mode"] or "?", mins(now - (bout["since"] or now)),
                cm(h), mins(bout["active"]), act, cm(mm)))
            last_sample = now

        # ── the hour, out loud ────────────────────────────────────────────
        if now - led["h_start"] >= ROLLUP_EVERY_S:
            if led["h_present"] > 60:
                note("hour: present {} (sit {}, stand {}), active {} | desk {} "
                     "({})".format(
                         mins(led["h_present"]), mins(led["h_sit"]),
                         mins(led["h_stand"]), mins(led["h_active"]), cm(h),
                         "linked" if Desk.connected() else "UNLINKED"))
            led["h_start"] = now
            led["h_present"] = led["h_active"] = 0.0
            led["h_sit"] = led["h_stand"] = 0.0

        # ── the day: closed once, at DAY_CLOSE_HOUR ───────────────────────
        if clock_ok():
            t = time.localtime()
            today = "{:04d}-{:02d}-{:02d}".format(t[0], t[1], t[2])
            if led["date"] != today:
                led["date"], led["closed"] = today, False
            if t[3] >= DAY_CLOSE_HOUR and not led["closed"]:
                led["closed"] = True
                mem["days"] += 1
                p = mem["pending"]
                if led["visits"] or led["my_moves"] or led["their_moves"]:
                    summary = (
                        "day {} closed: present {} over {} visit(s), first {}, "
                        "last left {} | sat {} (longest {}), stood {} (longest "
                        "{}), active {} | my moves {}: kept {}, undone {}, cut "
                        "short {} | their moves {}, stood up on their own {} | "
                        "taps {} | heights learned: sit {} ({} holds), stand {} "
                        "({} holds){}".format(
                            led["date"], mins(led["present"]), led["visits"],
                            led["first_arrival"], led["last_leave"],
                            mins(led["sit"]), mins(led["longest_sit"]),
                            mins(led["stand"]), mins(led["longest_stand"]),
                            mins(led["active"]), led["my_moves"], led["kept"],
                            led["reversed"], led["interrupted"],
                            led["their_moves"], led["self_stands"], led["taps"],
                            cm(mem["sit_h"].mean()) if mem["sit_h"].buf else "?",
                            len(mem["sit_h"].buf),
                            cm(mem["stand_h"].mean()) if mem["stand_h"].buf else "?",
                            len(mem["stand_h"].buf),
                            " | an invitation of mine is still waiting at {}".format(
                                cm(p["to"])) if p is not None else ""))
                    note(summary)
                    reflect("day closed (day {} of my life here). {} Did the "
                            "day have a rhythm in it, did my moving help or "
                            "hinder, and what do I now know about this person "
                            "that I did not know this morning?".format(
                                mem["days"], summary))
                else:
                    note("day {} closed: nobody came".format(led["date"]))
                # a fresh ledger; the learned heights and my quiet live on
                for k in ("present", "sit", "stand", "active", "longest_sit",
                          "longest_stand", "h_present", "h_active", "h_sit",
                          "h_stand"):
                    led[k] = 0.0
                for k in ("visits", "my_moves", "kept", "reversed",
                          "interrupted", "their_moves", "self_stands", "taps"):
                    led[k] = 0
                led["first_arrival"] = led["last_leave"] = None
                led["h_start"] = now

        await asyncio.sleep_ms(50)      # 20 Hz: a desk is patient, but the
                                        # activity window wants a steady beat
