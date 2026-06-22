"""Fake Mem: a bounded named-slot ring buffer for the simulator.

Mirrors the on-device `Mem` (creatures/*/main.py) exactly — push/recent/latest/
slots/clear, up to MAX_SLOTS named slots, each a bounded list. Unlike the other
fakes there is no hardware behind it: `Mem` is plain in-RAM data on the device
too, so this is a faithful port rather than a stand-in.

The harness holds ONE instance and re-injects it into the instinct scope on every
hot-swap, so pushed data survives the instinct being rewritten — the whole point
of Mem. Mem is private to the instinct; to surface what it holds, the instinct
must send() it.
"""


class _Mem:
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
