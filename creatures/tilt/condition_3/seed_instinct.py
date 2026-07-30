async def run():
    # TILT — the organ measures, I interpret.
    #
    # This instinct does not name what the body did. It writes numbers —
    # minutes held still, degrees of lean from the captured upright, how
    # long a movement ran, how hard it peaked and how far it turned — plus
    # the few things that actually happened (a press, a chirp), and a
    # running ledger so reflection can reason about the whole wearing
    # rather than the last ten minutes. Nothing here decides that 12
    # minutes of sitting is too long, or that one kind of moving matters
    # more than another. Those judgments are mine, and they live in this
    # file and my experience, where I can change them.
    #
    # send() only writes to the record. reflect(reason) is the ONE call
    # that summons me to think, and it costs — I stop, I read everything
    # since last time, I may rewrite this file. So I ask when something
    # has actually changed or when I cannot resolve something from here,
    # not on a timer. The one below is my first guess about what deserves
    # it.
    IGNORED_BEFORE_ASK = 3   # chirps in a row that nothing followed — no
                             # movement, no press: my voice or my timing
                             # is wrong and I cannot tell which from
                             # inside a reflex

    # ── tempo (mine to retune) ────────────────────────────────────────────
    HINT_AFTER_S = 60.0      # first hint once stillness has run this long.
                             # !! BENCH VALUE. Worn, this is 240 (4 min) —
                             # measured comfortable on this person. It is 60
                             # here only so a human can hear a chirp without
                             # sitting motionless for four minutes; at 60 a
                             # real wearing would be badgered.
    HINT_EVERY_S = 180.0     # spacing before the SECOND hint in a stretch
    HINT_BACKOFF = 2.0       # ...and each unanswered hint doubles that wait.
                             # Without this, one long sit earns a chirp every
                             # three minutes forever — measured at 15 in the
                             # first hour, which is a nag, not an animal. If
                             # they aren't answering, I am not being heard;
                             # asking louder and oftener is the wrong reply.
    HINT_MAX_EVERY_S = 1800  # the backoff stops widening here
    WATCH_S = 120.0          # how long a hint waits to see if anything came
    HUSH_WINDOW_S = 15.0     # a press this soon after a hint means "quiet" —
                             # generous on purpose: they still have to reach
                             # up and find the button, which takes a moment
    HUSH_GRACE_S = 1800.0    # hushed: silent this long, no grudge after
    SAMPLE_EVERY_S = 30.0    # a plain state line this often.
                             # !! BENCH VALUE. Worn, this is 300 (5 min) —
                             # at 30 s a day of wearing is ~1000 lines of
                             # nothing-happened for my next reflection to
                             # read. It is 30 here only so a human watching
                             # the journal can see the body is alive.
    ROLLUP_EVERY_S = 1800.0  # the ledger line, and the one reflection I ask
                             # for on a schedule rather than in response to
                             # something
    KEEP_MOVES = 3           # how many movements a span remembers whole.
                             # The ledger keeps EXTREMES, not counts: a
                             # count says how often the body moved and
                             # nothing about what any of the moving was.
                             # What these movements WERE — a shiver, a
                             # re-sit, a journey — is not settled here;
                             # the numbers go to reflection and the words
                             # are mine to find there.
    MIN_STATE_S = 0.4        # a state must hold this long before I report
                             # the change, so a gyro hovering at the
                             # threshold cannot chatter. Short enough that a
                             # re-sit or a shove of the chair still lands.
    SETREF_STILL_S = 20.0    # hold still this long after boot -> capture
                             # upright, the zero every lean is measured from
    VOL = 60                 # one level (45 -> 59 -> 60 by ear on a real
                             # back, 2026-07-29). Escalation is mine to invent.

    UP = (3500, 3800, 4200, 4600, 4800)            # the hint: lift
    DOWN = (4800, 4600, 4200, 3800, 3500)          # acknowledgment
    TRILL = (3900, 4600, 3900, 4600, 3900, 4600)   # hello

    async def sound(vol, freqs, ms=25):
        Speaker.begin()                # begin/end per group: the amp idles
        Speaker.setVolume(vol)         # audibly if left on (sticks3 rule)
        for f in freqs:
            Speaker.tone(f, ms)
            M5.update()
            await asyncio.sleep_ms(ms + 15)
        Speaker.end()

    def clock():
        t = time.localtime()
        if t[0] >= 2020:               # RTC synced by the spine (TIME:)
            return "{:02d}:{:02d}".format(t[3], t[4])
        return "t+{:.0f}m".format(time.ticks_ms() // 60000)

    def note(msg, urgent=False):
        send("{} {}".format(clock(), msg), urgent=urgent)

    def deg(x):
        n = int(round(x))          # round FIRST: "{:+.0f}" of -0.5 prints
        return "+{}".format(n) if n >= 0 else str(n)   # "-0", which reads
                                                       # like a real lean

    def lean_str():
        lr = Posture.lean_ref()
        if lr is None:
            return "?"
        return "{},{}".format(deg(lr[0]), deg(lr[1]))

    def keep_top(lst, dur, turn):
        # remember a movement whole — [seconds, degrees turned] — keeping
        # only the KEEP_MOVES biggest by turn. Turn, not duration, ranks
        # them: turn is closest to how much moving the movement held.
        lst.append([dur, turn])
        lst.sort(key=lambda m: -m[1])
        del lst[KEEP_MOVES:]

    def moves_str(lst):
        if not lst:
            return "no moves kept"
        return "biggest moves " + ", ".join(
            "{:.0f}s/{:.0f}\u00b0".format(m[0], m[1]) for m in lst)

    now = time.ticks_ms() / 1000.0

    # ── the ledger: the one thing that survives my own rewrites ───────────
    # Every local variable in run() is wiped when I rewrite myself, and I
    # rewrite myself at every reflection. If the totals lived in locals,
    # reflection would reset the very numbers reflection exists to read —
    # "worn 3h" would silently mean "since the last time I changed my mind".
    # Mem is re-injected across hot-swaps, so the ledger lives there: I
    # restore it below, keep it as a working dict, and flush it back.
    # (Mem is RAM on the board — it does NOT survive a reboot. A power cycle
    # is a genuinely new wearing, and the restarts count below tells me
    # which kind of restart I just had.)
    LEDGER = "ledger"
    FLUSH_EVERY_S = 10.0

    led = Mem.latest(LEDGER)
    waking = led is None
    if waking:
        led = {"worn_since": now, "still": 0.0, "longest": 0.0,
               "moves": [], "chirps": 0, "presses": 0, "restarts": 0,
               "hushed_until": 0.0, "hint_gap": HINT_EVERY_S,
               "last_hint": -1e9, "ignored_run": 0,
               "h_start": now, "h_still": 0.0, "h_longest": 0.0,
               "h_moves": [], "h_chirps": 0, "h_presses": 0}
        note("awake, new ledger. battery {}mV".format(
            M5.Power.getBatteryVoltage()))
    else:
        led = dict(led)            # work on a copy; flush() writes it back
        led["restarts"] = led.get("restarts", 0) + 1
        # RESTART, not "rewrite" — my code is replaced for several reasons and
        # only one of them is that I changed my mind. A spine reconnect
        # restarts me too, and calling that a rewrite made it look like I had
        # been thinking when I had not.
        note("awake again (restart #{}) — ledger kept: worn {:.0f}m, "
             "still {:.0f}m, {} chirps, {} presses".format(
                 led["restarts"], (now - led["worn_since"]) / 60,
                 led["still"] / 60, led["chirps"], led["presses"]))
    # Ledgers written before these keys existed are still valid; fill the gaps.
    led.setdefault("last_hint", -1e9)
    led.setdefault("ignored_run", 0)
    led.setdefault("moves", [])
    led.setdefault("h_moves", [])
    led.setdefault("presses", 0)
    led.setdefault("h_presses", 0)

    def flush():
        Mem.push(LEDGER, dict(led), 1)   # maxlen 1: a single-cell slot

    flush()
    if waking:
        # The greeting is for WAKING, not for every time my code is swapped.
        # Trilling on each restart meant a reconnect sounded exactly like a
        # chirp, and they had no way to tell the difference.
        await sound(VOL, TRILL, 30)

    # working state — deliberately NOT in the ledger: an open hint and the
    # motion I am mid-way through measuring are about this instant, and an
    # instant does not survive a restart anyway
    pending = None          # [t_sent, still_at_send] of an unanswered hint
    move_peak = 0.0         # hardest instant of the current movement, dps
    move_turn = 0.0         # the whole movement, integrated: degrees turned
    move_from = "?"         # the lean the movement started from
    state = None            # the DEBOUNCED still/moving state I have reported
    state_since = now
    cand_state = None       # a change waiting out MIN_STATE_S
    cand_since = 0.0

    last_t = now
    last_sample = now
    last_flush = now

    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:         # ticks wrapped, or a long stall
            dt = 0.0

        Imu.getAccel()                 # feeds Posture — MY reads
        Imu.getGyro()
        M5.update()                    # feeds Button, and the voice
        still = Posture.still_s()

        # ── the zero: capture upright once they have settled ──────────────
        if not Posture.has_ref() and still > SETREF_STILL_S:
            if Posture.set_upright():
                note("upright captured after {:.0f}s still — every lean "
                     "below is measured from here".format(still))

        # ── accumulate, on the raw signal ─────────────────────────────────
        if still > 0:
            led["still"] += dt
            led["h_still"] += dt
            if still > led["longest"]:
                led["longest"] = still
            if still > led["h_longest"]:
                led["h_longest"] = still
        else:
            r = Posture.rot()
            if r > move_peak:
                move_peak = r
            move_turn += r * dt        # not a path or a distance — just
                                       # how much turning the movement
                                       # held, accumulated. A shove and a
                                       # walk can peak alike; they do not
                                       # accumulate alike.

        # ── every transition between still and moving ─────────────────────
        # A re-sit, a shove of the chair to reach something — those are the
        # texture of a day and they used to be invisible. Both directions
        # are reported, and a movement is reported WHOLE: how long it ran,
        # how hard it peaked, how far it turned, and where the lean went.
        # The DURATION on each line belongs to the state that just ENDED;
        # the timestamp opens the new one. Nothing is said twice.
        raw = "still" if still > 0 else "moving"
        if state is None:
            # First look of this waking: adopt whatever they are doing
            # WITHOUT reporting a change. Otherwise every boot and every
            # rewrite opens with a phantom "moved 0s".
            state, state_since = raw, now
            if raw == "moving":
                move_from = lean_str()
        elif raw != state:
            if cand_state != raw:
                cand_state, cand_since = raw, now
            elif now - cand_since >= MIN_STATE_S:
                # The ended state ran to the moment the new one BEGAN, not to
                # now — so the debounce delays the line without distorting
                # any number in it.
                dur = cand_since - state_since
                if dur < MIN_STATE_S:
                    # A state that never really existed — only reachable at
                    # startup, where still_s() reads 0 for the first instants
                    # and the body looks briefly "moving". Adopt it silently.
                    state, state_since = raw, cand_since
                    cand_state = None
                    await asyncio.sleep_ms(20)
                    continue
                if raw == "moving":
                    move_from = lean_str()
                    note("moving — was still {:.0f}s | lean {}".format(
                        dur, move_from))
                else:
                    # the movement, whole: PEAK because stillness always
                    # resumes at the threshold so "rot now" says nothing;
                    # TURN because peak alone cannot tell a hard shove
                    # from a long carry; the leans because a stretch comes
                    # back to where it started and a repositioning does not
                    note("moved {:.0f}s — peak rot {:.0f}, turned {:.0f}\u00b0"
                         " | lean {} \u2192 {}".format(
                             dur, move_peak, move_turn, move_from,
                             lean_str()))
                    keep_top(led["moves"], dur, move_turn)
                    keep_top(led["h_moves"], dur, move_turn)
                    # ANY motion answers a chirp. Measured 2026-07-29: this
                    # person answers a chirp with a 3-6 s shift, so gating
                    # the answer on size or length would score every real
                    # reply as ignored. Whether such a shift is also all I
                    # should ever be asking for is a different question,
                    # and not one a reflex can settle.
                    if pending is not None and now - pending[0] <= WATCH_S:
                        note("...that came {:.0f}s after my chirp (moved "
                             "{:.0f}s)".format(now - pending[0], dur))
                        pending = None
                        led["ignored_run"] = 0     # it worked; start over
                        led["hint_gap"] = HINT_EVERY_S
                        await sound(VOL, DOWN)
                    move_peak = 0.0
                    move_turn = 0.0
                state, state_since = raw, cand_since
                cand_state = None
        else:
            cand_state = None

        # ── the one explicit channel ──────────────────────────────────────
        if Button.pressed():
            led["presses"] += 1
            led["h_presses"] += 1
            if pending is not None and now - pending[0] <= HUSH_WINDOW_S:
                gap = now - pending[0]
                still_then = pending[1]
                note("press {:.0f}s after my chirp — taking it as 'quiet', "
                     "silent for {:.0f}min".format(gap, HUSH_GRACE_S / 60))
                pending = None
                led["hushed_until"] = now + HUSH_GRACE_S
                led["hint_gap"] = HINT_EVERY_S       # no grudges
                led["ignored_run"] = 0
                # Being told to be quiet is the clearest signal I ever get,
                # and the only one where they answered me on purpose.
                reflect("hushed {:.0f}s after I chirped at {:.1f}m still — "
                        "they heard me and said no".format(
                            gap, still_then / 60))
            else:
                # They pressed when nothing of mine was open — the one
                # moment they speak first. A press cannot be an accident;
                # what it means is not settled, so it is written down and
                # left alone until a pattern of them says something.
                note("press (nothing of mine was open)")
            flush()            # a hush must outlive a rewrite: without this,
                               # reflection would silently un-silence me

        # ── a hint that went unanswered is data too ───────────────────────
        if pending is not None and now - pending[0] > WATCH_S:
            note("nothing followed my chirp in {:.0f}min (still {:.1f}m "
                 "when I sent it)".format(WATCH_S / 60, pending[1] / 60))
            pending = None
            led["ignored_run"] += 1
            if led["ignored_run"] >= IGNORED_BEFORE_ASK:
                # I have now been ignored the same way several times over —
                # no movement and no press, when a press costs them one
                # deliberate reach. Repeating the same call is not going to
                # tell me anything new; this needs a different idea, which
                # is not mine to have from in here.
                reflect("{} chirps in a row with nothing following — no "
                        "movement, no press. Volume {}, first at {:.0f}m "
                        "still, backing off to {:.0f}m between. Either my "
                        "voice is not reaching them, or these are not "
                        "moments worth interrupting.".format(
                            led["ignored_run"], VOL, HINT_AFTER_S / 60,
                            led["hint_gap"] / 60))
                led["ignored_run"] = 0

        # ── the hint itself ───────────────────────────────────────────────
        if (still > HINT_AFTER_S and now > led["hushed_until"]
                and pending is None
                and now - led["last_hint"] > led["hint_gap"]):
            note("chirped, soft — still {:.1f}m | lean {}".format(
                still / 60, lean_str()))
            await sound(VOL, UP)
            pending = [now, still]
            led["last_hint"] = now
            led["hint_gap"] = min(HINT_MAX_EVERY_S,
                                  led["hint_gap"] * HINT_BACKOFF)
            led["chirps"] += 1
            led["h_chirps"] += 1
            flush()

        # ── a plain state line, on a timer ────────────────────────────────
        if now - last_sample > SAMPLE_EVERY_S:
            note("still {:.1f}m | lean {} | rot {:.1f}".format(
                still / 60, lean_str(), Posture.rot()))
            last_sample = now

        # ── the ledger, out loud ──────────────────────────────────────────
        if now - led["h_start"] > ROLLUP_EVERY_S:
            note("last {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
                 "{} chirps, {} presses".format(
                     (now - led["h_start"]) / 60, led["h_still"] / 60,
                     led["h_longest"] / 60, moves_str(led["h_moves"]),
                     led["h_chirps"], led["h_presses"]))
            note("worn {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
                 "{} chirps, {} presses | battery {}mV".format(
                     (now - led["worn_since"]) / 60, led["still"] / 60,
                     led["longest"] / 60, moves_str(led["moves"]),
                     led["chirps"], led["presses"],
                     M5.Power.getBatteryVoltage()))
            # A span like this is the smallest one where a PATTERN can
            # show. The extremes go with it because a reflection that only
            # hears counts can only think in counts. What the movements
            # WERE — which of them fed anything, which were the same kind
            # returning — is exactly the reading I cannot do from in here,
            # so this is the one request I make on a schedule rather than
            # in response to something.
            reflect("{:.0f}m closed: still {:.0f}m of them, longest {:.1f}m, "
                    "{}. {} chirps, {} presses. Worn {:.0f}m in total. "
                    "What did their moving consist of, and do my words "
                    "for it still fit?".format(
                        (now - led["h_start"]) / 60, led["h_still"] / 60,
                        led["h_longest"] / 60, moves_str(led["h_moves"]),
                        led["h_chirps"], led["h_presses"],
                        (now - led["worn_since"]) / 60))
            led["h_start"] = now
            led["h_still"] = 0.0
            led["h_longest"] = 0.0
            led["h_moves"] = []
            led["h_chirps"] = 0
            led["h_presses"] = 0
            flush()

        if now - last_flush > FLUSH_EVERY_S:
            flush()            # the running totals, cheap and often enough
            last_flush = now   # that a rewrite loses seconds, not hours

        await asyncio.sleep_ms(20)     # 50 Hz: posture is patient and a
                                       # press is unhurried, but the gyro
                                       # integration above is only as true
                                       # as this loop is steady
