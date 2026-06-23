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
from .creature_sim.fake_imu import load_imu_source, _CapturingImu
from .creature_sim.fake_speaker import _CapturingSpeaker
from .creature_sim.fake_synth import _CapturingSynth
from .creature_sim.fake_mem import _Mem
from .creature_sim.fake_m5 import _M5
from .llm import load_llm
from .reflection import Creature, ReflectionLoop


class RealtimeClock:
    """Wall-clock with a freeze. Creature-time = wall − time spent frozen.

    Same `now_ms` interface as creature_sim.Clock, so fake_imu/speaker/synth/m5
    reuse it unchanged. While frozen (the body waits for a slow reflection), the
    creature's clock stops, so the IMU/music don't skip and every reflection
    costs exactly `reflection_time` of the creature's own timeline regardless of
    how long the real LLM took.
    """

    def __init__(self):
        self._start = time.monotonic()
        self._frozen_total = 0.0       # seconds of creature-time skipped
        self._frozen_since = None      # monotonic when the current freeze began

    @property
    def now_ms(self) -> float:
        frozen = self._frozen_total
        if self._frozen_since is not None:
            frozen += time.monotonic() - self._frozen_since
        return (time.monotonic() - self._start - frozen) * 1000.0

    @property
    def frozen(self) -> bool:
        return self._frozen_since is not None

    def freeze(self) -> None:
        if self._frozen_since is None:
            self._frozen_since = time.monotonic()

    def unfreeze(self) -> None:
        if self._frozen_since is not None:
            self._frozen_total += time.monotonic() - self._frozen_since
            self._frozen_since = None

    def ticks_ms(self) -> int:
        return int(self.now_ms)

    # creature_sim.Clock has advance() for the virtual case; the real-time
    # variant ignores it (wall clock advances on its own).
    def advance(self, dt_ms: float) -> None:
        pass


# Patch MicroPython-only time.ticks_* onto the real module. sleep_ms/create_task
# reach the instinct via the per-run asyncio shim below, not by patching the
# module — so a creature's tasks are tracked and the freeze can be applied.
def _patch_time(clock) -> None:
    time.ticks_ms   = lambda: int(clock.now_ms)
    time.ticks_diff = lambda a, b: int(a) - int(b)
    time.ticks_add  = lambda a, b: int(a) + int(b)
    time.sleep_ms   = lambda n: None     # synchronous blocking sleep — no-op


class _RTAsyncio:
    """The instinct's `asyncio`: real asyncio, but `sleep_ms` applies the
    reflection freeze and `create_task`/`gather` are tracked so a hot-swap can
    cancel the whole previous instinct (root + the coroutines it spawned)."""

    def __init__(self, spine):
        self._spine = spine

    def sleep_ms(self, n):
        return self._spine._body_sleep_ms(n)

    def sleep(self, seconds):
        return self._spine._body_sleep_ms(float(seconds) * 1000.0)

    def create_task(self, coro):
        t = asyncio.ensure_future(coro)
        self._spine._body_tasks.append(t)
        return t

    def gather(self, *aws, **kw):
        aws = [self.create_task(a) if asyncio.iscoroutine(a) else a for a in aws]
        return asyncio.gather(*aws, **kw)

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _build_scope(*, send, aio, imu, speaker, synth, mem, m5):
    return {
        "__name__":   "__instinct__",
        "__builtins__": __builtins__,
        "send":       send,
        "asyncio":    aio,
        "time":       time,
        "math":       math,
        "struct":     struct,
        "Imu":        imu,
        "Speaker":    speaker,
        "Synth":      synth,
        "Mem":        mem,
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

        # Real-time clock. With --reflection-time (budgeted), each reflection
        # costs the creature exactly that much of its own timeline: the body
        # plays the budget with the current instinct, then the clock FREEZES
        # until the soul replies and the new instinct swaps in. Without it,
        # reflections just fire as the instinct sends and deploy when the LLM
        # returns (the body keeps dancing meanwhile).
        self.clock = RealtimeClock()
        self.budgeted = reflection_time is not None
        self.reflection_time = reflection_time
        self.reflection_time_ms = None if reflection_time is None else reflection_time * 1000.0
        self._reflect_deadline = None            # creature-time the budget ends
        self._deadline_reached = asyncio.Event() # set when the body hits the deadline
        self._reflect_release = asyncio.Event()  # set to release the frozen body
        self._body_tasks: list[asyncio.Task] = []  # the current instinct's tasks
        _patch_time(self.clock)

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
        self.synth = _CapturingSynth(self.clock,
                                     os.path.join(session_dir, "output", "midi_events.jsonl"))
        # One Mem for the whole session: it must survive every instinct hot-swap.
        self.mem = _Mem()
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
                "clock_mode": "budgeted" if self.budgeted else "realtime",
                "reflection_time_s": self.reflection_time,   # None = no freeze budget
                "started_at": time.time(),
            }, f, indent=2)

        self._instinct_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._stopping = False   # suppress auto-refire once we're shutting down

    # ── Loop callbacks ────────────────────────────────────────────────

    def _log(self, msg: str, style: str = None) -> None:
        ts = time.strftime("%H:%M:%S")
        prefix = f"[{style}] " if style else ""
        print(f"{ts}  {prefix}{msg}", file=sys.stderr)

    def _intent(self, intent: str, ts: float) -> None:
        time_str = time.strftime("%H:%M:%S", time.localtime(ts))
        print(f"\n  intent ({time_str}):\n    {intent}\n", file=sys.stderr)

    async def _deploy(self, code: str, version: int) -> None:
        # Only *gate* the swap: don't deploy before the reflection_time budget has
        # elapsed on the creature clock, even if the LLM was fast. The unfreeze /
        # release is done by _maybe_reflect once reflect() returns (so it also
        # covers reflections that change nothing and never call _deploy). While
        # shutting down the body is gone, so don't wait on the budget.
        if self.budgeted and not self._stopping:
            await self._deadline_reached.wait()
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

    async def _body_sleep_ms(self, n):
        """The instinct's sleep: a real sleep, then — in budgeted mode — freeze
        at the reflection deadline until the swap releases the body."""
        await asyncio.sleep(float(n) / 1000.0)
        while (self.budgeted and self._reflect_deadline is not None
               and self.clock.now_ms >= self._reflect_deadline):
            self.clock.freeze()
            self._deadline_reached.set()
            await self._reflect_release.wait()
        # End the clip promptly the moment the creature has danced its full
        # duration (checked every tick, so it doesn't overshoot under load).
        if self.clock.now_ms >= self.duration_ms:
            self._stop_event.set()

    def _start_instinct_task(self, code: str) -> None:
        self._body_tasks = []
        scope = _build_scope(
            send=self._make_send(), aio=_RTAsyncio(self),
            imu=self.imu, speaker=self.speaker, synth=self.synth, mem=self.mem, m5=self.m5,
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
            except Exception:
                tb = traceback.format_exc()
                self.loop.add_crash("CRASH:" + tb.strip().split("\n")[-1])
                if not self._stopping:
                    asyncio.create_task(self._maybe_reflect())

        self._instinct_task = asyncio.create_task(wrapped())

    async def _stop_instinct_task(self) -> None:
        # Cancel the whole instinct — root run() plus every coroutine it spawned
        # (gather children unwind via the root's cancellation) — so a hot-swap
        # never leaves the previous generation's loops running.
        tasks = [t for t in ([self._instinct_task] + self._body_tasks)
                 if t is not None and not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._instinct_task = None
        self._body_tasks = []

    # ── Reflection scheduling ─────────────────────────────────────────

    async def _maybe_reflect(self) -> None:
        if self.loop.needs_reflection():
            if self.budgeted:
                # Open a fresh budget: the body dances reflection_time, then the
                # clock freezes at the deadline.
                self._reflect_deadline = self.clock.now_ms + self.reflection_time_ms
                self._deadline_reached = asyncio.Event()
                self._reflect_release = asyncio.Event()
            await self.loop.reflect()        # LLM + (maybe) _deploy, gated on the deadline
            if self.budgeted:
                # The reflection cost the creature exactly reflection_time: wait
                # for the body to reach the budget deadline (it freezes there),
                # then clear it, unfreeze the clock, and release the body. Done
                # here (not in _deploy) so reflections that change nothing still
                # unfreeze.
                await self._deadline_reached.wait()
                self._reflect_deadline = None
                self.clock.unfreeze()
                self._reflect_release.set()
            if self.loop.needs_reflection() and not self._stopping:
                # Re-fire if new messages/crash arrived during reflection.
                asyncio.create_task(self._maybe_reflect())

    # ── Top-level run ─────────────────────────────────────────────────

    async def run(self) -> None:
        # Boot: start instinct with the current (seed or resumed) code
        self._start_instinct_task(self.loop.current_instinct)
        self._log(f"started instinct v{self.loop.instinct_version}", "dim")

        # Stop when the creature has experienced the full clip. Creature-time
        # excludes reflection freezes, so a budgeted run takes longer in wall
        # time but the creature still dances exactly duration_ms of its timeline.
        warned_exhausted = False
        while not self._stop_event.is_set():
            if self.clock.now_ms >= self.duration_ms:
                break
            # Backup deadline-detector: normally the body freezes itself at the
            # budget deadline, but if the instinct has crashed there is no body
            # left to do it — so the pending deploy would never fire. Detect it
            # here (the run loop always lives) so a crashed creature still
            # recovers promptly.
            if (self.budgeted and self._reflect_deadline is not None
                    and self.clock.now_ms >= self._reflect_deadline):
                self.clock.freeze()
                self._deadline_reached.set()
            if (not warned_exhausted) and self.clock.now_ms > self.imu_source.duration_ms:
                self._log("IMU source exhausted — holding last sample", "dim")
                warned_exhausted = True
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.05)
            except asyncio.TimeoutError:
                pass

        self._log("stopping sim", "dim")
        self._stopping = True
        if self.budgeted:
            # The body is about to stop, so nothing is left to play the budget or
            # hit the deadline — release any reflection waiting on it and thaw the
            # clock so the final drain reflection can't deadlock.
            self._deadline_reached.set()
            self._reflect_release.set()
            self.clock.unfreeze()
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
        self.synth.close()
        self.m5.close()


def main():
    p = argparse.ArgumentParser(description="In-process spine driving a simulated creature.")
    p.add_argument("creature_path",
                   help="A creature directory (typically sim_creatures/<name>).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--imu", help="Path to an IMU stream (.npz or .jsonl).")
    src.add_argument("--from-mocap", metavar="CLIP",
                     help="A baked clip directory (data/mocap/<clip>/), its clip.json, or a "
                          "raw .bvh/.npz; reads imu_<wrist>.jsonl and records it as the run's "
                          "source so the viewer shows the dancer + dense IMU.")
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

    # Resolve the IMU stream. --from-mocap reads the clip's pre-baked
    # imu_<wrist>.jsonl and records provenance (source/wrist/fps) so the viewer
    # can draw the dancer skeleton + dense IMU.
    source = wrist = fps = None
    if args.from_mocap:
        if not os.path.exists(args.from_mocap):
            raise SystemExit(f"mocap clip not found: {args.from_mocap}")
        from .creature_sim.cli import _resolve_mocap_imu
        imu_path = _resolve_mocap_imu(args.from_mocap, args.wrist)
        source, wrist = args.from_mocap, args.wrist
        clip_json = (os.path.join(args.from_mocap, "clip.json")
                     if os.path.isdir(args.from_mocap) else args.from_mocap)
        if os.path.isfile(clip_json) and clip_json.endswith(".json"):
            try:
                with open(clip_json) as f:
                    fps = json.load(f).get("fps")
            except Exception:
                fps = None
        print(f"mocap {os.path.basename(args.from_mocap.rstrip('/'))} ({wrist} wrist) "
              f"→ {imu_path}", file=sys.stderr)
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
        print(f"clock:    real-time, budgeted · each reflection costs the creature "
              f"{args.reflection_time:.2f}s (body plays that, then freezes for a "
              f"slow LLM)", file=sys.stderr)
    else:
        print("clock:    real-time (no freeze; body dances on through reflection)",
              file=sys.stderr)

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
