async def run():
    # send() writes to the record; it does not summon the soul. reflect()
    # does, and costs a reflection — so it is called when the world changes
    # state, not on the sampling cadence.
    motor = PWM(Pin(1), freq=5000, duty=0)

    WINDOW = 30
    STILL_VAR = 0.0005      # below this the body is not being moved
    bx, by, bz = [], [], []
    moving = None

    while True:
        ax, ay, az = Imu.getAccel()
        bx.append(ax)
        by.append(ay)
        bz.append(az)
        if len(bx) > WINDOW:
            bx.pop(0)
            by.pop(0)
            bz.pop(0)

        if len(bx) == WINDOW:
            mx = sum(bx) / WINDOW
            my = sum(by) / WINDOW
            mz = sum(bz) / WINDOW
            vx = sum((v - mx) ** 2 for v in bx) / WINDOW
            vy = sum((v - my) ** 2 for v in by) / WINDOW
            vz = sum((v - mz) ** 2 for v in bz) / WINDOW
            light = Als.getLightSensorData()
            prox = Als.getProximitySensorData()
            var = vx + vy + vz
            send("accel x={:.4f} y={:.4f} z={:.4f} var={:.6f} light={} prox={}".format(
                mx, my, mz, var, light, prox))
            now_moving = var > STILL_VAR
            if moving is not None and now_moving != moving:
                reflect("the body {} being moved (var={:.6f}, light={}, "
                        "prox={})".format("started" if now_moving else "stopped",
                                          var, light, prox))
            moving = now_moving
            bx.clear()
            by.clear()
            bz.clear()

        await asyncio.sleep_ms(33)
