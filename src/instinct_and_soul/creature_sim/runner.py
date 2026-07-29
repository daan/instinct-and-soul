"""Drive an instinct.py coroutine under the virtual clock."""
import asyncio
import datetime
import json
import math
import os
import struct
import sys
import time
import traceback
from typing import Optional

from .clock import Clock
from .fake_imu import NpzImuSource, _CapturingImu
from .fake_speaker import _CapturingSpeaker
from .fake_synth import _CapturingSynth
from .fake_mem import _Mem
from .fake_m5 import _M5
from .virtual_clock import VirtualScheduler, VAsyncio, StopSimulation  # noqa: F401
from .organs import load_organs
from ..instinct_tools import Calc


def _patch_time(clock: Clock):
    """Monkey-patch MicroPython-only time.ticks_* onto the real time module.

    These don't exist on CPython; adding them shadows nothing. (sleep_ms /
    create_task are provided to the instinct via the per-run asyncio shim, not
    by patching the module, so concurrent runs don't stomp each other.)
    """
    time.ticks_ms   = lambda: int(clock.now_ms)
    time.ticks_diff = lambda a, b: int(a) - int(b)
    time.ticks_add  = lambda a, b: int(a) + int(b)
    time.sleep_ms   = lambda n: clock.advance(float(n))  # synchronous legacy


def _build_scope(*, send, aio, imu, speaker, synth, mem, m5):
    return {
        "__name__":   "__instinct__",
        "__builtins__": __builtins__,
        "send":       send,
        # No soul in this harness — reflect() is a request to think and there
        # is nobody to think. Journal the reason so the run still records
        # WHEN the creature wanted to reflect, and carry on.
        "reflect":    lambda reason: send("REFLECTION: {}".format(reason)),
        "asyncio":    aio,
        "time":       time,
        "math":       math,
        "struct":     struct,
        "Imu":        imu,
        "Speaker":    speaker,
        "Synth":      synth,
        "Mem":        mem,
        "M5":         m5,
        "Calc":       Calc,
    }


# Names the sim injects into the instinct scope (above) that the soul may instead
# try to `import` — valid on the real M5/MicroPython (real modules with sleep_ms,
# etc.), but in the sim a real import either shadows the injected shim (asyncio)
# or fails with ModuleNotFoundError (Imu/Synth/Mem/Calc/M5). Replace any such
# import with a no-op (line numbers preserved) so the injected object is used.
_INJECTED_NAMES = ("asyncio", "uasyncio", "M5", "Imu", "Synth", "Speaker",
                   "Mem", "Calc", "math", "time", "struct", "reflect")


def _neutralize_injected_imports(code: str, extra: tuple = ()) -> str:
    names = _INJECTED_NAMES + tuple(extra)
    out = []
    for line in code.split("\n"):
        stripped = line.split("#", 1)[0].strip()
        mod = None
        if stripped.startswith("from ") and " import " in stripped:
            mod = stripped[5:].split(" import ", 1)[0].strip().split(".")[0]
        elif stripped.startswith("import "):
            mod = stripped[7:].split(" as ")[0].split(",")[0].strip().split(".")[0]
        if mod in names:
            indent = line[:len(line) - len(line.lstrip())]
            out.append(indent + "pass  # sim: provided in scope, not importable")
        else:
            out.append(line)
    return "\n".join(out)


def run_sim(
    *,
    instinct_code: str,
    imu_source: NpzImuSource,
    duration_ms: float,
    output_dir: str,
    meta: Optional[dict] = None,
    screen=(135, 240),
    creature_dir: Optional[str] = None,
) -> dict:
    """Run instinct.py code in the simulator. Writes captured events to output_dir.

    Writes a self-contained session directory (see docs/SIM.md, Decision 3):
      meta.json, input/imu_reads.jsonl, output/*.jsonl, comms/sent.jsonl.
    `meta` supplies provenance (creature, source clip, wrist, …); the runner adds
    the runtime-derived duration and timestamp.

    Returns a small summary dict (final virtual ms, event counts, output paths).
    """
    os.makedirs(output_dir, exist_ok=True)
    for sub in ("input", "output", "comms"):
        os.makedirs(os.path.join(output_dir, sub), exist_ok=True)

    clock = Clock()
    imu = _CapturingImu(imu_source, clock, os.path.join(output_dir, "input", "imu_reads.jsonl"))
    speaker = _CapturingSpeaker(clock, os.path.join(output_dir, "output", "audio_events.jsonl"))
    synth = _CapturingSynth(clock, os.path.join(output_dir, "output", "midi_events.jsonl"))
    mem = _Mem()
    m5 = _M5(clock, os.path.join(output_dir, "output", "display_log.jsonl"), screen=screen)

    sent_path = os.path.join(output_dir, "comms", "sent.jsonl")
    sent_log = open(sent_path, "w")

    def captured_send(msg, urgent=False):
        # `urgent` is accepted and ignored: the device runtime and sim_spine
        # both take it, and a seed written for either must not blow up here.
        # (It used to TypeError on the instinct's first line — before any
        # await — which hung the run instead of reporting a crash.)
        sent_log.write(json.dumps({"t": clock.now_ms, "content": str(msg)}) + "\n")

    sched = VirtualScheduler(clock, duration_ms)
    _patch_time(clock)

    scope = _build_scope(send=captured_send, aio=VAsyncio(sched),
                         imu=imu, speaker=speaker, synth=synth, mem=mem, m5=m5)

    # Per-creature organs may wrap scope entries or add new senses (organs.py).
    organ_names = ()
    attach = load_organs(creature_dir)
    if attach:
        before = set(scope)
        attach(scope)
        organ_names = tuple(set(scope) - before)

    instinct_code = _neutralize_injected_imports(instinct_code, organ_names)
    try:
        exec(compile(instinct_code, "<instinct>", "exec"), scope)
    except Exception:
        sent_log.close()
        imu.close()
        speaker.close()
        synth.close()
        m5.close()
        traceback.print_exc()
        raise RuntimeError("instinct code failed to load (see traceback above)")

    if "run" not in scope:
        raise RuntimeError("instinct code defines no `run` coroutine")
    instinct_run = scope["run"]

    crash_path = None
    try:
        asyncio.run(sched.run(instinct_run))
    finally:
        sent_log.close()
        imu.close()
        speaker.close()
        synth.close()
        m5.close()

    if sched.crashes:
        crash_path = os.path.join(output_dir, "crash.txt")
        with open(crash_path, "w") as f:
            f.write("\n\n".join(sched.crashes))

    # Session provenance: caller-supplied context + runtime-derived fields.
    meta_out = dict(meta or {})
    meta_out.setdefault("kind", "sim")
    meta_out["duration_ms"] = clock.now_ms
    meta_out["created"] = (datetime.datetime.now(datetime.timezone.utc)
                           .isoformat(timespec="seconds").replace("+00:00", "Z"))
    with open(os.path.join(output_dir, "meta.json"), "w") as f:
        json.dump(meta_out, f, indent=2)

    # Count events for the summary
    def _count(path):
        if not os.path.isfile(path):
            return 0
        with open(path) as f:
            return sum(1 for _ in f)

    return {
        "final_ms": clock.now_ms,
        "imu_reads":    _count(os.path.join(output_dir, "input",  "imu_reads.jsonl")),
        "audio_events": _count(os.path.join(output_dir, "output", "audio_events.jsonl")),
        "midi_events":  _count(os.path.join(output_dir, "output", "midi_events.jsonl")),
        "display_calls":_count(os.path.join(output_dir, "output", "display_log.jsonl")),
        "sent":         _count(os.path.join(output_dir, "comms",  "sent.jsonl")),
        "crashed":      crash_path is not None,
        "output_dir":   output_dir,
    }
