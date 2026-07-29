"""Seed instinct for the puppyc creature: validated asymmetric trot
plus a periodic IMU report. Soul can rewrite this on reflection.

send() only writes to the record — it does not summon the soul. reflect()
does, and costs a reflection, so it is spent on the thing this stage exists
to find out: whether the gait keeps the body upright."""


async def run():
    AMP = 40
    PERIOD_MS = 500
    DUTY = 0.65
    DT_MS = 20
    TIPPED = 0.55        # tilt magnitude that means the trot is failing

    def phase(t):
        t = t % 1.0
        if t < DUTY:
            return AMP - 2 * AMP * (t / DUTY)
        return -AMP + 2 * AMP * ((t - DUTY) / (1 - DUTY))

    center_all()
    await asyncio.sleep_ms(300)

    send("trot amp={} period_ms={} duty={}".format(AMP, PERIOD_MS, DUTY))

    i = 0
    upright = True
    while True:
        t = (i * DT_MS / PERIOD_MS)
        a = phase(t)
        b = phase(t + 0.5)
        set_all(90 + a, 90 + b, 90 + b, 90 + a)
        if i % 50 == 0:
            ax, ay, az = Imu.getAccel()
            tilt = (ax * ax + ay * ay) ** 0.5
            send("trot tick={} ax={:.2f} ay={:.2f} az={:.2f} tilt={:.2f}".format(i, ax, ay, az, tilt))
            now_upright = tilt < TIPPED
            if now_upright != upright:
                # The gait either stopped working or recovered. Either way
                # the parameters above are the thing to think about, and
                # they are not something a reflex can choose.
                reflect("the trot {} at tilt={:.2f} (amp={} period={}ms "
                        "duty={}) after {} ticks".format(
                            "went over" if not now_upright else "came back",
                            tilt, AMP, PERIOD_MS, DUTY, i))
            upright = now_upright
        i += 1
        await asyncio.sleep_ms(DT_MS)
