async def run():
    motor = PWM(Pin(1), freq=5000, duty=0)

    WINDOW = 30
    bx, by, bz = [], [], []

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
            send("accel x={:.4f} y={:.4f} z={:.4f} var={:.6f} light={} prox={}".format(
                mx, my, mz, vx + vy + vz, light, prox))
            bx.clear()
            by.clear()
            bz.clear()

        await asyncio.sleep_ms(33)
