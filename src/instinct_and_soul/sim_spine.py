"""sim_spine — in-process spine where the device is a fake M5.

Same ReflectionLoop as the real spine drives the soul cycle. The "device" is
local Python: fake_imu reads from an .npz, fake_speaker/fake_m5 capture every
output call to JSONL in the session directory. New instinct code is hot-swapped
into a running asyncio task — no websocket, no second process.

Usage:
  sim-spine sim_creatures/keep_changing --imu sim_in/dance.npz
  sim-spine sim_creatures/keep_changing --imu sim_in/dance.npz --duration 60
  sim-spine sim_creatures/i_want_to_be_touched/0_live_loop --osc     # live device
"""
import argparse
import asyncio
import json
import math
import os
import signal
import struct
import sys
import time
import traceback

from .creature_sim import devices
from .creature_sim import stethoscope
from .creature_sim.fake_imu import load_imu_source, _CapturingImu
from .creature_sim.osc_imu import OSC_PORT, OscImuSource, _LiveImu
from .creature_sim.fake_speaker import _CapturingSpeaker
from .creature_sim.fake_synth import _CapturingSynth
from .creature_sim.fake_mem import _Mem
from .creature_sim.fake_m5 import _M5
from .creature_sim.runner import _neutralize_injected_imports
from .creature_sim.organs import load_organs
from .llm import load_llm
from .reflection import REFLECT_PREFIX, Creature, ReflectionLoop
from .instinct_tools import Calc


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
        self.cap_ms = None             # hard ceiling on creature-time (clip end)

    @property
    def now_ms(self) -> float:
        frozen = self._frozen_total
        if self._frozen_since is not None:
            frozen += time.monotonic() - self._frozen_since
        t = (time.monotonic() - self._start - frozen) * 1000.0
        # Creature-time can never run past the end of the clip. Once the body has
        # danced the full duration the clock pins here, so a slow final reflection
        # draining during shutdown is stamped at the clip end, not minutes later.
        return t if self.cap_ms is None else min(t, self.cap_ms)

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


class _NoButton:
    """Stand-in for the device's explicit channel: there is no hardware here
    and nobody to press it, so it is never pressed. Mirrors the device API
    (main.py's _Button) so a seed written for the board runs unchanged."""

    def pressed(self):
        return False

    def last_s(self):
        return None          # never pressed this wearing



# ── keep(): what an instinct carries across its own rewrites ────────────────
# Module scope, so it outlives every hot-swap — the same lifetime as Mem, but
# by REFERENCE rather than by copy. Mirrors the device runtime (main.py) so a
# seed written for the board behaves identically here.
_kept = {}


def _make_keep(send):
    def keep(name, default):
        """The same object, every instinct that asks for this name."""
        if name not in _kept:
            _kept[name] = default
            return _kept[name]
        obj = _kept[name]
        # Additive only: a rewrite may declare new fields, but keys it no
        # longer declares are reported and NOT deleted — forgetting one in a
        # defaults dict must not destroy accumulated history.
        if isinstance(default, dict) and isinstance(obj, dict):
            added = [k for k in default if k not in obj]
            gone = [k for k in obj if k not in default]
            for k in added:
                obj[k] = default[k]
            if added or gone:
                send("LOG: my ledger changed shape — gained {}, no longer "
                     "declares {}".format(added or "nothing", gone or "nothing"))
        return obj
    return keep



def _build_scope(*, send, reflect, aio, imu, speaker, synth, mem, m5, iv=0):
    return {
        "__name__":   "__instinct__",
        "__builtins__": __builtins__,
        "send":       send,
        "reflect":    reflect,
        # No hardware and nobody to press it — always zero clicks, so a
        # device seed runs here unchanged.
        "Button":     _NoButton(),
        # Which instinct am I? A creature that tells a REWRITE from a re-push
        # compares this against the version in its own ledger (see tilt's
        # three-lifecycles section). The device runtime injects it too.
        "IV":         iv,
        "asyncio":    aio,
        "time":       time,
        "math":       math,
        "struct":     struct,
        "Imu":        imu,
        "Speaker":    speaker,
        "Synth":      synth,
        "Mem":        mem,
        "M5":         m5,
        "keep":       _make_keep(send),
        "Calc":       Calc,
    }


class SimSpine:
    """Glue: fake hardware + ReflectionLoop + hot-swappable instinct task."""

    def __init__(self, creature: Creature, llm, llm_info: dict, *,
                 imu_path: str | None, duration_ms: float | None, resume: bool,
                 source: str | None = None, wrist: str | None = None,
                 fps: float | None = None, reflection_time: float | None = None,
                 max_reflections: int | None = None,
                 osc_port: int | None = None,
                 reflect_every: float | None = None,
                 live_audio: bool = False,
                 no_scope: bool = False):
        self.creature = creature
        # Live mode: the IMU is a real device streaming OSC; there is no clip,
        # so the session is open-ended (--duration is an optional cap) and the
        # human in the loop means the clock can never freeze.
        self.live = osc_port is not None
        self.osc_port = osc_port
        if self.live:
            self.imu_source = None
            self.imu_path = None
            self.duration_ms = duration_ms          # None = run until Ctrl+C
        else:
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
        self.clock.cap_ms = self.duration_ms     # never tick past the clip end (None = no cap)
        self.budgeted = reflection_time is not None
        self.reflection_time = reflection_time
        self.reflection_time_ms = None if reflection_time is None else reflection_time * 1000.0
        # Wall-clock reflection cadence for live co-performance: the soul
        # reflects at most every reflect_every seconds, so a chatty instinct
        # can't burn one LLM call per message while a human is playing. A crash
        # bypasses the throttle (the body must be repaired immediately).
        self.reflect_every_ms = None if reflect_every is None else reflect_every * 1000.0
        self._next_reflect_ms = self.reflect_every_ms or 0.0
        # Phasic attention: send(msg, urgent=True) bypasses the cadence for
        # the rare moment that can't wait. The body owns the guardrails — a
        # hard floor between urgent reflections and a per-session budget — so
        # a soul can't reflect-storm itself broke.
        self._urgent_pending = False
        self._urgent_left = 8
        self._last_urgent_ms = -1e12
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
            max_reflections=max_reflections,
            # Put reflection events on the sim clock so they align with the
            # IMU/audio/display stage on one axis.
            now=lambda: self.clock.now_ms / 1000.0,
        )

        session_dir = self.loop.store.base
        for sub in ("input", "output"):
            os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

        reads_path = os.path.join(session_dir, "input", "imu_reads.jsonl")
        if self.live:
            # Full-rate stream log in the replayable {t, ax..gz} contract: a
            # live session is automatically a clip for later --imu replays.
            self.osc_source = OscImuSource(
                osc_port, self.clock,
                os.path.join(session_dir, "input", "imu_stream.jsonl"),
                mag_log_path=os.path.join(session_dir, "input", "mag_stream.jsonl"))
            self.imu = _LiveImu(self.osc_source, self.clock, reads_path)
        else:
            self.osc_source = None
            self.imu = _CapturingImu(self.imu_source, self.clock, reads_path)
        self.speaker = _CapturingSpeaker(self.clock,
                                         os.path.join(session_dir, "output", "audio_events.jsonl"))
        midi_path = os.path.join(session_dir, "output", "midi_events.jsonl")
        if live_audio:
            from .creature_sim.live_synth import LiveSynth
            self.synth = LiveSynth(self.clock, midi_path)
        else:
            self.synth = _CapturingSynth(self.clock, midi_path)
        # One Mem for the whole session: it must survive every instinct hot-swap.
        self.mem = _Mem()
        # Per-creature organs (organs.py): loaded once per session so organ
        # state survives hot-swaps; attach() is called at every instinct load.
        self._organs_attach = load_organs(creature.path)
        screen = devices.resolve(creature.device)["screen"]
        self.m5 = _M5(self.clock,
                      os.path.join(session_dir, "output", "display_log.jsonl"),
                      screen=screen)

        # Also snapshot the sim's input setup into session.json-adjacent metadata
        with open(os.path.join(session_dir, "sim_meta.json"), "w") as f:
            json.dump({
                "imu_path": None if self.live else os.path.abspath(imu_path),
                "imu_duration_ms": None if self.live else self.imu_source.duration_ms,
                "duration_ms": self.duration_ms,
                "device": creature.device,
                "screen": {"w": screen[0], "h": screen[1]},
                "source": source,          # mocap clip → enables the viewer's dancer + dense IMU
                "wrist": wrist,
                "fps": fps,
                "clock_mode": "live" if self.live else
                              ("budgeted" if self.budgeted else "realtime"),
                "reflection_time_s": self.reflection_time,   # None = no freeze budget
                "osc_port": osc_port,
                "reflect_every_s": reflect_every,
                "live_audio": live_audio,
                "started_at": time.time(),
            }, f, indent=2)

        self._instinct_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._stopping = False   # suppress auto-refire once we're shutting down

        # Stethoscope (ARCHITECTURE.md movement 3): organ events are always
        # recorded to output/organ_events.jsonl; the UDP-OSC live emit is the
        # advisory EEG any listener may attach to.
        self._organ_objs = {}
        stethoscope.attach(self.clock, session_dir,
                           osc_target=None if no_scope else ("127.0.0.1", 9001))
        self._last_probe_t = 0.0

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
        if self._stopping:
            # The drain reflection can deploy after logs are closed — save the
            # version (the store already has it) but don't start a body that
            # would write to closed files and log a phantom crash.
            self._log(f"instinct v{version} saved (session ending — body not restarted)", "cyan")
            return
        self._log(f"hot-swapping to instinct v{version}", "cyan")
        await self._stop_instinct_task()
        self._start_instinct_task(code)

    def _status(self) -> None:
        pass  # nothing to render — info is in log lines

    # ── Instinct task lifecycle ───────────────────────────────────────

    def _make_send(self):
        def send(msg, urgent=False):
            """Journal entry (+ optional warrant). Returns True if an urgent
            warrant was granted (a reflection will fire at the next possible
            moment — immediately, or right after the one in flight), False if
            it was declined (floor or budget; the entry is still journaled and
            will be read at the next rhythm reflection), None for a plain
            journal write."""
            self.loop.add_message(str(msg))
            granted = None
            if urgent:
                granted = (self.reflect_every_ms is not None
                           and self._urgent_left > 0
                           and self.clock.now_ms - self._last_urgent_ms >= 15000.0)
                if granted:
                    self._urgent_left -= 1
                    self._last_urgent_ms = self.clock.now_ms
                    self._urgent_pending = True
                    self._log(f"urgent reflection requested ({self._urgent_left} left)", "dim")
            # Schedule reflection in the background so the instinct doesn't block.
            asyncio.create_task(self._maybe_reflect())
            return granted
        return send

    def _make_reflect(self):
        def reflect(reason):
            """Ask the soul to think, and say why — the same call the device
            runtime provides, so one seed runs in both places. Here it maps
            onto the sim's existing warrant path; the sim's own trigger
            cadence (reflect_every / urgent budget) is unchanged."""
            self.loop.add_message("{} {}".format(REFLECT_PREFIX, str(reason).strip()))
            self.loop.add_reflect_request(str(reason).strip())
            self._urgent_pending = True
            asyncio.create_task(self._maybe_reflect())
        return reflect

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
        # Live sessions with no --duration run until Ctrl+C.
        if self.duration_ms is not None and self.clock.now_ms >= self.duration_ms:
            self._stop_event.set()

    def _start_instinct_task(self, code: str) -> None:
        self._body_tasks = []
        scope = _build_scope(
            send=self._make_send(), reflect=self._make_reflect(), aio=_RTAsyncio(self),
            imu=self.imu, speaker=self.speaker, synth=self.synth, mem=self.mem, m5=self.m5,
            iv=self.loop.instinct_version,
        )
        organ_names = ()
        if self._organs_attach:
            before = set(scope)
            self._organs_attach(scope)
            organ_names = tuple(set(scope) - before)
            self._organ_objs = {k: scope[k] for k in organ_names}
        # The soul may `import` names the sim injects into scope (asyncio shim,
        # Imu/Synth/Mem/Calc/M5, organ senses) — valid on the real M5/MicroPython,
        # but in the sim a real import shadows the shim or ModuleNotFoundError's.
        code = _neutralize_injected_imports(code, organ_names)
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
        # Wall-clock cadence (live mode): messages keep buffering, but the LLM
        # only fires once per reflect_every window. The run loop re-checks the
        # buffer when the window opens, so nothing is lost — just batched.
        # A crashed instinct skips the throttle: the body needs the fix now.
        if (self.reflect_every_ms is not None and not self.loop.last_crashed
                and not self._urgent_pending
                and self.clock.now_ms < self._next_reflect_ms):
            return
        if self.loop.needs_reflection():
            self._urgent_pending = False
            if self.budgeted:
                # Open a fresh budget: the body dances reflection_time, then the
                # clock freezes at the deadline.
                self._reflect_deadline = self.clock.now_ms + self.reflection_time_ms
                self._deadline_reached = asyncio.Event()
                self._reflect_release = asyncio.Event()
            await self.loop.reflect()        # LLM + (maybe) _deploy, gated on the deadline
            if self.reflect_every_ms is not None:
                self._next_reflect_ms = self.clock.now_ms + self.reflect_every_ms
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
        # Live sessions end on Ctrl+C, so make the first one a *graceful* stop
        # (drain the reflection, flush every log); a second Ctrl+C forces.
        try:
            aloop = asyncio.get_running_loop()

            def _sigint():
                self._log("stopping (Ctrl+C again to force)", "bold")
                self._stop_event.set()
                aloop.remove_signal_handler(signal.SIGINT)
            aloop.add_signal_handler(signal.SIGINT, _sigint)
        except (NotImplementedError, RuntimeError):
            pass                              # non-POSIX: default Ctrl+C

        if self.live:
            await self.osc_source.start()
            self._log(f"osc: listening on :{self.osc_port} — waiting for stream…", "dim")

        # Boot: start instinct with the current (seed or resumed) code
        self._start_instinct_task(self.loop.current_instinct)
        self._log(f"started instinct v{self.loop.instinct_version}", "dim")

        # Stop when the creature has experienced the full clip. Creature-time
        # excludes reflection freezes, so a budgeted run takes longer in wall
        # time but the creature still dances exactly duration_ms of its timeline.
        warned_exhausted = False
        stream_up = stream_lost = False
        while not self._stop_event.is_set():
            if self.duration_ms is not None and self.clock.now_ms >= self.duration_ms:
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
            if (not self.live and not warned_exhausted
                    and self.clock.now_ms > self.imu_source.duration_ms):
                self._log("IMU source exhausted — holding last sample", "dim")
                warned_exhausted = True
            if self.live:
                # Announce stream up / lost / resumed transitions (never spam).
                age = self.osc_source.age_s()
                if age is not None and not stream_up:
                    stream_up = True
                    ip = self.osc_source.sender[0] if self.osc_source.sender else "?"
                    self._log(f"osc: stream up from {ip}", "green")
                elif stream_up and age is not None and age > 1.0 and not stream_lost:
                    stream_lost = True
                    self._log("osc: stream lost — holding last sample", "bold red")
                elif stream_lost and age is not None and age < 0.5:
                    stream_lost = False
                    self._log("osc: stream resumed", "green")
            # Stethoscope levels: poll the organs' non-consuming reads ~4x/s
            # and whisper them to any live listener (the record derives these
            # from its own streams — probes are advisory by contract).
            if self.clock.now_ms - self._last_probe_t > 250.0:
                self._last_probe_t = self.clock.now_ms
                for nm, obj in self._organ_objs.items():
                    try:
                        if nm == "Hunger":
                            stethoscope.probe("hunger", obj.level())
                            stethoscope.probe("startle", obj.startle())
                        elif nm == "Motion":
                            stethoscope.probe("fluency", obj.fluency())
                        elif nm == "Handling":
                            stethoscope.probe("alone_s", obj.alone_s())
                        elif nm == "Familiar":
                            stethoscope.probe("gestures_known", float(len(obj.gestures())))
                            g = obj.guess()
                            if g:
                                stethoscope.probe("guess_conf", g[1])
                        elif nm == "Strike":
                            stethoscope.probe("strikes", float(obj.count()))
                    except Exception:
                        pass
            # Cadence tick: messages that buffered during the throttle window
            # get their reflection the moment the window opens, even if the
            # instinct doesn't send again right then.
            if (self.reflect_every_ms is not None and not self.loop.reflecting
                    and self.clock.now_ms >= self._next_reflect_ms
                    and self.loop.needs_reflection()):
                asyncio.create_task(self._maybe_reflect())
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
        stethoscope.detach()
        if self.osc_source is not None:
            self.osc_source.close()
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
    src.add_argument("--osc", nargs="?", const=OSC_PORT, type=int, metavar="PORT",
                     help="LIVE mode: listen for the CoreS3Recorder IMU stream "
                          f"(/imu ,iffffff on UDP, default port {OSC_PORT}). The "
                          "session is open-ended (Ctrl+C to stop), MIDI plays live "
                          "through fluidsynth, and the full stream is logged as a "
                          "replayable clip (input/imu_stream.jsonl).")
    p.add_argument("--wrist", default="left", choices=("left", "right"),
                   help="Wrist to extract when using --from-mocap (default: left).")
    p.add_argument("--duration", type=float, default=None,
                   help="Simulated duration in seconds. Defaults to IMU source length "
                        "(with --osc: no limit).")
    p.add_argument("--llm", default=None, metavar="NAME",
                   help="LLM profile name (overrides default in .config/config.toml).")
    p.add_argument("--reflection-time", type=float, default=None, metavar="SECONDS",
                   help="Model each reflection as taking this many SIMULATED seconds "
                        "(virtual clock — the dance generates fast, only the real LLM "
                        "calls cost wall time). Omit to use the real LLM latency.")
    p.add_argument("--resume", action="store_true",
                   help="Resume from the last session's final experience/instinct")
    p.add_argument("--max-reflections", type=int, default=None, metavar="N",
                   help="Cap the run at N LLM reflections (cost ceiling for pricey "
                        "models). After the cap the body keeps performing with the "
                        "last instinct — no more LLM calls — until the clip ends. "
                        "0 = never reflect (pure seed-instinct run).")
    p.add_argument("--reflect-every", type=float, default=None, metavar="SECONDS",
                   help="Reflect at most once per this many seconds (messages batch "
                        "up in between; crashes bypass it). Defaults to 45 in --osc "
                        "mode, off otherwise.")
    p.add_argument("--no-scope", action="store_true",
                   help="Disable the stethoscope's live UDP-OSC emit (:9001). "
                        "organ_events.jsonl is always recorded regardless.")
    p.add_argument("--live-audio", action=argparse.BooleanOptionalAction, default=None,
                   help="Play MIDI live through fluidsynth while also logging it. "
                        "Default: on with --osc, off otherwise (so replay runs can "
                        "opt in with --live-audio, tests can opt out with "
                        "--no-live-audio).")
    args = p.parse_args()

    live = args.osc is not None
    if live and args.reflection_time is not None:
        raise SystemExit("--reflection-time (freeze budget) makes no sense live: "
                         "you can't freeze the human. Use --reflect-every instead.")
    reflect_every = args.reflect_every
    if live and reflect_every is None:
        reflect_every = 45.0
    live_audio = args.live_audio if args.live_audio is not None else live

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
    elif args.imu:
        imu_path = args.imu
        # Record the stream as the run's source so the tracer can find a skeleton
        # beside it (e.g. an imu_<wrist|hips>.jsonl inside a clip dir).
        source = imu_path
    else:
        imu_path = None            # live: the source is the OSC stream

    duration_ms = None if args.duration is None else args.duration * 1000.0
    if not live:
        sim_source = load_imu_source(imu_path)
        source_s = sim_source.duration_ms / 1000.0
        if args.duration is not None and args.duration > source_s + 1e-6:
            raise SystemExit(
                f"--duration {args.duration:.2f}s exceeds IMU source length ({source_s:.2f}s); "
                f"sim will hold the last sample past that point only if you accept the source length")

    print(f"creature: {creature.path}", file=sys.stderr)
    if live:
        print(f"imu:      live OSC on :{args.osc}  (CoreS3Recorder /imu stream)", file=sys.stderr)
    else:
        print(f"imu:      {imu_path}  ({source_s:.2f}s, {len(sim_source.t_ms)} samples)", file=sys.stderr)
    print(f"llm:      {llm_info.get('llm') or (llm_info.get('api') + '/' + llm_info.get('model', ''))}", file=sys.stderr)
    if live:
        print(f"duration: {'%.2fs' % (duration_ms/1000.0) if duration_ms else 'until Ctrl+C'}",
              file=sys.stderr)
        print(f"clock:    live (wall-clock; reflections at most every "
              f"{reflect_every:.0f}s, body plays on through them)", file=sys.stderr)
        print(f"audio:    {'live (fluidsynth)' if live_audio else 'log only'}", file=sys.stderr)
    else:
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
                   reflection_time=args.reflection_time,
                   max_reflections=args.max_reflections,
                   osc_port=args.osc, reflect_every=reflect_every,
                   live_audio=live_audio, no_scope=args.no_scope)
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
