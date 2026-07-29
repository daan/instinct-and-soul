"""stethoscope (device side) — the creature's EEG, over WiFi.

The MicroPython twin of instinct_and_soul.creature_sim.stethoscope: organs
call tap(kind, **payload) / probe(name, value) and, once attached, each
lands on the laptop as a UDP-OSC packet the host `stetho` dashboard already
understands. Advisory and lossy by contract — packets are fire-and-forget,
every failure is swallowed, and detached (the default) both calls are
no-ops, so wearing the creature costs nothing.

The attach target survives radio naps: batch mode tears the WLAN down
between session windows, which kills the UDP socket — on the next tap the
socket is reopened toward the remembered target instead of going silent.

Wire format (must match creature_sim/stethoscope.py):
    /organ/<kind>   ,is   t_ms(int32 ticks_ms), payload-json(string)
    /probe/<name>   ,if   t_ms(int32 ticks_ms), value(float32)

Arm it from main's STETHO_HOST policy (re-armed at every radio-up), or by
hand from a tuner recipe (the tilt tuner's `stetho` command):
    import stethoscope
    stethoscope.attach("<laptop ip>", 9001)
"""
import struct
import time

try:
    import usocket as socket
    import ujson as json
except ImportError:
    import socket
    import json

_sock = None
_addr = None
_target = None   # (host, port) — kept across socket deaths so we can heal


def attach(host, port=9001):
    """Start emitting to host:port. Safe to call again to retarget. Never
    raises: with the radio down the target is kept and the socket opens
    lazily on the first tap after the radio returns."""
    global _target
    _target = (host, port)
    _reopen()


def detach():
    global _target
    _target = None
    _close()


def _close():
    global _sock, _addr
    if _sock:
        try:
            _sock.close()
        except Exception:
            pass
    _sock = None
    _addr = None


def _reopen():
    global _sock, _addr
    _close()
    if _target is None:
        return
    try:
        _addr = socket.getaddrinfo(_target[0], _target[1])[0][-1]
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except Exception:
        _close()   # radio down: stay armed, retry on a later call


def _osc_str(s):
    b = s.encode()
    return b + b"\x00" * (4 - (len(b) % 4))


def tap(kind, **payload):
    if _sock is None:
        _reopen()
        if _sock is None:
            return
    try:
        _sock.sendto(_osc_str("/organ/" + kind) + _osc_str(",is")
                     + struct.pack(">i", time.ticks_ms())
                     + _osc_str(json.dumps(payload)), _addr)
    except Exception:
        _close()   # interface bounced beneath us; heal on the next call


def probe(name, value):
    if _sock is None:
        _reopen()
        if _sock is None:
            return
    try:
        _sock.sendto(_osc_str("/probe/" + name) + _osc_str(",if")
                     + struct.pack(">i", time.ticks_ms())
                     + struct.pack(">f", float(value)), _addr)
    except Exception:
        _close()   # interface bounced beneath us; heal on the next call
