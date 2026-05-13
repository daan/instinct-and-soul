async def run():
    while True:
        ax, ay, az = Imu.getAccel()
        dev = ((ax) ** 2 + (ay) ** 2 + (az - 1) ** 2) ** 0.5
        Mem.push("dev", dev, maxlen=300)

        window = Mem.recent("dev", 90)
        if len(window) == 90:
            mean = sum(window) / 90
            if mean < 0.05:
                state = "still"
            elif mean < 0.5:
                state = "held"
            else:
                state = "active"

            last = Mem.latest("state")
            if state != last:
                Mem.push("state", state)
                send("state: {} -> {}".format(last or "?", state))

        await asyncio.sleep_ms(33)
