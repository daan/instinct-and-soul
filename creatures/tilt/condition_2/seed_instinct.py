async def run():
    # TILT — the organ measures, I interpret.
    #
    # This instinct does not name what the body did. It writes numbers —
    # minutes held still, degrees of lean from the captured upright, dps of
    # motion — plus the few things that actually happened (a tap, a chirp,
    # a break), and a running ledger so reflection can reason about the
    # whole wearing rather than the last ten minutes. Nothing here decides
    # that 12 minutes of sitting is too long. That judgment is mine, and it
    # lives in this file, where I can change it.
    #
    # send() only writes to the record. reflect(reason) is the ONE call that
    # summons me to think, and it costs — I stop, I read everything since
    # last time, I may rewrite this file. So I ask when something has
    # actually changed or when I cannot resolve something from here, not on
    # a timer. The three below are my first guesses about what deserves it.
    IGNORED_BEFORE_ASK = 3   # chirps in a row that nothing followed: my
                             # voice or my timing is wrong and I cannot tell
                             # which from inside a reflex

    # ── tempo (mine to retune) ────────────────────────────────────────────
    HINT_AFTER_S = 240.0     # first hint once stillness has run this long
    HINT_EVERY_S = 180.0     # spacing before the SECOND hint in a stretch
    HINT_BACKOFF = 2.0       # ...and each unanswered hint doubles that wait.
                             # Without this, one long sit earns a chirp every
                             # three minutes forever — measured at 15 in the
                             # first hour, which is a nag, not an animal. If
                             # they aren't answering, I am not being heard;
                             # asking louder and oftener is the wrong reply.
    HINT_MAX_EVERY_S = 1800  # the backoff stops widening here
    WATCH_S = 120.0          # how long a hint waits to see if anything came
    HUSH_WINDOW_S = 15.0     # a tap this soon after a hint means "quiet" —
                             # generous on purpose: they have to reach up
                             # and find me, which takes a moment
    HUSH_GRACE_S = 1800.0    # hushed: silent this long, no grudge after
    SAMPLE_EVERY_S = 300.0   # a plain state line this often
    ROLLUP_EVERY_S = 3600.0  # the ledger line
    BREAK_S = 8.0            # motion at least this long counts as a break
                             # (shorter is a fidget — it still resets
                             # stillness, it just isn't worth a line)
    SETREF_STILL_S = 20.0    # hold still this long after boot -> capture
                             # upright, the zero every lean is measured from
    VOL = 45                 # one level. Escalation is mine to invent.

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
            return "lean ?"
        return "lean {},{}".format(deg(lr[0]), deg(lr[1]))

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
    if led is None:
        led = {"worn_since": now, "still": 0.0, "longest": 0.0,
               "breaks": 0, "chirps": 0, "taps": 0, "restarts": 0,
               "hushed_until": 0.0, "hint_gap": HINT_EVERY_S,
               "h_start": now, "h_still": 0.0, "h_longest": 0.0,
               "h_breaks": 0, "h_chirps": 0, "h_taps": 0}
        note("awake, new ledger. battery {}mV".format(
            M5.Power.getBatteryVoltage()))
    else:
        led = dict(led)            # work on a copy; flush() writes it back
        led["restarts"] = led.get("restarts", 0) + 1
        note("awake again (rewrite #{}) — ledger kept: worn {:.0f}m, "
             "still {:.0f}m, {} breaks, {} chirps".format(
                 led["restarts"], (now - led["worn_since"]) / 60,
                 led["still"] / 60, led["breaks"], led["chirps"]))

    def flush():
        Mem.push(LEDGER, dict(led), 1)   # maxlen 1: a single-cell slot

    flush()
    await sound(VOL, TRILL, 30)

    # working state — deliberately NOT in the ledger: an open hint and the
    # motion I am mid-way through measuring are about this instant, and an
    # instant does not survive a rewrite anyway
    pending = None          # [t_sent, still_at_send] of an unanswered hint
    last_hint = -1e9
    move_start = None
    move_peak = 0.0
    ignored_run = 0         # consecutive chirps nothing followed

    last_t = now
    last_sample = now
    last_flush = now

    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:         # ticks wrapped, or a long stall
            dt = 0.0

        Imu.getAccel()                 # feeds Posture/Tap — MY reads
        Imu.getGyro()
        still = Posture.still_s()

        # ── the zero: capture upright once they have settled ──────────────
        if not Posture.has_ref() and still > SETREF_STILL_S:
            if Posture.set_upright():
                note("upright captured after {:.0f}s still — every lean "
                     "below is measured from here".format(still))

        # ── accumulate, and notice real breaks ────────────────────────────
        if still > 0:
            if move_start is not None:
                dur = now - move_start
                peak = move_peak
                move_start = None
                move_peak = 0.0
                if dur >= BREAK_S:
                    led["breaks"] += 1
                    led["h_breaks"] += 1
                    led["hint_gap"] = HINT_EVERY_S   # they moved: start over
                    # the PEAK rot, not the current one — stillness always
                    # resumes at the threshold, so "rot now" is the same
                    # number every time and says nothing about the break
                    note("moved {:.0f}s, peak rot {:.0f} | now still again "
                         "| {}".format(dur, peak, lean_str()))
                    if pending is not None and now - pending[0] <= WATCH_S:
                        note("...that came {:.0f}s after my chirp".format(
                            now - pending[0]))
                        pending = None
                        ignored_run = 0        # it worked; start over
                        await sound(VOL, DOWN)
            led["still"] += dt
            led["h_still"] += dt
            if still > led["longest"]:
                led["longest"] = still
            if still > led["h_longest"]:
                led["h_longest"] = still
        else:
            if move_start is None:
                move_start = now
            r = Posture.rot()
            if r > move_peak:
                move_peak = r

        # ── the one explicit channel ──────────────────────────────────────
        if Tap.tapped():
            led["taps"] += 1
            led["h_taps"] += 1
            if pending is not None and now - pending[0] <= HUSH_WINDOW_S:
                gap = now - pending[0]
                still_then = pending[1]
                note("tap {:.0f}s after my chirp — taking it as 'quiet', "
                     "silent for {:.0f}min".format(gap, HUSH_GRACE_S / 60))
                pending = None
                led["hushed_until"] = now + HUSH_GRACE_S
                led["hint_gap"] = HINT_EVERY_S       # no grudges
                ignored_run = 0
                # Being told to be quiet is the clearest signal I ever get,
                # and the only one where they answered me on purpose.
                reflect("hushed {:.0f}s after I chirped at {:.1f}m still — "
                        "they heard me and said no".format(
                            gap, still_then / 60))
            else:
                note("tap (nothing of mine was open)")
            flush()            # a hush must outlive a rewrite: without this,
                               # reflection would silently un-silence me

        # ── a hint that went unanswered is data too ───────────────────────
        if pending is not None and now - pending[0] > WATCH_S:
            note("nothing followed my chirp in {:.0f}min (still {:.1f}m "
                 "when I sent it)".format(WATCH_S / 60, pending[1] / 60))
            pending = None
            ignored_run += 1
            if ignored_run >= IGNORED_BEFORE_ASK:
                # I have now been ignored the same way several times over.
                # Repeating the same call is not going to tell me anything
                # new — this needs a different idea, which is not mine to
                # have from in here.
                reflect("{} chirps in a row with nothing following. Volume "
                        "{}, first at {:.0f}m still, backing off to {:.0f}m "
                        "between. Either they cannot hear me, or this is not "
                        "a moment worth interrupting.".format(
                            ignored_run, VOL, HINT_AFTER_S / 60,
                            led["hint_gap"] / 60))
                ignored_run = 0

        # ── the hint itself ───────────────────────────────────────────────
        if (still > HINT_AFTER_S and now > led["hushed_until"]
                and pending is None and now - last_hint > led["hint_gap"]):
            note("chirped, soft — still {:.1f}m | {}".format(
                still / 60, lean_str()))
            await sound(VOL, UP)
            pending = [now, still]
            last_hint = now
            led["hint_gap"] = min(HINT_MAX_EVERY_S,
                                  led["hint_gap"] * HINT_BACKOFF)
            led["chirps"] += 1
            led["h_chirps"] += 1
            flush()

        # ── a plain state line, on a timer ────────────────────────────────
        if now - last_sample > SAMPLE_EVERY_S:
            note("still {:.1f}m | {} | rot {:.1f}".format(
                still / 60, lean_str(), Posture.rot()))
            last_sample = now

        # ── the ledger, out loud ──────────────────────────────────────────
        if now - led["h_start"] > ROLLUP_EVERY_S:
            note("hour: still {:.0f}m of {:.0f}m, longest {:.1f}m, "
                 "{} breaks, {} chirps, {} taps".format(
                     led["h_still"] / 60, (now - led["h_start"]) / 60,
                     led["h_longest"] / 60, led["h_breaks"],
                     led["h_chirps"], led["h_taps"]))
            note("worn {:.0f}m: still {:.0f}m, longest {:.1f}m, {} breaks, "
                 "{} chirps, {} taps | battery {}mV".format(
                     (now - led["worn_since"]) / 60, led["still"] / 60,
                     led["longest"] / 60, led["breaks"], led["chirps"],
                     led["taps"], M5.Power.getBatteryVoltage()))
            # An hour is the smallest span where a PATTERN can show — which
            # hours they sit longest, whether my chirps land better early or
            # late. That is exactly the reading I cannot do from in here, so
            # this is the one request I make on a schedule rather than in
            # response to something.
            reflect("hour closed: still {:.0f}m of {:.0f}m, longest {:.1f}m, "
                    "{} breaks, {} chirps, {} taps. Worn {:.0f}m in total. "
                    "Is my timing right for this person?".format(
                        led["h_still"] / 60, (now - led["h_start"]) / 60,
                        led["h_longest"] / 60, led["h_breaks"],
                        led["h_chirps"], led["h_taps"],
                        (now - led["worn_since"]) / 60))
            led["h_start"] = now
            led["h_still"] = 0.0
            led["h_longest"] = 0.0
            led["h_breaks"] = 0
            led["h_chirps"] = 0
            led["h_taps"] = 0
            flush()

        if now - last_flush > FLUSH_EVERY_S:
            flush()            # the running totals, cheap and often enough
            last_flush = now   # that a rewrite loses seconds, not hours

        await asyncio.sleep_ms(20)     # 50 Hz: posture is patient, but
                                       # taps are spikes — don't miss them
