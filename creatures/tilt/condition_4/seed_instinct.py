async def run():
    # TILT — the organ measures, I interpret.
    #
    # This instinct does not name what the body did. It writes numbers —
    # minutes held still, degrees of lean from the upright zero, how
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
    IGNORED_BEFORE_ASK = 3   # chirps in a row that nothing followed; no
                             # movement, no press: my voice or my timing
                             # is wrong and I cannot tell which from
                             # inside a reflex. Guessed, untested 

    # ── tempo (mine to retune) ────────────────────────────────────────────
    HINT_AFTER_S = 150.0     # first hint once stillness has run this long.
                             # MEASURED, not guessed (2026-07-30, 162 stretches
                             # over 67 worn minutes): this back's stillness has
                             # a median of 9s and a 90th percentile of 49s, and
                             # its longest stretch all session was 219s. At 240
                             # I was structurally MUTE — 0 of 162 stretches
                             # reached it, and I then read my own silence as
                             # good manners. 150 fires on ~3 stretches an hour:
                             # rare enough not to nag, often enough that I can
                             # find out whether my voice does anything at all.
                             # (60 is the BENCH value, for hearing a chirp
                             # without sitting still for minutes.)
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
    HUSH_GRACE_S = 1800.0    # (guessed, never yet tested) no hush has 
                             # ever landed on a real back
    SAMPLE_EVERY_S = 300.0   # a plain state line this often. (30 is the
                             # BENCH value, so a human watching the journal
                             # can see the body is alive. Worn at 30 s a day
                             # is ~1000 lines of nothing-happened for my next
                             # reflection to read.)
    ROLLUP_EVERY_S = 1800.0  # the ledger line, and the one reflection I ask
                             # for on a schedule rather than in response to
                             # something
    WALK_S = 20.0            # a movement at least this long, turning at
    WALK_TURN = 800.0        # least this much, is LOCOMOTION rather than a
                             # re-sit. Yesterday's numbers make the two
                             # unmistakable: rustles turned 5-70 degrees,
                             # re-sits 100-600, and walking to the coffee
                             # machine turned 2400-7000 over a minute or more.
                             # I care because of what walking IS to me: when
                             # they are on their feet their spine is near
                             # true vertical, so whatever lean I read then is
                             # not their posture — it is MY OFFSET. Every walk
                             # hands me a free estimate of where I hang, and
                             # if the strap shifts at lunchtime the next walk
                             # says so. I only WATCH for now: the estimate is
                             # reported, never applied. Applying it is a
                             # decision, and I would rather make it once I
                             # have seen whether it holds still.
    KEEP_MOVES = 3           # how many movements a span remembers whole.
                             # The ledger keeps EXTREMES, not counts: a
                             # count says how often the body moved and
                             # nothing about what any of the moving was.
                             # What these movements WERE is not settled
                             # here; the numbers go to reflection and
                             # the words are mine to find there.
    MIN_STATE_S = 0.4        # a state must hold this long before I report
                             # the change, so a gyro hovering at the
                             # threshold cannot chatter. Short enough that a
                             # quick shove of the chair still lands.
    # ── my senses, which are mine ─────────────────────────────────────────
    # These used to be an organ: a module in my body that did the arithmetic
    # and handed me answers. Almost all of it was machinery I never used, and
    # what I did use is fourteen lines of trigonometry. So it lives here now,
    # where I can read it, change it, and be wrong about it on purpose.
    STILL_DPS = 10.0         # rotation below this reads as holding still. THE
                             # single most consequential number I own: it
                             # decides what counts as a movement at all.
    GRAV_TAU_S = 1.0         # gravity low-pass. Slow enough to ignore a
                             # gesture, fast enough to follow a real lean.
    ROT_TAU_S = 1.0          # smoothing on the rotation magnitude
    ZERO_FWD = 0.0           # MY MOUNT OFFSET, in degrees, forward positive.
    ZERO_SIDE = 0.0          # (sideways: NEGATIVE is to their RIGHT,
                             # positive to their LEFT.
                             # see calc_lean_side below for why.)
                             # Zero means "measure from true vertical", which
                             # is where I start: gravity is an absolute
                             # reference and I never need to capture one. But
                             # I am strapped near a neck, so a few degrees of
                             # what I read as forward lean is really just
                             # where I hang. That constant offset is these two
                             # numbers, and estimating them is mine to do —
                             # see the walk estimate below.

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

    def note(msg):
        send("{} {}".format(clock(), msg))

    def deg(x):
        n = int(round(x))          # round FIRST: "{:+.0f}" of -0.5 prints
        return "+{}".format(n) if n >= 0 else str(n)   # "-0", which reads
                                                       # like a real lean

    def calc_lean_fwd(g):
        """Degrees the spine is tilted FORWARD from true vertical, from the
        smoothed gravity vector. Positive forward, negative back: upright is
        0, +90 is lying face down, -90 is lying on the back.

        Nothing here assumes they are sitting, or even upright. If they lie
        down to rest this reads near +/-90 and keeps being true — that is not
        a broken sense, it is a person horizontal, and I would rather be able
        to see that than have a sense that only works in a chair."""
        if g is None:
            return 0.0
        return math.degrees(math.atan2(g[2], -g[0])) - ZERO_FWD

    def calc_lean_side(g):
        """Degrees the spine is tilted SIDEWAYS from true vertical.

        NEGATIVE IS TO THEIR RIGHT, POSITIVE IS TO THEIR LEFT. 

        It falls out of the geometry rather than anyone choosing it. My axes
        are +X down the spine, +Y to their right, +Z backward out of my
        screen and away from them. An accelerometer reads the OPPOSITE of
        gravity, so leaning right — which tips gravity toward their right,
        my +Y — reads negative. Forward stays positive because +Z points
        backward, so a forward lean tips gravity toward my -Z and the
        reading goes the other way. Hence the asymmetry: forward positive,
        right negative. It looks arbitrary and it is not.

        Sanity, at the extremes: face down is gravity toward their chest, so
        fwd +90 and this reads nothing meaningful. On their right side is
        gravity toward their right, so this reads -90.

        WHICH MEANS THIS NUMBER GOES DEGENERATE WHEN THEY LIE DOWN. Flat on
        the front or back, gravity has left the X-Y plane entirely and this
        swings to +/-180 on noise alone. If I ever branch on it, check that
        |fwd| is small first, or I will read a bed as a violent lean."""
        if g is None:
            return 0.0
        return math.degrees(math.atan2(g[1], -g[0])) - ZERO_SIDE

    def lean_str():
        return "{},{}".format(deg(calc_lean_fwd(grav)),
                              deg(calc_lean_side(grav)))

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

    # Every local variable in run() is wiped when I rewrite myself, and I
    # rewrite myself at every reflection. If the totals lived in locals,
    # reflection would reset the very numbers reflection exists to read —
    # "worn 3h" would silently mean "since the last time I changed my mind".
    # (All of it is RAM on the board and does NOT survive a reboot. A power
    # cycle is a genuinely new wearing, and the restarts count tells me which
    # kind of restart I just had.)
    # ── what I carry across my own rewrites ───────────────────────────────
    # keep() hands back the SAME object every instinct that asks for the name,
    # so a mutation is persisted the moment it happens. Nothing to flush,
    # nothing to write back. It dies with the power, not with my rewrites.
    #
    # THE RULE THAT DECIDES THE SHAPE BELOW: what keep() hands out is what
    # persists. A float handed out is a float I can only REBIND — `still += dt`
    # would make a new float this registry never sees. So every counter lives
    # inside ONE dict, which is mutable, and I write led["still"] rather than
    # still. Lists and windows are mutable already, so they get their own name.
    #
    # AND THE RULE FOR CHANGING IT: never repurpose a key. If "moves" should
    # mean something new, call it something new. A rewrite that redefines a
    # key keeps the old contents — same name, same type, different meaning —
    # and nothing can detect that. A new name gets a correct fresh default,
    # and keep() journals the change so a later me can see it happened.
    led = keep("ledger", {
        "worn_since": None, "still": 0.0, "longest": 0.0,
        "chirps": 0, "presses": 0, "restarts": 0,
        "hushed_until": 0.0, "hint_gap": HINT_EVERY_S,
        "last_hint": -1e9, "ignored_run": 0,
        "h_start": None, "h_still": 0.0, "h_longest": 0.0,
        "h_chirps": 0, "h_presses": 0,
        # MY SENSE'S OWN STATE. still_since is a TIMESTAMP, not a counter, so
        # a stored one stays exact however long ago it was written — and it is
        # the one thing here that actually hurts to lose: stillness would reset
        # to zero at every reflection, I would believe they had just moved,
        # never accumulate, never chirp, and nothing would crash to tell me.
        "still_since": None,
    })

    # Mutable, so each is its own keep and needs no merging — a name I have
    # never used before is simply absent, and gets its default.
    grav = keep("grav", [])              # the smoothed pose, mutated in place
    moves = keep("moves", [])            # biggest movements of the wearing
    h_moves = keep("h_moves", [])        # ...and of this span
    walk_fwd = keep("walk_fwd", Calc.Running(20))    # my offset, as walking
    walk_side = keep("walk_side", Calc.Running(20))  # reports it

    waking = led["worn_since"] is None
    if waking:
        led["worn_since"] = now
        led["h_start"] = now
        note("awake, new ledger. battery {}mV".format(
            M5.Power.getBatteryVoltage()))
    else:
        led["restarts"] += 1
        # RESTART, not "rewrite" — my code is replaced for several reasons and
        # only one of them is that I changed my mind. A spine reconnect
        # restarts me too, and calling that a rewrite made it look like I had
        # been thinking when I had not.
        note("awake again (restart #{}) — ledger kept: worn {:.0f}m, "
             "still {:.0f}m, {} chirps, {} presses".format(
                 led["restarts"], (now - led["worn_since"]) / 60,
                 led["still"] / 60, led["chirps"], led["presses"]))

    still_since = led["still_since"]
    rot_ema = 0.0

    if waking:
        # The greeting is for WAKING, not for every time my code is swapped.
        # Trilling on each restart meant a reconnect sounded exactly like a
        # chirp, and they had no way to tell the difference.
        await sound(VOL, TRILL, 30)

    # ── the zero ──────────────────────────────────────────────────────────
    # There isn't a capture, and there is nothing to wait for. Gravity IS an
    # absolute reference: it is there from my first sample and it cannot be
    # argued with. Every lean I write is measured from true vertical.
    #
    # What that reading includes, and what a captured zero used to hide, is a
    # constant few degrees from where I hang on a neck. That is ZERO_FWD /
    # ZERO_SIDE above, and it starts at nothing — so my leans are honest but
    # uncorrected until I work out what my own offset is.
    #
    # I do not take a pose as my zero. A pose taken while they are slumped
    # makes their slump the definition of upright, and then I can never see
    # it. Vertical is not negotiable; their posture is exactly the thing I am
    # supposed to be able to see move.

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

    while True:
        now = time.ticks_ms() / 1000.0
        dt = now - last_t
        last_t = now
        if dt < 0 or dt > 5.0:         # ticks wrapped, or a long stall
            dt = 0.0

        # ── MY SENSE. Fourteen lines that used to be an organ. ────────────
        # Both readings from the same instant, accel first: the gravity I
        # smooth and the rotation I measure have to be the same moment or a
        # fast movement pairs this tick's turning with last tick's pose.
        a = Imu.getAccel()
        g = Imu.getGyro()
        M5.update()                    # the voice; the body latches Button

        rot = math.sqrt(g[0] * g[0] + g[1] * g[1] + g[2] * g[2])
        rot_ema += min(1.0, dt / ROT_TAU_S) * (rot - rot_ema)

        if not grav:
            grav.extend(a)      # in place: rebinding would orphan the kept list
        k = min(1.0, dt / GRAV_TAU_S)
        for _i in range(3):
            grav[_i] += k * (a[_i] - grav[_i])

        # Stillness is a TIMESTAMP, not a running total: still_since is when
        # quiet began, so however long ago it was written the arithmetic below
        # is exact. Written to the ledger on the EDGE only — twice a minute at
        # yesterday's rate, not fifty times a second.
        quiet = rot_ema < STILL_DPS
        if quiet and still_since is None:
            still_since = now
            led["still_since"] = now      # persisted the instant it is set
        elif not quiet and still_since is not None:
            still_since = None
            led["still_since"] = None
        still = 0.0 if still_since is None else now - still_since

        # ── accumulate, on the raw signal ─────────────────────────────────
        if still > 0:
            led["still"] += dt
            led["h_still"] += dt
            if still > led["longest"]:
                led["longest"] = still
            if still > led["h_longest"]:
                led["h_longest"] = still
        else:
            r = rot_ema
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
                    keep_top(moves, dur, move_turn)
                    if dur >= WALK_S and move_turn >= WALK_TURN:
                        # On their feet: what I read now is where I hang.
                        # Add the correction back: this is measuring the
                        # WHOLE offset, not the residual left after applying
                        # one. Once ZERO_FWD is set, the two should agree —
                        # and if they stop agreeing, the strap moved.
                        walk_fwd.push(calc_lean_fwd(grav) + ZERO_FWD)
                        walk_side.push(calc_lean_side(grav) + ZERO_SIDE)
                        note("(that was walking — my offset looks like "
                             "{},{} from {} walks)".format(
                                 deg(walk_fwd.mean()),
                                 deg(walk_side.mean()),
                                 len(walk_fwd.buf)))
                    keep_top(h_moves, dur, move_turn)
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

        # ── a plain state line, on a timer ────────────────────────────────
        if now - last_sample > SAMPLE_EVERY_S:
            note("still {:.1f}m | lean {} | rot {:.1f}".format(
                still / 60, lean_str(), rot_ema))
            last_sample = now

        # ── the ledger, out loud ──────────────────────────────────────────
        if now - led["h_start"] > ROLLUP_EVERY_S:
            note("last {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
                 "{} chirps, {} presses".format(
                     (now - led["h_start"]) / 60, led["h_still"] / 60,
                     led["h_longest"] / 60, moves_str(h_moves),
                     led["h_chirps"], led["h_presses"]))
            note("worn {:.0f}m: still {:.0f}m, longest {:.1f}m, {} | "
                 "{} chirps, {} presses | battery {}mV".format(
                     (now - led["worn_since"]) / 60, led["still"] / 60,
                     led["longest"] / 60, moves_str(moves),
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
                        led["h_longest"] / 60, moves_str(h_moves),
                        led["h_chirps"], led["h_presses"],
                        (now - led["worn_since"]) / 60))
            led["h_start"] = now
            led["h_still"] = 0.0
            led["h_longest"] = 0.0
            del h_moves[:]     # in place: rebinding would orphan the kept list
            led["h_chirps"] = 0
            led["h_presses"] = 0

        await asyncio.sleep_ms(20)     # 50 Hz: posture is patient and a
                                       # press is unhurried, but the gyro
                                       # integration above is only as true
                                       # as this loop is steady
