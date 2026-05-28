"""Virtual clock — milliseconds advanced explicitly by sleep_ms calls."""


class Clock:
    """A simple monotonic counter in milliseconds.

    Virtual time advances only when the simulator's sleep_ms shim runs;
    everything else (IMU reads, audio calls, computation) is instantaneous
    in virtual time. The wall-clock time of running the simulation is
    therefore unrelated to the simulated duration.
    """

    def __init__(self, start_ms: float = 0.0):
        self.now_ms = float(start_ms)

    def advance(self, dt_ms: float) -> None:
        if dt_ms < 0:
            raise ValueError(f"cannot advance backwards: dt_ms={dt_ms}")
        self.now_ms += float(dt_ms)

    def ticks_ms(self) -> int:
        # Match MicroPython's int-returning semantics; fractional ms in now_ms
        # is preserved internally but rounded for the API.
        return int(self.now_ms)
