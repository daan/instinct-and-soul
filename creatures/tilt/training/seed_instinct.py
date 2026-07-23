async def run():
    # TILT baseline, v2 — TRAINING variant: identical behavior to
    # condition_1's seed, but the tempo constants live in the Tempo organ
    # view (module globals in organs.py) so the tuner can retune them live:
    #     set FROZEN_AFTER_S 1200      (seconds; `params` reads them back)
    # Reads happen every loop tick — a set lands within a second. Defaults
    # are bench tempo (statue at 2 min); condition_1 keeps worn tempo.
    #
    # The trigger is STILLNESS, never form: an upright statue is still a
    # statue. Posture words appear only as descriptive flavors inside
    # grammar tokens (README: verbs about movement, never judgments about
    # form). Every sound this animal makes ships as a reafference triplet:
    #     ACT#n INTENT invite-movement ACTION chirp-up lvl2 @14:40
    #     ACT#n OUTCOME moved (FULL_STRETCH after 43s)
    # Outcomes are observed ON-DEVICE, so radio naps never truncate them.
    LVL_VOLS = (40, 50, 62)    # call levels: louder only with persistence
    STATIC_MILESTONES = (10, 20, 40, 80)   # minutes; doubling after
    VARIETY_EVERY_S = 3600.0   # the hourly summary

    UP = (3500, 3800, 4200, 4600, 4800)      # the invitation: lift
    DOWN = (4800, 4600, 4200, 3800, 3500)    # contentment: there you are
    TRILL = (3900, 4600, 3900, 4600, 3900, 4600)   # presence: hello

    async def sound(vol, freqs, ms=25):
        Speaker.begin()                # begin/end per call: the amp idles
        Speaker.setVolume(vol)         # audibly if left on (sticks3 rule)
        for f in freqs:
            Speaker.tone(f, ms)
            M5.update()
            await asyncio.sleep_ms(ms + 15)
        Speaker.end()

    def clock():
        t = time.localtime()
        if t[0] >= 2020:               # RTC synced by the spine (TIME:)
            return "@{:02d}:{:02d}".format(t[3], t[4])
        return "@t+{}s".format(time.ticks_ms() // 1000)

    act_state = [0]

    def act(intent, action):
        act_state[0] += 1
        send("ACT#{} INTENT {} ACTION {} {}".format(
            act_state[0], intent, action, clock()))
        return act_state[0]

    # ── hello: presence, announced and auditable like everything else ──
    act("greet", "trill")
    await sound(50, TRILL, 30)

    pending = None          # [act_n, t_s, lvl] of the open invite-movement
    hushed_until = 0.0
    last_call = 0.0
    calls_this_freeze = 0
    static_next = STATIC_MILESTONES[0]

    hour_start = time.ticks_ms() / 1000.0
    hour_moves = 0
    hour_flavors = []

    while True:
        now = time.ticks_ms() / 1000.0
        Imu.getAccel()                 # feeds Posture/Tap — MY reads
        Imu.getGyro()
        still = Posture.still_s()

        # ── movement verbs: the body's history, named as it happens ──
        v = Posture.verb()
        if v:
            send("{}({})".format(v[0], v[1]) if v[1] else v[0])
            static_next = STATIC_MILESTONES[0]   # motion resets the statue clock
            calls_this_freeze = 0                # and the escalation (no grudges)
            hour_moves += 1
            fl = Posture.flavor()
            if fl not in hour_flavors:
                hour_flavors.append(fl)
            if pending is not None:              # ...and answers an open act
                grade = {"FULL_STRETCH": "stretched",
                         "MOVED_OFF": "stood"}.get(v[0], "moved")
                send("ACT#{} OUTCOME {} ({} after {:.0f}s)".format(
                    pending[0], grade, v[0], now - pending[1]))
                pending = None
                act("acknowledge", "chirp-down")  # content when they move
                await sound(LVL_VOLS[0], DOWN)

        # ── STATIC milestones: "you've been a statue" ──
        if still > static_next * 60:
            send("STATIC({}min, {})".format(static_next, Posture.flavor()))
            if static_next == STATIC_MILESTONES[-1]:
                static_next *= 2
            else:
                static_next = STATIC_MILESTONES[
                    STATIC_MILESTONES.index(static_next) + 1]

        # ── taps: hush if they answer a call; feedback token otherwise ──
        tb = Tap.burst()
        if tb:
            if pending is not None and now - pending[1] <= Tempo.HUSH_WINDOW_S:
                send("ACT#{} OUTCOME hushed (tap x{} within {:.0f}s)".format(
                    pending[0], tb[1], now - pending[1]))
                pending = None
                hushed_until = now + Tempo.HUSH_GRACE_S
                calls_this_freeze = 0            # no grudges
            else:
                send("TAPPED(x{})".format(tb[1]))

        # ── an open act times out: also data ──
        if pending is not None and now - pending[1] > Tempo.OUTCOME_S:
            send("ACT#{} OUTCOME ignored (nothing in {:.0f}s)".format(
                pending[0], Tempo.OUTCOME_S))
            pending = None

        # ── restlessness: frozen too long -> invite movement ──
        if (still > Tempo.FROZEN_AFTER_S and now > hushed_until
                and pending is None and now - last_call > Tempo.CALL_EVERY_S):
            lvl = min(len(LVL_VOLS), 1 + calls_this_freeze)
            n = act("invite-movement", "chirp-up lvl{}".format(lvl))
            await sound(LVL_VOLS[lvl - 1], UP)
            pending = [n, now, lvl]
            last_call = now
            calls_this_freeze += 1

        # ── the hourly summary: a statistic, not a scold ──
        if now - hour_start > VARIETY_EVERY_S:
            rating = ("low" if hour_moves < 2
                      else "ok" if hour_moves < 6 else "lively")
            send("POSTURE_VARIETY({}, this hour: {} moves, flavors {})".format(
                rating, hour_moves, hour_flavors or ["none"]))
            send("BATTERY({}mV{})".format(
                M5.Power.getBatteryVoltage(),
                ", charging" if M5.Power.isCharging() else ""))
            hour_start = now
            hour_moves = 0
            hour_flavors = []

        await asyncio.sleep_ms(20)     # 50 Hz: posture is patient, but
                                       # taps are spikes — don't miss them
