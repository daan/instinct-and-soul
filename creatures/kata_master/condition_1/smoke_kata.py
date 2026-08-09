"""Runs the kata seed against stubbed hardware on CPython: pickup, a held
pose, three cuts landing on three faces, a rest that closes the phrase and
draws the echo, then a put-down that ends the run with a reflection."""
import asyncio as _aio, math, time as _time, types, random
random.seed(3)

from calc import Calc
from kata_sense import KataSense

class Clock:
    def __init__(self): self.t = 0.0
CLK = Clock()

class _M5:
    @staticmethod
    def update(): pass

SYN = []   # (t, op, ch, a, b)
class _Synth:
    @staticmethod
    def program(ch, p): SYN.append((round(CLK.t,3), "prog", ch, p, None))
    @staticmethod
    def note(ch, n, ms, velocity=80): SYN.append((round(CLK.t,3), "note", ch, n, velocity))
    @staticmethod
    def note_on(ch, n, velocity=80): SYN.append((round(CLK.t,3), "on", ch, n, velocity))
    @staticmethod
    def note_off(ch, n, velocity=0): SYN.append((round(CLK.t,3), "off", ch, n, velocity))
    @staticmethod
    def control_change(ch, c, v): SYN.append((round(CLK.t,3), "cc", ch, c, v))
    @staticmethod
    def pitch_bend(ch, v): SYN.append((round(CLK.t,3), "bend", ch, v, None))

class _Ear:
    @staticmethod
    def recent(n=None, ch=None): return []
    @staticmethod
    def cc_total(): return 0

# ── the practice, as (until_s, rot_dps, gravity) segments ────────────────
Z, XM, YP, ZM = (0,0,1.0), (-1.0,0,0), (0,1.0,0), (0,0,-1.0)
SCRIPT = []
def plan():
    t = 0.0
    def seg(dur, rot, g):
        nonlocal t; t += dur; SCRIPT.append((t, rot, g))
    seg(2.0, 0.1, Z)          # on the table
    seg(1.5, 8.0, Z)          # picked up, handled
    seg(1.2, 1.5, Z)          # held still: a pose, palm down — arms
    def cut(g_to):            # strike, follow-through, hover
        seg(0.12, 1800, g_to)
        seg(0.30, 270, g_to)
        seg(0.90, 150, g_to)
    cut(XM)                   # cut 1 -> fingers up (X-)
    cut(YP)                   # cut 2 -> blade (Y+)
    cut(ZM)                   # cut 3 -> palm up (Z-)
    seg(3.5, 1.5, ZM)         # rest: phrase closes at 2 s, echo plays
    seg(12.0, 0.1, ZM)        # set down: put-down after 6 s -> reflect
plan()

class _Imu:
    @staticmethod
    def _row():
        for until, rot, g in SCRIPT:
            if CLK.t < until:
                return rot, g
        return 0.1, ZM
    @staticmethod
    def getAccel():
        r, g = _Imu._row(); return g
    @staticmethod
    def getGyro():
        r, g = _Imu._row()
        r += random.uniform(-0.05, 0.05) * r
        return (r/1.8, r/1.8, r/1.8)

class _time_mod:
    @staticmethod
    def ticks_ms(): return int(CLK.t * 1000)
    @staticmethod
    def localtime(): return (1970,1,1,0,0,0,0,0)

class _Sleep:
    def __init__(self, ms): self.ms = ms
    def __await__(self):
        CLK.t += self.ms / 1000.0
        yield
class _asyncio_mod:
    @staticmethod
    def sleep_ms(ms): return _Sleep(ms)

JOURNAL, REFLECTS = [], []
def send(m, urgent=False):
    JOURNAL.append((round(CLK.t,1), m)); print("  LOG {:6.1f}  {}".format(CLK.t, m))
class StopInstinct(Exception): pass
def reflect(m):
    REFLECTS.append((round(CLK.t,1), m)); print("  RFL {:6.1f}  {}".format(CLK.t, m))
    raise StopInstinct()

MEM = {}

def build_env():
    return dict(asyncio=_asyncio_mod, math=math, time=_time_mod, M5=_M5,
                Imu=_Imu, Synth=_Synth, Ear=_Ear,
                Calc=Calc, KataSense=KataSense, mem=MEM, send=send, reflect=reflect)

def load():
    src = open("seed_instinct.py").read()
    env = build_env()
    exec(compile(src, "seed_instinct.py", "exec"), env)
    return env["run"]

async def wear(run, until):
    try:
        task = run()
        while CLK.t < until:
            try:
                task.send(None)
            except StopIteration:
                break
    except StopInstinct:
        print("  -- reflection summoned; instinct stops --")

print("== a practice run ==")
_aio.get_event_loop().run_until_complete(wear(load(), 60.0))

print("\n== checks ==")
texts = [m for _, m in JOURNAL]
def has(f): return any(f in m for m in texts)
assert has("picked up after"), "no pickup"
assert has("THEM: X- Y+ Z-"), "phrase wrong: " + str([m for m in texts if "THEM" in m])
assert has("ME: echo X- Y+ Z-"), "no echo line"
assert has("new X-)Y+ Y+)Z-"), "analysis missing: " + str([m for m in texts if "THEM" in m])
assert REFLECTS and "put down after" in REFLECTS[0][1], REFLECTS
assert "3 cuts (3 from a pose)" in REFLECTS[0][1], REFLECTS[0][1]
assert "1 phrases" in REFLECTS[0][1] and "1 answered" in REFLECTS[0][1], REFLECTS[0][1]
assert "repertoire 2 of 30" in REFLECTS[0][1], REFLECTS[0][1]

# the voice: 3 gust on/off pairs on ch 0, in order, on ~= launch
ons  = [e for e in SYN if e[1] == "on"  and e[2] == 0]
offs = [e for e in SYN if e[1] == "off" and e[2] == 0]
assert len(ons) == 3 and len(offs) == 3, (len(ons), len(offs))
for on, off in zip(ons, offs):
    assert 0.1 < off[0] - on[0] < 0.6, (on, off)   # gust dies in follow-through

# tones on ch 2: hello(2) + 3 full landings + 3 echo notes
tones = [e for e in SYN if e[1] == "note" and e[2] == 2]
assert len(tones) == 8, tones
land_notes = [e[3] for e in tones[2:5]]
echo_notes = [e[3] for e in tones[5:8]]
assert land_notes == [72, 62, 67], land_notes    # X- Y+ Z-
assert echo_notes == land_notes, echo_notes      # the echo says it back
full = [e for e in tones[2:5] if e[4] == 95]
assert len(full) == 3, "landings not in cone: " + str(tones[2:5])

# senses persisted whole in mem
assert MEM["sense"].flight is False and MEM["hand_g"].state is False
assert MEM["phrase"] == [] and MEM["cuts"] == 3

print("  gusts: 3 on/off pairs, died {:.2f}-{:.2f}s after attack".format(
    min(o[0]-i[0] for i,o in zip(ons,offs)), max(o[0]-i[0] for i,o in zip(ons,offs))))
print("  tones: landings {} -> echo {}".format(land_notes, echo_notes))
print("  reflect: " + REFLECTS[0][1][:80] + "...")
print("\nall kata smoke checks pass")
