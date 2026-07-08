"""Stethoscope — the creature's EEG (data movement 3, see ARCHITECTURE.md).

Organs call `tap(kind, **payload)` at the moments their one-shot events are
BORN (flag-set time, not read time — the instinct's consume-on-read events
stay untouched). The harness attaches a session: every tap then lands in
`output/organ_events.jsonl` (movement 1 — authoritative) and, if enabled,
is emitted as UDP-OSC `/organ/<kind>` for any live listener (movement 3 —
advisory, lossy by contract). The harness may also register slow LEVELS
(non-consuming reads like Hunger.level) that get polled and emitted as
`/probe/<name>`.

Organs import this with a fallback so the same organs.py runs on-device,
where the module (for now) doesn't exist:

    try:
        from instinct_and_soul.creature_sim.stethoscope import tap
    except ImportError:
        def tap(kind, **payload):
            pass

Wire format (OSC):
    /organ/<kind>   ,is   t_ms(int32), payload-json(string)
    /probe/<name>   ,if   t_ms(int32), value(float32)
Default target 127.0.0.1:9001. Detached (no session), tap() is a no-op.
"""
import json
import os
import socket
import struct

_state = {
    "clock": None,        # object with .now_ms
    "log": None,          # open file: organ_events.jsonl
    "sock": None,
    "target": None,
}


def _osc_str(s: str) -> bytes:
    b = s.encode()
    return b + b"\x00" * (4 - (len(b) % 4))


def _emit_osc(addr: str, tags: str, *args) -> None:
    sock, target = _state["sock"], _state["target"]
    if sock is None:
        return
    msg = _osc_str(addr) + _osc_str("," + tags)
    for tag, a in zip(tags, args):
        if tag == "i":
            msg += struct.pack(">i", int(a))
        elif tag == "f":
            msg += struct.pack(">f", float(a))
        elif tag == "s":
            msg += _osc_str(str(a))
    try:
        sock.sendto(msg, target)
    except OSError:
        pass


def attach(clock, session_dir: str, osc_target=("127.0.0.1", 9001)) -> None:
    """Called by the harness at session start. osc_target=None disables the
    live emit (the jsonl record is always written once attached)."""
    _state["clock"] = clock
    path = os.path.join(session_dir, "output", "organ_events.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _state["log"] = open(path, "w")
    if osc_target is not None:
        _state["sock"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _state["target"] = osc_target


def detach() -> None:
    if _state["log"] is not None:
        try:
            _state["log"].close()
        except Exception:
            pass
    if _state["sock"] is not None:
        try:
            _state["sock"].close()
        except Exception:
            pass
    _state.update({"clock": None, "log": None, "sock": None, "target": None})


def tap(kind: str, **payload) -> None:
    """An organ event was born. Record it; whisper it to any listener."""
    if _state["clock"] is None:
        return
    t = _state["clock"].now_ms
    if _state["log"] is not None:
        _state["log"].write(json.dumps({"t": t, "kind": kind, **payload}) + "\n")
    _emit_osc("/organ/" + kind, "is", t, json.dumps(payload))


def probe(name: str, value: float) -> None:
    """A slow level sample (harness-polled, non-consuming). OSC-only by
    default — levels are derivable from the record, so the jsonl stays
    events-only unless an organ chooses to tap them."""
    if _state["clock"] is None:
        return
    _emit_osc("/probe/" + name, "if", _state["clock"].now_ms, value)
