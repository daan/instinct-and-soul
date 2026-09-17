"""
ultrasonic.py — the M5 Unit Ultrasonic I2C (RCWL-9620) at 0x57.

The smallest possible driver: one byte to trigger a ping, ~120 ms of
patience, three bytes back in micrometres. The runtime's pump calls
trigger() then read() with the wait between them spent in asyncio, so the
loop never blocks on the sensor.

Ranges 20-4500 mm by the datasheet. What comes back outside that is not a
distance, it is the sensor failing to hear an echo — read() collapses it to
0, this body's one representation of "nothing there".
"""

ADDR = 0x57
WAIT_MS = 120       # the datasheet minimum between trigger and read
MIN_MM = 20
MAX_MM = 4500


def trigger(i2c):
    i2c.writeto(ADDR, b"\x01")


def read(i2c):
    """Millimetres, or 0 for no echo. Raises on a bus error — the caller
    decides what an absent sensor means."""
    d = i2c.readfrom(ADDR, 3)
    um = (d[0] << 16) | (d[1] << 8) | d[2]
    mm = um / 1000.0
    if mm < MIN_MM or mm > MAX_MM:
        return 0
    return mm
