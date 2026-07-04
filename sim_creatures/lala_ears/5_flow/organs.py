"""Organs of this creature: an Ear — the sense of one's own voice.

Loaded once per session by the harness socket (creature_sim/organs.py);
attach(scope) runs at every instinct (re)load. The note record lives at module
level, so it survives instinct hot-swaps the way Mem does.

The Ear is read-only from inside: the instinct can attend to it but cannot
clear it or write into it. Capture happens by interposition — the instinct's
`Synth` is transparently wrapped, so every note is recorded at the moment it
sounds, regardless of what the instinct code does. Control changes are counted
(cc_total), not buffered; program changes pass through unrecorded.
"""
import time

_MAXLEN = 400
_events = []      # newest last; entry formats below
_cc_total = [0]   # control_change calls since session start


def _record(entry):
    _events.append(entry)
    if len(_events) > _MAXLEN:
        del _events[:len(_events) - _MAXLEN]


class _Ear:
    """The notes this body voiced, newest last. Entry formats:
        [t_ms, "on",   ch, note, velocity]
        [t_ms, "off",  ch, note]
        [t_ms, "note", ch, note, velocity, ms]
    """

    def recent(self, n=None, ch=None):
        """The last n note events (all if n is None), oldest first.
        ch selects a single voice: only events on that channel."""
        evs = _events if ch is None else [e for e in _events if e[2] == ch]
        if n is None or n >= len(evs):
            return list(evs)
        return evs[-int(n):]

    def cc_total(self):
        """Control-change messages sent since the session started."""
        return _cc_total[0]


class _EarSynth:
    def __init__(self, real):
        self._real = real

    def program(self, ch, program):
        return self._real.program(ch, program)

    def control_change(self, ch, control, value):
        _cc_total[0] += 1
        return self._real.control_change(ch, control, value)

    def note_on(self, ch, note, velocity=80):
        _record([time.ticks_ms(), "on", ch, note, velocity])
        return self._real.note_on(ch, note, velocity)

    def note_off(self, ch, note, velocity=0):
        _record([time.ticks_ms(), "off", ch, note])
        return self._real.note_off(ch, note, velocity)

    def note(self, ch, note, ms, velocity=80):
        _record([time.ticks_ms(), "note", ch, note, velocity, ms])
        return self._real.note(ch, note, ms, velocity)


def attach(scope):
    real = scope["Synth"]
    if isinstance(real, _EarSynth):   # re-attach on hot-swap: don't double-wrap
        real = real._real
    scope["Synth"] = _EarSynth(real)
    scope["Ear"] = _Ear()
