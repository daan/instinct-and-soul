"""creature_mem — device-side `Mem`: a bounded named-slot ring buffer.

Plain in-RAM data on the board — the one thing that survives an instinct
hot-swap (every local variable in run() is wiped on rewrite; Mem is not).
main.py holds ONE instance and re-injects it into the instinct scope on every
swap, so a sliding window of recent samples persists across reflections.

Mirrors the simulator's `_Mem` (creature_sim/fake_mem.py) exactly, so an
instinct behaves the same in the sim and on hardware. Mem is PRIVATE to the
instinct — the spine never reads it; to surface what it holds, send() it.
"""


class Mem:
    DEFAULT_MAXLEN = 300
    MAX_MAXLEN = 1000
    MAX_SLOTS = 8

    def __init__(self):
        self._slots = {}
        self._caps = {}

    def push(self, slot, value, maxlen=None):
        if slot not in self._slots:
            if len(self._slots) >= self.MAX_SLOTS:
                return
            self._slots[slot] = []
            self._caps[slot] = min(maxlen or self.DEFAULT_MAXLEN, self.MAX_MAXLEN)
        elif maxlen is not None:
            new_cap = min(maxlen, self.MAX_MAXLEN)
            self._caps[slot] = new_cap
            buf = self._slots[slot]
            while len(buf) > new_cap:
                buf.pop(0)
        buf = self._slots[slot]
        buf.append(value)
        if len(buf) > self._caps[slot]:
            buf.pop(0)

    def recent(self, slot, n=None):
        buf = self._slots.get(slot)
        if not buf:
            return []
        if n is None or n >= len(buf):
            return list(buf)
        return list(buf[-n:])

    def latest(self, slot):
        buf = self._slots.get(slot)
        return buf[-1] if buf else None

    def slots(self):
        return list(self._slots.keys())

    def clear(self, slot=None):
        if slot is None:
            self._slots = {}
            self._caps = {}
        elif slot in self._slots:
            self._slots[slot] = []
