"""sim_spine — in-process spine where the device is a fake M5.

Same ReflectionLoop as the real spine drives the soul cycle. The "device" is
local Python: fake_imu reads from an .npz, fake_speaker/fake_m5 capture every
output call to JSONL in the session directory. New instinct code is hot-swapped
into a running asyncio task — no websocket, no second process.

Usage:
  sim-spine sim_creatures/keep_changing --imu sim_in/dance.npz
  sim-spine sim_creatures/keep_changing --imu sim_in/dance.npz --duration 60
"""
import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time
import traceback

from .creature_sim import devices
from .creature_sim.clock import Clock
from .creature_sim.runner import StopSimulation
from .creature_sim.fake_imu import load_imu_source, _CapturingImu
from .creature_sim.fake_speaker import _CapturingSpeaker
from .creature_sim.fake_m5 import _M5
from .llm import load_llm
from .reflection import Creature, ReflectionLoop


class RealtimeClock:
    """Drop-in for creature_sim.Clock that tracks wall-clock instead of virtual.

    Same `now_ms` interface as Clock so the existing fake_imu / fake_speaker /
    fake_m5 modules can be reused unchanged.
    """

    def __init__(self):
        self._start = time.monotonic()

    @property
    def now_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000.0

    def ticks_ms(self) -> int:
        return int(self.now_ms)

    # creature_sim.Clock has advance() for the virtual case; the real-time
    # variant ignores it (wall clock advances on its own).
    def advance(self, dt_ms: float) -> None:
        pass


# Real-time replacements for uasyncio-only / micropython-only APIs.
def _install_realtime_shims(clock: RealtimeClock) -> None:
    async def sleep_ms(n):
        await asyncio.sleep(float(n) / 1000.0)
    asyncio.sleep_ms = sleep_ms
    time.ticks_ms   = lambda: int(clock.now_ms)
    time.ticks_diff = lambda a, b: int(a) - int(b)
    time.ticks_add  = lambda a, b: int(a) + int(b)


def _build_scope(*, send, imu, speaker, m5):
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
        "M5":         m5,
    }


class SimSpine:
    """Glue: fake hardware + ReflectionLoop + hot-swappable instinct task."""

    def __init__(self, creature: Creature, llm, llm_info: dict, *,
                 imu_path: str, duration_ms: float | None, resume: bool,
                 source: str | None = None, wrist: str | None = None,
                 fps: float | None = None, reflection_time: float | None = None):
        self.creature = creature
        self.imu_source = load_imu_source(imu_path)
        self.imu_path = imu_path
        if duration_ms is None:
            self.duration_ms = self.imu_source.duration_ms
        else:
            self.duration_ms = duration_ms

        # Clock mode. Default: real-time (latency == real LLM time). With a
        # reflection_time: virtual time — the dance generates fast and each
        # reflection occupies a fixed `reflection_time` of simulated time.
        self.virtual = reflection_time is not None
        self.reflection_time = reflection_time
        self.reflection_time_ms = None if reflection_time is None else reflection_time * 1000.0
        self.clock = Clock() if self.virtual else RealtimeClock()
        # Reflection-budget gate (virtual mode): the body advances at most
        # reflection_time of virtual time per reflection, then blocks here.
        self._reflect_deadline = None
        self._reflect_done = asyncio.Event()
        # Patch uasyncio/micropython-only APIs (asyncio.sleep_ms, time.ticks_*)
        # onto the stdlib modules BEFORE any instinct runs.
        if self.virtual:
            self._install_virtual_shims()
        else:
            _install_realtime_shims(self.clock)

        self.loop = ReflectionLoop(
            creature, llm,
            llm_info=llm_info,
            resume=resume,
            provenance="simulator",
            on_log=self._log,
            on_intent=self._intent,
            on_instinct_deploy=self._deploy,
            on_status_change=self._status,
            # Put reflection events on the sim clock so they align with the
            # IMU/audio/display stage on one axis.
            now=lambda: self.clock.now_ms / 1000.0,
        )

        session_dir = self.loop.store.base
        for sub in ("input", "output"):
            os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

        self.imu = _CapturingImu(self.imu_source, self.clock,
                                 os.path.join(session_dir, "input", "imu_reads.jsonl"))
        self.speaker = _CapturingSpeaker(self.clock,
                                         os.path.join(session_dir, "output", "audio_events.jsonl"))
        screen = devices.resolve(creature.device)["screen"]
        self.m5 = _M5(self.clock,
                      os.path.join(session_dir, "output", "display_log.jsonl"),
                      screen=screen)

        # Also snapshot the sim's input setup into session.json-adjacent metadata
        with open(os.path.join(session_dir, "sim_meta.json"), "w") as f:
            json.dump({
                "imu_path": os.path.abspath(imu_path),
                "imu_duration_ms": self.imu_source.duration_ms,
                "duration_ms": self.duration_ms,
                "device": creature.device,
                "screen": {"w": screen[0], "h": screen[1]},
                "source": source,          # mocap clip → enables the viewer's dancer + dense IMU
                "wrist": wrist,
                "fps": fps,
                "clock_mode": "virtual" if self.virtual else "real",
                "reflection_time_s": self.reflection_time,   # None in real mode
                "started_at": time.time(),
            }, f, indent=2)

        self._instinct_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._stopping = False   # suppress auto-refire once we're shutting down

    def _install_virtual_shims(self) -> None:
        """Virtual sleep_ms: advance the clock instantly (no wall delay), stop at
        the duration cap, and block at the per-reflection budget so the body
        dances exactly `reflection_time` of virtual time per reflection."""
        clock = self.clock

        async def sleep_ms(n):
            n = float(n)
            if clock.now_ms + n > self.duration_ms:
                clock.advance(max(0.0, self.duration_ms - clock.now_ms))
                raise StopSimulation()
            clock.advance(n)
            if self._reflect_deadline is not None and clock.now_ms >= self._reflect_deadline:
                await self._reflect_done.wait()   # wait (real time) for the soul
            else:
                await asyncio.sleep(0)            # yield so reflection tasks run

        asyncio.sleep_ms = sleep_ms
        time.ticks_ms   = lambda: int(clock.now_ms)
        time.ticks_diff = lambda a, b: int(a) - int(b)
        time.ticks_add  = lambda a, b: int(a) + int(b)
        time.sleep_ms   = lambda n: clock.advance(float(n))

    # ── Loop callbacks ────────────────────────────────────────────────

    def _log(self, msg: str, style: str = None) -> None:
        ts = time.strftime("%H:%M:%S")
        prefix = f"[{style}] " if style else ""
        print(f"{ts}  {prefix}{msg}", file=sys.stderr)

    def _intent(self, intent: str, ts: float) -> None:
        time_str = time.strftime("%H:%M:%S", time.localtime(ts))
        print(f"\n  intent ({time_str}):\n    {intent}\n", file=sys.stderr)

    async def _deploy(self, code: str, version: int) -> None:
        self._log(f"hot-swapping to instinct v{version}", "cyan")
        await self._stop_instinct_task()
        self._start_instinct_task(code)

    def _status(self) -> None:
        pass  # nothing to render — info is in log lines

    # ── Instinct task lifecycle ───────────────────────────────────────

    def _make_send(self):
        def send(msg):
            self.loop.add_message(str(msg))
            # Schedule reflection in the background so the instinct doesn't block.
            asyncio.create_task(self._maybe_reflect())
        return send

    def _start_instinct_task(self, code: str) -> None:
        scope = _build_scope(
            send=self._make_send(),
            imu=self.imu, speaker=self.speaker, m5=self.m5,
        )
        try:
            exec(compile(code, f"<instinct-v{self.loop.instinct_version}>", "exec"), scope)
        except Exception:
            traceback.print_exc()
            self.loop.add_crash("CRASH:" + repr(sys.exc_info()[1]))
            asyncio.create_task(self._maybe_reflect())
            return
        if "run" not in scope:
            self._log("instinct defines no run() coroutine", "bold red")
            return

        async def wrapped():
            try:
                await scope["run"]()
            except asyncio.CancelledError:
                pass
            except StopSimulation:
                self._stop_event.set()   # virtual duration cap reached — clean stop
            except Exception:
                tb = traceback.format_exc()
                self.loop.add_crash("CRASH:" + tb.strip().split("\n")[-1])
                asyncio.create_task(self._maybe_reflect())

        self._instinct_task = asyncio.create_task(wrapped())

    async def _stop_instinct_task(self) -> None:
        t = self._instinct_task
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._instinct_task = None

    # ── Reflection scheduling ─────────────────────────────────────────

    async def _maybe_reflect(self) -> None:
        if self.loop.needs_reflection():
            if self.virtual:
                # Open a virtual-time budget: the body may dance reflection_time
                # of virtual time before it blocks waiting for this reflection.
                self._reflect_deadline = self.clock.now_ms + self.reflection_time_ms
                self._reflect_done.clear()
            await self.loop.reflect()
            if self.virtual:
                self._reflect_deadline = None
                self._reflect_done.set()     # unblock the body; new instinct is live
            if self.loop.needs_reflection() and not self._stopping:
                # Re-fire if new messages/crash arrived during reflection.
                asyncio.create_task(self._maybe_reflect())

    # ── Top-level run ─────────────────────────────────────────────────

    async def run(self) -> None:
        # Boot: start instinct with the current (seed or resumed) code
        self._start_instinct_task(self.loop.current_instinct)
        self._log(f"started instinct v{self.loop.instinct_version}", "dim")

        if self.virtual:
            # Virtual clock: the body generates the dance fast and blocks only on
            # the reflection budget; it raises StopSimulation at the duration cap,
            # which wrapped() turns into _stop_event. Just wait for that.
            await self._stop_event.wait()
        else:
            # Real-time clock: stop at the wall-clock deadline.
            deadline = time.monotonic() + self.duration_ms / 1000.0
            warned_exhausted = False
            while not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if (not warned_exhausted) and self.clock.now_ms > self.imu_source.duration_ms:
                    self._log("IMU source exhausted — holding last sample", "dim")
                    warned_exhausted = True
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=min(remaining, 0.5))
                except asyncio.TimeoutError:
                    pass

        self._log("stopping sim", "dim")
        self._stopping = True
        await self._stop_instinct_task()
        # An in-flight reflection was already paid for — let it finish and save
        # rather than discarding it at the deadline (bounded wait).
        if self.loop.reflecting:
            self._log("finishing in-flight reflection…", "dim")
            waited = 0.0
            while self.loop.reflecting and waited < 90.0:
                await asyncio.sleep(0.2)
                waited += 0.2
        # Drain any messages buffered but never reflected on.
        if self.loop.needs_reflection():
            await self.loop.reflect()

        self.imu.close()
        self.speaker.close()
        self.m5.close()


def main():
    p = argparse.ArgumentParser(description="In-process spine driving a simulated creature.")
    p.add_argument("creature_path",
                   help="A creature directory (typically sim_creatures/<name>).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--imu", help="Path to an IMU stream (.npz or .jsonl, e.g. from bake-imu).")
    src.add_argument("--from-mocap", metavar="CLIP",
                     help="A baked mocap clip JSON; bridged to IMU on the fly and recorded "
                          "as the run's source so the viewer shows the dancer + dense IMU.")
    p.add_argument("--wrist", default="left", choices=("left", "right"),
                   help="Wrist to extract when using --from-mocap (default: left).")
    p.add_argument("--duration", type=float, default=None,
                   help="Simulated duration in seconds. Defaults to IMU source length.")
    p.add_argument("--llm", default=None, metavar="NAME",
                   help="LLM profile name (overrides default in .config/config.toml).")
    p.add_argument("--reflection-time", type=float, default=None, metavar="SECONDS",
                   help="Model each reflection as taking this many SIMULATED seconds "
                        "(virtual clock — the dance generates fast, only the real LLM "
                        "calls cost wall time). Omit to use the real LLM latency.")
    p.add_argument("--resume", action="store_true",
                   help="Resume from the last session's final experience/instinct")
    args = p.parse_args()

    creature = Creature(args.creature_path)
    llm, llm_info = load_llm(args.llm)

    # Resolve the IMU stream. --from-mocap bridges the clip and records provenance
    # (source/wrist/fps) so the viewer can draw the dancer skeleton + dense IMU.
    source = wrist = fps = None
    if args.from_mocap:
        if not os.path.isfile(args.from_mocap):
            raise SystemExit(f"mocap clip not found: {args.from_mocap}")
        from .creature_sim.bridge import bake
        imu_path = bake(args.from_mocap, args.wrist)
        source, wrist = args.from_mocap, args.wrist
        with open(args.from_mocap) as f:
            fps = json.load(f).get("fps")
        print(f"bridged {os.path.basename(args.from_mocap)} ({wrist} wrist) → {imu_path}",
              file=sys.stderr)
    else:
        imu_path = args.imu

    sim_source = load_imu_source(imu_path)
    source_s = sim_source.duration_ms / 1000.0
    if args.duration is not None and args.duration > source_s + 1e-6:
        raise SystemExit(
            f"--duration {args.duration:.2f}s exceeds IMU source length ({source_s:.2f}s); "
            f"sim will hold the last sample past that point only if you accept the source length")
    duration_ms = None if args.duration is None else args.duration * 1000.0

    print(f"creature: {creature.path}", file=sys.stderr)
    print(f"imu:      {imu_path}  ({source_s:.2f}s, {len(sim_source.t_ms)} samples)", file=sys.stderr)
    print(f"llm:      {llm_info.get('llm') or (llm_info.get('api') + '/' + llm_info.get('model', ''))}", file=sys.stderr)
    print(f"duration: {(duration_ms or sim_source.duration_ms)/1000.0:.2f}s", file=sys.stderr)
    if args.reflection_time is not None:
        print(f"clock:    virtual · reflection_time={args.reflection_time:.2f}s "
              f"(wall time still waits for each real LLM call)", file=sys.stderr)
    else:
        print("clock:    real-time (reflection length = real LLM latency)", file=sys.stderr)

    sim = SimSpine(creature, llm, llm_info,
                   imu_path=imu_path, duration_ms=duration_ms, resume=args.resume,
                   source=source, wrist=wrist, fps=fps,
                   reflection_time=args.reflection_time)
    print(f"session:  {sim.loop.store.base}", file=sys.stderr)
    if sim.loop.resumed_from:
        print(f"resumed from: {sim.loop.resumed_from}", file=sys.stderr)
    print("(Ctrl+C to stop)", file=sys.stderr)

    try:
        asyncio.run(sim.run())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)


if __name__ == "__main__":
    main()
