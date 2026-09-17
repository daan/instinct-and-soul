"""Runs the desk seed against a stubbed body on CPython, at virtual time.

A day, compressed: someone arrives and sits for 50 minutes typing, leaves
for coffee, the desk rises while they are gone, they come back and keep it
(kept); they stand 45 minutes, leave, the desk lowers, they come back and
immediately raise it again (a no); a tap; then the clock jumps to evening
and the day closes with a reflection.

    python creatures/desk/smoke_desk.py

Prints the journal and checks the lines that carry the story. No hardware,
no network, no LLM: this is the seed's logic, nothing else."""
import asyncio as _aio
import math
import os
import random
import sys
import time as _real_time

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
from calc import Calc


# ── the clock ─────────────────────────────────────────────────────────────
class _Clock:
    t = 0.0                                   # virtual seconds since boot
    wall0 = _real_time.mktime((2026, 9, 17, 8, 0, 0, 3, 260, -1))  # 08:00

CLK = _Clock()
_WRAP = 1 << 30


class _time:
    @staticmethod
    def ticks_ms():
        return int(CLK.t * 1000) % _WRAP

    @staticmethod
    def ticks_diff(a, b):
        d = (a - b) % _WRAP
        return d - _WRAP if d >= _WRAP // 2 else d

    @staticmethod
    def localtime():
        return _real_time.localtime(CLK.wall0 + CLK.t)


# ── the world: range, desk, surface, touch ────────────────────────────────
class World:
    def __init__(self):
        self.range_mm = 2000.0
        self.act_amp = 0.0003       # g of accel noise: idle surface
        self.touch = 0
        # the desk
        self.h = 720.0
        self.target = None
        self.hand = None
        self.cmd_t = 0.0
        self.cmd_from = None
        self.result = None
        self.speed = 32.0
        self.v = 0.0
        self.script = []
        self.log = []

    def step(self, dt):
        while self.script and self.script[0][0] <= CLK.t:
            _, label, fn = self.script.pop(0)
            self.log.append("{:>7.0f}s  === {}".format(CLK.t, label))
            fn()
        goal = self.hand if self.hand is not None else self.target
        if goal is None:
            self.v = 0.0
            return
        d = goal - self.h
        step = self.speed * dt
        if abs(d) <= step:
            self.h = goal
            self.v = 0.0
            if self.hand is not None:
                self.hand = None
            else:
                self._finish("arrived")
        else:
            self.h += step if d > 0 else -step
            self.v = self.speed if d > 0 else -self.speed

    def _finish(self, how):
        if self.target is None:
            return
        self.result = (how, self.cmd_from, self.h, CLK.t - self.cmd_t)
        self.target = None

    def at(self, t, label, fn):
        self.script.append((t, label, fn))
        self.script.sort(key=lambda s: s[0])


WORLD = World()
JOURNAL = []


def send(msg):
    JOURNAL.append((CLK.t, str(msg)))


def reflect(reason):
    send("REFLECTION: " + str(reason))


class _asyncio:
    @staticmethod
    async def sleep_ms(ms):
        CLK.t += ms / 1000.0
        WORLD.step(ms / 1000.0)
        await _aio.sleep(0)

    @staticmethod
    async def sleep(s):
        await _asyncio.sleep_ms(s * 1000)


class _M5:
    @staticmethod
    def update():
        pass


class _Imu:
    @staticmethod
    def getAccel():
        a = WORLD.act_amp
        return (random.gauss(0, a), random.gauss(0, a), 1.0 + random.gauss(0, a))


class _Range:
    def mm(self):
        return WORLD.range_mm

    def age_ms(self):
        return 0

    def ok(self):
        return True


class _Desk:
    def height_mm(self):
        return WORLD.h

    def speed_mms(self):
        return WORLD.v

    def moving(self):
        return abs(WORLD.v) > 0.5 or WORLD.target is not None

    def commanded(self):
        return WORLD.target is not None

    def target_mm(self):
        return WORLD.target

    def connected(self):
        return True

    def kind(self):
        return "virtual"

    def age_ms(self):
        return 0

    def move_to(self, mm):
        if 0 < WORLD.range_mm < 1000:          # the body rule, as main.py has it
            send("LOG: refused to move the desk — someone is {:.0f} mm away".format(WORLD.range_mm))
            return False
        WORLD.target = max(620.0, min(1270.0, float(mm)))
        WORLD.cmd_t = CLK.t
        WORLD.cmd_from = WORLD.h
        return True

    def stop(self):
        WORLD._finish("interrupted")

    def result(self):
        r = WORLD.result
        WORLD.result = None
        return r


class _Touch:
    def pressed(self):
        if WORLD.touch:
            WORLD.touch -= 1
            return True
        return False

    def last_s(self):
        return None


# ── the day ───────────────────────────────────────────────────────────────
M = 60.0
def arrive(): WORLD.range_mm = 600.0; WORLD.act_amp = 0.006
def leave(): WORLD.range_mm = 2000.0; WORLD.act_amp = 0.0003
def hand(mm): return lambda: setattr(WORLD, "hand", float(mm))
def tap(): WORLD.touch += 1
def jump(hours): return lambda: setattr(CLK, "t", CLK.t + hours * 3600)

t = 10 * M
WORLD.at(t, "arrives, sits, types", arrive)
t += 50 * M
WORLD.at(t, "leaves for coffee (sat 50m)", leave)
t += 10 * M
WORLD.at(t, "returns — the desk should be up", arrive)
t += 45 * M
WORLD.at(t, "leaves again (stood 45m at my height)", leave)
t += 8 * M
WORLD.at(t, "returns — the desk should be down", arrive)
t += 0.5 * M
WORLD.at(t, "...and raises it right back: a no", hand(1100))
t += 15 * M
WORLD.at(t, "a tap on the screen", tap)
t += 5 * M
WORLD.at(t, "leaves for the day", leave)
t += 2 * M
WORLD.at(t, "the clock jumps to evening", jump(12))
T_END = t + 12 * 3600 + 3 * M


async def main():
    with open(os.path.join(HERE, "seed_instinct.py")) as f:
        code = f.read()
    env = {"send": send, "reflect": reflect, "asyncio": _asyncio, "time": _time,
           "math": math, "struct": None, "M5": _M5, "Imu": _Imu,
           "Speaker": None, "Widgets": None, "mem": {}, "IV": 1,
           "Range": _Range(), "Desk": _Desk(), "Touch": _Touch(),
           "Calc": type("Calc", (), {"OneEuro": Calc.OneEuro, "Running": Calc.Running,
                                     "Onset": Calc.Onset, "Ring": Calc.Ring,
                                     "Gate": Calc.Gate, "Ema": Calc.Ema})}
    exec(code, env)
    task = _aio.create_task(env["run"]())
    while CLK.t < T_END and not task.done():
        await _aio.sleep(0)
    if task.done():
        task.result()          # surface a crash with its traceback
    task.cancel()
    try:
        await task
    except _aio.CancelledError:
        pass


_aio.run(main())

events = [(t, "=== " + l.split("=== ", 1)[1]) for t, l in
          ((float(l.split("s")[0]), l) for l in WORLD.log)]
for t, line in sorted(JOURNAL + events, key=lambda e: e[0]):
    print("{:>7.0f}s  {}".format(t, line))

text = "\n".join(l for _, l in JOURNAL)
CHECKS = [
    "arrived — ",
    "left — sat 50m at 72cm",
    "moving the desk 72cm → 110cm — they sat 50m",
    "back after 10m — desk at 110cm (I put it there; was 72cm)",
    "they kept my height — standing at 110cm",
    "left — stood 45m at 110cm",
    "moving the desk 110cm → 72cm — they stood 45m",
    "they moved the desk 72cm → 110cm while here",
    "a no (#1 in a row)",
    "tap on my screen",
    "day 2026-09-17 closed:",
    "REFLECTION: day closed",
]
missing = [c for c in CHECKS if c not in text]
crashes = [l for _, l in JOURNAL if l.startswith("CRASH")]
print()
if missing or crashes:
    for c in missing:
        print("MISSING:", c)
    for c in crashes:
        print(c)
    sys.exit(1)
print("smoke ok — {} journal lines, {} checks".format(len(JOURNAL), len(CHECKS)))
