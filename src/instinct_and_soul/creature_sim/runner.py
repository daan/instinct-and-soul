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
from .fake_m5 import _M5


class StopSimulation(Exception):
    """Raised by the patched sleep_ms when the virtual clock would exceed --duration."""


def _make_sleep_ms(clock: Clock, duration_ms: float):
    async def sleep_ms(n):
        # If advancing would push past the duration cap, finish at the cap
        # and unwind via StopSimulation so the driver can clean up cleanly.
        n = float(n)
        if clock.now_ms + n > duration_ms:
            clock.advance(max(0.0, duration_ms - clock.now_ms))
            raise StopSimulation()
        clock.advance(n)
        # Yield once so asyncio.create_task(...) tasks (if any) get a turn.
        await asyncio.sleep(0)
    return sleep_ms


def _patch_modules(clock: Clock, duration_ms: float):
    """Monkey-patch uasyncio-only and time.ticks_* into the real stdlib modules.

    These functions don't exist on CPython; adding them doesn't shadow anything.
    Lifetime of the patches is the lifetime of this CLI process — fine for a
    one-shot runner.
    """
    asyncio.sleep_ms = _make_sleep_ms(clock, duration_ms)
    time.ticks_ms   = lambda: int(clock.now_ms)
    time.ticks_diff = lambda a, b: int(a) - int(b)
    time.ticks_add  = lambda a, b: int(a) + int(b)
    time.sleep_ms   = lambda n: clock.advance(float(n))  # synchronous variant


def _build_scope(*, send, imu, speaker, synth, m5):
    return {
        "__name__":   "__instinct__",
        "__builtins__": __builtins__,
        "send":       send,
        "asyncio":    asyncio,
        "time":       time,
        "math":       math,
        "struct":     struct,
        "Imu":        imu,
        "Speaker":    speaker,
        "Synth":      synth,
        "M5":         m5,
    }


def run_sim(
    *,
    instinct_code: str,
    imu_source: NpzImuSource,
    duration_ms: float,
    output_dir: str,
    meta: Optional[dict] = None,
    screen=(135, 240),
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
    m5 = _M5(clock, os.path.join(output_dir, "output", "display_log.jsonl"), screen=screen)

    sent_path = os.path.join(output_dir, "comms", "sent.jsonl")
    sent_log = open(sent_path, "w")

    def captured_send(msg):
        sent_log.write(json.dumps({"t": clock.now_ms, "content": str(msg)}) + "\n")

    _patch_modules(clock, duration_ms)

    scope = _build_scope(send=captured_send, imu=imu, speaker=speaker, synth=synth, m5=m5)

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

    async def driver():
        nonlocal crash_path
        try:
            await instinct_run()
        except StopSimulation:
            pass
        except asyncio.CancelledError:
            pass
        except Exception:
            crash_path = os.path.join(output_dir, "crash.txt")
            with open(crash_path, "w") as f:
                traceback.print_exc(file=f)

    try:
        asyncio.run(driver())
    finally:
        sent_log.close()
        imu.close()
        speaker.close()
        synth.close()
        m5.close()

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
