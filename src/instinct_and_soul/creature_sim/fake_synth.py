"""Fake Synth module: capture every MIDI command to output/midi_events.jsonl.

`Synth` is the device-side audio abstraction that sits beside `Speaker` (the
M5's tone beeper). On hardware it will drive a SAM2695 GM module over serial;
in the simulator it just logs the MIDI commands, which `bake-midi` later renders
to a WAV through FluidSynth (mirroring Speaker.tone -> audio_events -> bake-audio).

A creature can use `Speaker`, `Synth`, or both — the system prompt decides. The
API is MIDI-native so the captured stream maps 1:1 onto mido messages:

    Synth.program(ch, program)            # program (instrument) change
    Synth.note_on(ch, note, velocity)     # raw note on
    Synth.note_off(ch, note)              # raw note off
    Synth.note(ch, note, ms, velocity)    # timed note (on now, off after ms)
    Synth.control_change(ch, control, value)

Channel 9 is the GM drum channel. `note(...)` is the convenience analog of
Speaker.tone(freq, ms): it records a single duration-bearing event that bake-midi
expands into an on/off pair, so an instinct can fire a note without juggling the
off itself.
"""
import json
import os


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


class _CapturingSynth:
    def __init__(self, clock, log_path: str):
        self._clock = clock
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w")

    def _emit(self, payload: dict) -> None:
        payload["t"] = self._clock.now_ms
        self._log.write(json.dumps(payload) + "\n")

    def program(self, ch, program):
        self._emit({"kind": "program", "ch": _clamp(ch, 0, 15),
                    "program": _clamp(program, 0, 127)})

    def note_on(self, ch, note, velocity=80):
        self._emit({"kind": "note_on", "ch": _clamp(ch, 0, 15),
                    "note": _clamp(note, 0, 127), "velocity": _clamp(velocity, 0, 127)})

    def note_off(self, ch, note, velocity=0):
        self._emit({"kind": "note_off", "ch": _clamp(ch, 0, 15),
                    "note": _clamp(note, 0, 127), "velocity": _clamp(velocity, 0, 127)})

    def note(self, ch, note, ms, velocity=80):
        self._emit({"kind": "note", "ch": _clamp(ch, 0, 15),
                    "note": _clamp(note, 0, 127), "ms": float(ms),
                    "velocity": _clamp(velocity, 0, 127)})

    def control_change(self, ch, control, value):
        self._emit({"kind": "control_change", "ch": _clamp(ch, 0, 15),
                    "control": _clamp(control, 0, 127), "value": _clamp(value, 0, 127)})

    def close(self):
        try:
            self._log.close()
        except Exception:
            pass
