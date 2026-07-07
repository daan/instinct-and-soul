"""Live Synth: capture MIDI to jsonl (like fake_synth) AND sound it now.

For live co-performance sessions (`sim-spine --osc`) the creature's voice must
be audible in the room while it plays. LiveSynth extends _CapturingSynth: the
jsonl log is written by the same code path as every other session (so bake-midi
and the tracer work unchanged), and each event is additionally sent to a
FluidSynth subprocess driven over its command shell (stdin) — the live stand-in
for the SAM2695 GM module, using the same soundfont bake-midi renders with.

No new Python dependencies: fluidsynth is spawned as a subprocess, exactly like
the offline render. `Synth.note(ch, note, ms, vel)` schedules its own note-off
with asyncio.call_later, so timed notes work live too.
"""
import asyncio
import shutil
import subprocess
import sys

from .bake_midi import find_soundfont
from .fake_synth import _CapturingSynth


class FluidSynthOut:
    """A fluidsynth process with its command shell on stdin."""

    def __init__(self, gain: float = 0.6):
        exe = shutil.which("fluidsynth")
        if not exe:
            raise FileNotFoundError(
                "fluidsynth binary not found — install it (brew install "
                "fluidsynth) or run without --live-audio.")
        sf = find_soundfont()
        # -q keeps the shell quiet; stdout still goes somewhere, so route it to
        # devnull or a stalled pipe would eventually block the writes.
        self._proc = subprocess.Popen(
            [exe, "-q", "-g", str(gain), sf],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        print(f"live audio: fluidsynth + {sf}", file=sys.stderr)

    def _cmd(self, line: str) -> None:
        if self._proc.poll() is not None:
            return                      # fluidsynth died; keep the sim alive
        try:
            self._proc.stdin.write((line + "\n").encode())
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def program(self, ch, program):
        self._cmd(f"prog {ch} {program}")

    def note_on(self, ch, note, velocity):
        self._cmd(f"noteon {ch} {note} {velocity}")

    def note_off(self, ch, note):
        self._cmd(f"noteoff {ch} {note}")

    def control_change(self, ch, control, value):
        self._cmd(f"cc {ch} {control} {value}")

    def pitch_bend(self, ch, value):
        self._cmd(f"pitchbend {ch} {value + 8192}")   # shell wants 0..16383

    def close(self):
        try:
            if self._proc.poll() is None:
                self._proc.stdin.write(b"quit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=2.0)
        except Exception:
            pass
        finally:
            if self._proc.poll() is None:
                self._proc.kill()


class LiveSynth(_CapturingSynth):
    """_CapturingSynth that also plays each event through FluidSynthOut."""

    def __init__(self, clock, log_path: str, gain: float = 0.6):
        super().__init__(clock, log_path)
        self._out = FluidSynthOut(gain=gain)

    def _emit(self, payload: dict) -> None:
        super()._emit(payload)          # jsonl log — identical to offline runs
        kind = payload["kind"]
        if kind == "program":
            self._out.program(payload["ch"], payload["program"])
        elif kind == "note_on":
            self._out.note_on(payload["ch"], payload["note"], payload["velocity"])
        elif kind == "note_off":
            self._out.note_off(payload["ch"], payload["note"])
        elif kind == "control_change":
            self._out.control_change(payload["ch"], payload["control"], payload["value"])
        elif kind == "pitch_bend":
            self._out.pitch_bend(payload["ch"], payload["value"])
        elif kind == "note":
            ch, note = payload["ch"], payload["note"]
            self._out.note_on(ch, note, payload["velocity"])
            try:
                asyncio.get_running_loop().call_later(
                    payload["ms"] / 1000.0, self._out.note_off, ch, note)
            except RuntimeError:
                # No running loop (shouldn't happen mid-sim) — off immediately.
                self._out.note_off(ch, note)

    def close(self):
        super().close()
        self._out.close()
