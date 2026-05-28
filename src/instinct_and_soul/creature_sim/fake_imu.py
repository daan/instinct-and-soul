"""Fake Imu module: linear-interp samples from an .npz, log every read."""
import json
import os
import numpy as np


class NpzImuSource:
    """Hold an IMU stream from imu.npz and serve interpolated values by time.

    Expected arrays:
      t_ms:  shape (N,)        — virtual ms, monotonic, 0-based
      accel: shape (N, 3)      — g, sensor-frame
      gyro:  shape (N, 3)      — deg/s, sensor-frame
    """

    def __init__(self, path: str):
        z = np.load(path)
        self.t_ms = np.asarray(z["t_ms"], dtype=np.float64)
        self.accel = np.asarray(z["accel"], dtype=np.float64)
        self.gyro  = np.asarray(z["gyro"],  dtype=np.float64)
        if self.t_ms.ndim != 1 or len(self.t_ms) < 2:
            raise ValueError("imu.npz needs t_ms with at least 2 samples")
        if self.accel.shape != (len(self.t_ms), 3):
            raise ValueError(f"accel shape {self.accel.shape} doesn't match t_ms")
        if self.gyro.shape != (len(self.t_ms), 3):
            raise ValueError(f"gyro shape {self.gyro.shape} doesn't match t_ms")
        # Monotonic-read cursor: bisect would be fine too, but reads in the
        # sim are monotonic in virtual time, so incrementing is O(1).
        self._cursor = 0

    @property
    def duration_ms(self) -> float:
        return float(self.t_ms[-1] - self.t_ms[0])

    @property
    def end_ms(self) -> float:
        return float(self.t_ms[-1])

    def _advance_cursor(self, t: float) -> int:
        # Find i such that t_ms[i] <= t < t_ms[i+1]. Walk forward from cursor.
        i = self._cursor
        n = len(self.t_ms)
        while i + 1 < n and self.t_ms[i + 1] <= t:
            i += 1
        # Allow backwards lookup too — bisect handles it, but cheaper to drop back
        while i > 0 and self.t_ms[i] > t:
            i -= 1
        self._cursor = i
        return i

    def _interp(self, t: float, arr: np.ndarray) -> tuple[float, float, float]:
        if t <= self.t_ms[0]:
            v = arr[0]
            return float(v[0]), float(v[1]), float(v[2])
        if t >= self.t_ms[-1]:
            v = arr[-1]
            return float(v[0]), float(v[1]), float(v[2])
        i = self._advance_cursor(t)
        t0, t1 = self.t_ms[i], self.t_ms[i + 1]
        frac = (t - t0) / (t1 - t0)
        v = (1.0 - frac) * arr[i] + frac * arr[i + 1]
        return float(v[0]), float(v[1]), float(v[2])

    def accel_at(self, t_ms: float):
        return self._interp(t_ms, self.accel)

    def gyro_at(self, t_ms: float):
        return self._interp(t_ms, self.gyro)


class _CapturingImu:
    """Module-level Imu replacement. Reads from the source, logs each access."""

    def __init__(self, source: NpzImuSource, clock, log_path: str):
        self._source = source
        self._clock = clock
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w")

    def getAccel(self):
        t = self._clock.now_ms
        v = self._source.accel_at(t)
        g = self._source.gyro_at(t)
        self._log.write(json.dumps({
            "t": t, "ax": v[0], "ay": v[1], "az": v[2],
            "gx": g[0], "gy": g[1], "gz": g[2],
        }) + "\n")
        return v

    def getGyro(self):
        # Logged via getAccel above (each read logs both for completeness).
        # On the real device they're separate reads; in the sim we just look
        # up the same time index, so emitting one combined line per call site
        # keeps the log small without losing information.
        return self._source.gyro_at(self._clock.now_ms)

    def getMag(self):
        return (0.0, 0.0, 0.0)  # M5StickS3 has no magnetometer

    def close(self):
        try:
            self._log.close()
        except Exception:
            pass
