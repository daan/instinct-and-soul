"""Discrete-event virtual clock for the simulator.

The naive virtual clock advanced time by `n` on every `sleep_ms(n)` call. That is
correct for a single instinct loop, but breaks when an instinct runs several
coroutines concurrently (e.g. a sensor loop + a music loop): each coroutine's
sleep adds to the clock, so virtual time races ahead — N concurrent loops burn
time N× too fast, and the run hits its duration cap almost immediately.

This scheduler models virtual time as discrete events instead. `sleep_ms(n)`
*parks* the caller until the clock reaches now+n; the driver advances the clock
to the earliest pending wake-up only once every live instinct task is parked.
Concurrent sleeps therefore overlap on one shared timeline, exactly like real
time.

Only coroutines the instinct itself spawns are tracked — the instinct's scope
gets a small `asyncio` shim whose `create_task`/`sleep`/`sleep_ms` route here,
while the spine's own tasks (reflection, the LLM call) use the real asyncio and
stay invisible to the clock.
"""
import asyncio
import heapq
import traceback


class StopSimulation(Exception):
    """Raised inside a parked sleep_ms once the duration cap is reached."""


class VirtualScheduler:
    def __init__(self, clock, duration_ms: float):
        self.clock = clock
        self.duration_ms = float(duration_ms)
        self._heap = []            # (deadline_ms, seq, future)
        self._seq = 0
        self._live = 0             # tracked instinct tasks alive
        self._running = 0          # tracked tasks NOT parked in sleep_ms
        self._settled = asyncio.Event()      # set when every live task is parked
        self._stopped = False
        # Reflection-freeze gate: while a pause point is set, the driver advances
        # virtual time up to it, then waits for resume() before going further.
        self._pause_at = None
        self._resume = asyncio.Event()
        self._resume.set()
        self._tasks = []
        self.crashes = []          # traceback strings from any task that threw
        self.on_crash = None       # optional callback(tb_str) when a task throws
        self.done_event = asyncio.Event()   # set when the sim ends (cap or stop())
        self._has_tasks = asyncio.Event()   # set while any instinct task is live

    # ── task tracking ──────────────────────────────────────────────────────
    def spawn(self, coro):
        """create_task replacement that keeps the live/running counts honest."""
        self._live += 1
        self._running += 1
        self._settled.clear()
        self._has_tasks.set()

        async def _wrapped():
            try:
                return await coro
            except (StopSimulation, asyncio.CancelledError):
                pass
            except Exception:
                tb = traceback.format_exc()
                self.crashes.append(tb)
                if self.on_crash is not None:
                    self.on_crash(tb)
            finally:
                self._live -= 1
                self._running -= 1
                if self._live <= 0:
                    self._has_tasks.clear()
                self._check_settled()
        t = asyncio.ensure_future(_wrapped())
        self._tasks.append(t)
        return t

    async def cancel_all(self):
        """Cancel every live instinct task (used on hot-swap) and reap them."""
        tasks = [t for t in self._tasks if not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:
                pass
        self._tasks = [t for t in self._tasks if not t.done()]

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._wake_all()
        self.done_event.set()

    def _check_settled(self):
        if self._live > 0 and self._running <= 0:
            self._settled.set()

    # ── the sleep primitive ────────────────────────────────────────────────
    async def sleep_ms(self, n):
        if self._stopped:
            raise StopSimulation()
        n = float(n)
        if n <= 0:
            # a pure yield — no virtual time passes, don't park on the heap
            await asyncio.sleep(0)
            return
        deadline = self.clock.now_ms + n
        fut = asyncio.get_event_loop().create_future()
        self._seq += 1
        heapq.heappush(self._heap, (deadline, self._seq, fut))
        self._running -= 1            # this task is now parked
        self._check_settled()
        try:
            await fut
        finally:
            self._running += 1        # woke up, running again
            self._settled.clear()
        if self._stopped:
            raise StopSimulation()

    async def sleep(self, seconds):
        await self.sleep_ms(float(seconds) * 1000.0)

    # ── reflection-freeze gate ─────────────────────────────────────────────
    def pause_advance_at(self, t_ms: float):
        """Let virtual time reach t_ms, then freeze until resume()."""
        self._pause_at = float(t_ms)
        self._resume.clear()

    def resume(self):
        self._pause_at = None
        self._resume.set()

    # ── the driver ─────────────────────────────────────────────────────────
    async def drive(self, stop_when_idle: bool = True):
        """Advance virtual time. With stop_when_idle, return when no task is left
        (single-shot creature-sim); otherwise wait for new tasks (sim-spine, whose
        instinct is hot-swapped — tasks come and go across the run)."""
        while not self._stopped:
            if self._live <= 0:
                if stop_when_idle:
                    break
                await self._has_tasks.wait()     # wait for the next instinct
                continue
            await self._settled.wait()           # all live tasks parked
            if self._stopped:
                break
            if self._live <= 0:
                continue
            if not self._heap:
                if stop_when_idle:
                    break
                self._settled.clear()
                await asyncio.sleep(0)
                continue
            deadline = self._heap[0][0]
            # honour a reflection freeze
            if self._pause_at is not None and deadline > self._pause_at:
                if self.clock.now_ms < self._pause_at:
                    self.clock.now_ms = self._pause_at
                await self._resume.wait()
                continue
            if deadline > self.duration_ms:
                self.clock.now_ms = self.duration_ms
                self.stop()                      # tasks raise StopSimulation
                break
            self.clock.now_ms = deadline
            self._settled.clear()
            self._wake_due()
            await asyncio.sleep(0)               # let woken tasks run + re-park

    async def run(self, root_factory):
        """Single-shot: spawn root_factory() (-> coroutine), drive to completion."""
        self.spawn(root_factory())
        try:
            await self.drive(stop_when_idle=True)
        finally:
            self.stop()
            await self.cancel_all()

    def _wake_due(self):
        now = self.clock.now_ms
        while self._heap and self._heap[0][0] <= now:
            _, _, fut = heapq.heappop(self._heap)
            if not fut.done():
                fut.set_result(None)

    def _wake_all(self):
        while self._heap:
            _, _, fut = heapq.heappop(self._heap)
            if not fut.done():
                fut.set_result(None)


class VAsyncio:
    """An `asyncio`-like shim for the instinct scope: create_task/sleep/sleep_ms
    route through the scheduler (virtual time, tracked); everything else falls
    through to the real asyncio module."""

    def __init__(self, sched: VirtualScheduler):
        self._sched = sched

    def create_task(self, coro):
        return self._sched.spawn(coro)

    def sleep_ms(self, n):
        return self._sched.sleep_ms(n)

    def sleep(self, seconds):
        return self._sched.sleep(seconds)

    def gather(self, *coros_or_futures, **kw):
        # Track any bare coroutines so their sleep_ms calls stay accounted for.
        wrapped = [self._sched.spawn(c) if asyncio.iscoroutine(c) else c
                   for c in coros_or_futures]
        return asyncio.gather(*wrapped, **kw)

    def __getattr__(self, name):
        return getattr(asyncio, name)
