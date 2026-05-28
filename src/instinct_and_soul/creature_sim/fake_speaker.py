"""Fake Speaker module: capture every call to output/audio_events.jsonl."""
import json
import os


class _CapturingSpeaker:
    def __init__(self, clock, log_path: str):
        self._clock = clock
        self._volume = 128  # M5 default-ish
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w")

    def _emit(self, payload: dict) -> None:
        payload["t"] = self._clock.now_ms
        self._log.write(json.dumps(payload) + "\n")

    def begin(self):
        self._emit({"kind": "begin"})

    def end(self):
        self._emit({"kind": "end"})

    def setVolume(self, v):
        self._volume = int(v)
        self._emit({"kind": "setVolume", "volume": self._volume})

    def tone(self, freq, ms):
        self._emit({
            "kind": "tone",
            "freq": float(freq),
            "ms": float(ms),
            "volume": self._volume,
        })

    def stop(self):
        self._emit({"kind": "stop"})

    def close(self):
        try:
            self._log.close()
        except Exception:
            pass
