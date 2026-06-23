"""Deterministic test for the realtime + reflection-freeze model (no network).

A FakeLLM with settable latency drives a tiny SimSpine. Asserts:
  - nothing hangs (single-loop, multi-coroutine, and busy-loop instincts);
  - the creature's timeline is identical regardless of LLM speed (same number of
    reflections for fast vs slow), while slow-LLM takes more wall-clock — i.e.
    the freeze absorbs the extra latency so runs stay comparable.
"""
import asyncio
import glob
import json
import os
import shutil
import tempfile
import time

from instinct_and_soul.reflection import Creature
from instinct_and_soul.sim_spine import SimSpine

# A new instinct the FakeLLM "writes" each reflection — keeps sending so the
# next reflection fires.
NEW_INSTINCT = """async def run():
    n = 0
    while True:
        Imu.getAccel()
        n += 1
        if n % 3 == 0:
            Synth.note(0, 60, 50)        # play, so we can detect recovery
        if n % 6 == 0:
            send("v tick %d" % n)
        await asyncio.sleep_ms(33)
"""

SEEDS = {
    "single": """async def run():
    n = 0
    while True:
        Imu.getAccel()
        n += 1
        if n % 6 == 0:
            send("tick %d" % n)
        await asyncio.sleep_ms(33)
""",
    "multi": """async def sensor():
    n = 0
    while True:
        Imu.getAccel(); n += 1
        if n % 6 == 0: send("s %d" % n)
        await asyncio.sleep_ms(33)
async def music():
    while True:
        Synth.note(0, 60, 50); await asyncio.sleep_ms(100)
async def run():
    asyncio.create_task(sensor())
    asyncio.create_task(music())
    while True:
        await asyncio.sleep_ms(500)
""",
    "busy": """async def run():
    n = 0
    while True:
        n += 1
        if n % 20000 == 0:           # spin on sleep_ms(0); act/log only rarely
            Imu.getAccel(); send("b %d" % n)
        await asyncio.sleep_ms(0)
""",
    "crash": """async def run():
    n = 0
    while True:
        Imu.getAccel(); n += 1
        if n == 4:                   # crash early — before any reflection swaps it
            boom = undefined_name_xyz
        if n % 6 == 0: send("c %d" % n)
        await asyncio.sleep_ms(33)
""",
}


def _last_midi_ms(sess):
    import os as _os
    p = _os.path.join(sess, "output", "midi_events.jsonl")
    if not _os.path.isfile(p):
        return 0.0
    ev = [json.loads(l) for l in open(p) if l.strip() and '"note"' in l]
    return ev[-1]["t"] if ev else 0.0


class FakeLLM:
    def __init__(self, latency_s):
        self.latency = latency_s
        self.calls = 0

    async def call(self, system_prompt, user_message):
        await asyncio.sleep(self.latency)
        self.calls += 1
        return {
            "text": "<intent>tick %d</intent>\n<instinct>\n%s</instinct>" % (self.calls, NEW_INSTINCT),
            "usage": {"input_tokens": 1, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0, "output_tokens": 1},
        }


def _make_creature(tmp, seed_code):
    d = os.path.join(tmp, "creature")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "system_prompt.md"), "w").write("sys")
    open(os.path.join(d, "character.md"), "w").write("char")
    open(os.path.join(d, "seed_experience.md"), "w").write("exp")
    open(os.path.join(d, "seed_instinct.py"), "w").write(seed_code)
    return Creature(d)


def _make_imu(tmp):
    p = os.path.join(tmp, "imu.jsonl")
    with open(p, "w") as f:
        for i in range(200):                       # ~6.6 s of samples at 33 ms
            t = i * 33.0
            f.write(json.dumps({"t": t, "ax": 0.1, "ay": 0.0, "az": 1.0,
                                "gx": 0.0, "gy": 0.0, "gz": 0.0}) + "\n")
    return p


def run_case(seed, latency, *, duration_ms=1500.0, reflection_time=0.3, wall_timeout=25.0):
    tmp = tempfile.mkdtemp()
    try:
        creature = _make_creature(tmp, SEEDS[seed])
        imu = _make_imu(tmp)
        sim = SimSpine(creature, FakeLLM(latency), {"model": None},
                       imu_path=imu, duration_ms=duration_ms, resume=False,
                       reflection_time=reflection_time)
        sess = sim.loop.store.base
        t0 = time.monotonic()
        asyncio.run(asyncio.wait_for(sim.run(), timeout=wall_timeout))
        wall = time.monotonic() - t0
        refls = len(glob.glob(os.path.join(sess, "reflections", "*.json")))
        crashes = len(glob.glob(os.path.join(sess, "crashes", "*")))
        # creature-time the run reached (from sim_meta + the last imu read)
        reads = open(os.path.join(sess, "input", "imu_reads.jsonl")).read().strip().split("\n")
        last_ct = json.loads(reads[-1])["t"] if reads and reads[0] else 0.0
        return {"wall": wall, "reflections": refls, "crashes": crashes,
                "creature_ms": last_ct, "last_midi_ms": _last_midi_ms(sess)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=== single-loop: fast vs slow LLM (freeze keeps the timeline equal) ===")
    fast = run_case("single", 0.02)
    slow = run_case("single", 0.6)
    print(f"  fast LLM: {fast}")
    print(f"  slow LLM: {slow}")
    assert fast["crashes"] == 0 and slow["crashes"] == 0, "unexpected crash"
    # Same creature timeline regardless of LLM speed (±jitter from message
    # buffering), and both dance the full duration — not overshoot.
    assert abs(fast["reflections"] - slow["reflections"]) <= 2, \
        "creature timeline differs across LLM speed (freeze broken)"
    for r in (fast, slow):
        assert 1400 <= r["creature_ms"] <= 1900, f"creature-time off: {r['creature_ms']}"
    # The freeze absorbs the slow LLM's extra latency → more wall-clock, same
    # creature-time. (3 reflections × (0.6−0.3)s of freeze ≈ +0.9 s.)
    assert slow["wall"] > fast["wall"] + 0.4, "slow LLM should take more wall-time (freeze)"

    print("=== robustness: nothing hangs ===")
    for seed in ("multi", "busy"):
        print(f"  running {seed}…", flush=True)
        r = run_case(seed, 0.05, wall_timeout=40.0)
        print(f"  {seed}: {r}")
        assert r["creature_ms"] >= 1400, f"{seed} didn't reach duration"
        assert r["crashes"] == 0, f"{seed} crashed"

    print("=== crash recovery: a crashed instinct recovers promptly and plays ===")
    r = run_case("crash", 0.05, wall_timeout=20.0)
    print(f"  crash: {r}")
    # The crash seed plays no notes and dies at ~130 ms (before its first send),
    # so ANY notes mean the soul redeployed a working instinct and it ran. The
    # recovery must play well past the crash and to ~duration — proving the
    # deploy didn't stall waiting on a dead body for the budget deadline.
    assert r["creature_ms"] >= 1400, "crash run didn't reach duration"
    assert r["last_midi_ms"] >= 1200, \
        f"recovery never played after the crash (deploy stalled?): {r['last_midi_ms']}"
    assert r["wall"] < 6.0, f"recovery stalled (wall {r['wall']:.1f}s for a 1.5 s clip)"

    print("\nALL ASSERTIONS PASSED ✓")


if __name__ == "__main__":
    main()
