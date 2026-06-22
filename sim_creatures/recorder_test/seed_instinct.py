# recorder_test — a plumbing probe, NOT an artistic creature.
#
# Its only job is to exercise all three M5 capture channels so the
# record -> playback pipeline can be verified end-to-end with no LLM cost:
#
#   Imu.getAccel / getGyro  -> input/imu_reads.jsonl
#   Speaker.tone            -> output/audio_events.jsonl   (bake-audio -> .wav)
#   M5.Display.*            -> output/display_log.jsonl
#
# Behaviour is a pure, deterministic function of the IMU, so replaying the
# recorded imu_reads.jsonl reproduces byte-identical audio + display logs.
#
# Synthetic-IMU mocap motion is gentle (Vasso wrist: gyro p90 ~5 deg/s, accel
# deviation < 0.03 g), so features are scaled to that range and drawn against the
# real panel size (M5.Display.width()/height()) rather than a hardcoded guess.

SPIN_FS = 12.0   # deg/s mapped to a full-height bar
DEV_FS = 0.03    # g of accel deviation mapped to the full dot radius


async def run():
    W = M5.Display.width()
    H = M5.Display.height()
    Speaker.begin()
    Speaker.setVolume(160)
    frame = 0

    while True:
        ax, ay, az = Imu.getAccel()
        gx, gy, gz = Imu.getGyro()

        spin = math.sqrt(gx * gx + gy * gy + gz * gz)              # deg/s
        dev = abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)    # g

        # SOUND — pitch tracks rotation; gated low so it sounds most of the time.
        if spin > 1.0:
            freq = 196 + min(spin, SPIN_FS) / SPIN_FS * 784        # 196..980 Hz
            Speaker.tone(freq, 60)

        # DISPLAY — bar = rotation (deg/s), centre dot = accel deviation (g).
        M5.Display.fillScreen(0x000000)
        bar = int(min(spin, SPIN_FS) / SPIN_FS * H)
        M5.Display.fillRect(0, H - bar, W, bar, 0x00cc44)
        r = int(min(dev, DEV_FS) / DEV_FS * (min(W, H) // 4))
        M5.Display.fillCircle(W // 2, H // 2, r, 0xcc3322)

        M5.update()
        frame += 1
        await asyncio.sleep_ms(33)
