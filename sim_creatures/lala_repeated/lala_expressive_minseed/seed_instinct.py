async def run():
    # A bare starting point — deliberately uncommitted. Read the body, keep a
    # short memory, send an honest summary now and then, and make a quiet, steady
    # sound so there is something to grow from. HOW the body's motion becomes
    # music is yours to find; this start does not decide it.
    CH = 0
    Synth.program(CH, 12)
    WIN = 200
    n = 0
    while True:
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()
        Mem.push("ax", round(ax, 4), maxlen=WIN)   # raw, unreduced
        if n % 8 == 0:                              # soft placeholder pulse, no mapping
            Synth.note(CH, 60, 200, velocity=60)
        n += 1
        if n % WIN == 0:
            send("window {:.0f}s: holding {} raw samples".format(
                len(Mem.recent("ax")) * 0.03, len(Mem.recent("ax"))))
        await asyncio.sleep_ms(30)
