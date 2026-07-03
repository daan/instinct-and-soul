"""synth.py — device-side `Synth`: drive an M5Stack Unit-Synth (SAM2695)
General-MIDI module over the Grove port as raw MIDI-over-UART.

The SAM2695 is a hardware GM synthesizer: it sustains and releases notes for
you, so there is no audio loop to tick (unlike the built-in Speaker, which needs
M5.update() in a tight loop). We only ever transmit — MIDI bytes out on the
UART's TX line — so RX is unused.

API mirrors the simulator's `Synth` (creature_sim/fake_synth.py) exactly, so an
instinct behaves the same in the sim and on hardware:

    Synth.program(ch, program)             # GM instrument 0..127
    Synth.note_on(ch, note, velocity)      # raw note on
    Synth.note_off(ch, note)               # raw note off
    Synth.note(ch, note, ms, velocity)     # fire-and-forget: on now, off after ms
    Synth.control_change(ch, control, value)

`note()` is the fire-and-forget workhorse: it schedules its own note_off as an
asyncio task, so a single call plays cleanly for its full duration without the
instinct juggling the release. Requires the asyncio loop to be running (it is —
the instinct runs under asyncio.run()).

Channel 9 is the GM drum kit. Notes are MIDI numbers (60 = middle C).

── WIRING ────────────────────────────────────────────────────────────────────
The Unit-Synth plugs into the M5StickS3 Grove port (HY2.0-4P). Only TX matters.
SYNTH_TX_PIN below defaults to the Grove Port-A data pins used elsewhere in this
repo (GPIO1/GPIO2). VERIFY against your board's silkscreen — a wrong TX pin is a
silent failure (no notes, no error). The synth's own UART runs at 31250 baud
(standard MIDI); do not change SYNTH_BAUD.
"""

import uasyncio as asyncio
from machine import UART, Pin

SYNTH_UART_ID = 1
SYNTH_TX_PIN = 2       # Grove Port-A TX  (board -> synth). VERIFY on your board.
SYNTH_RX_PIN = 1       # Grove Port-A RX  (unused; synth is receive-only for us)
SYNTH_BAUD = 31250     # standard MIDI baud — the SAM2695 expects this


def _clamp(v, lo, hi):
    v = int(v)
    return lo if v < lo else hi if v > hi else v


class Sam2695Synth:
    def __init__(self, uart_id=SYNTH_UART_ID, tx=SYNTH_TX_PIN, rx=SYNTH_RX_PIN,
                 baud=SYNTH_BAUD):
        self._uart = UART(uart_id, baudrate=baud, tx=Pin(tx), rx=Pin(rx))

    # ── raw MIDI ────────────────────────────────────────────────────────────
    def _send(self, *bytes_):
        try:
            self._uart.write(bytearray(bytes_))
        except Exception as e:
            print("synth: uart write error:", e)

    def program(self, ch, program):
        ch = _clamp(ch, 0, 15)
        self._send(0xC0 | ch, _clamp(program, 0, 127))

    def note_on(self, ch, note, velocity=80):
        ch = _clamp(ch, 0, 15)
        self._send(0x90 | ch, _clamp(note, 0, 127), _clamp(velocity, 0, 127))

    def note_off(self, ch, note, velocity=0):
        ch = _clamp(ch, 0, 15)
        self._send(0x80 | ch, _clamp(note, 0, 127), _clamp(velocity, 0, 127))

    def control_change(self, ch, control, value):
        ch = _clamp(ch, 0, 15)
        self._send(0xB0 | ch, _clamp(control, 0, 127), _clamp(value, 0, 127))

    # ── convenience: timed note ─────────────────────────────────────────────
    async def _release_after(self, ch, note, ms):
        await asyncio.sleep_ms(int(ms))
        self.note_off(ch, note)

    def note(self, ch, note, ms, velocity=80):
        ch = _clamp(ch, 0, 15)
        note = _clamp(note, 0, 127)
        self.note_on(ch, note, velocity)
        asyncio.create_task(self._release_after(ch, note, ms))

    # ── housekeeping ────────────────────────────────────────────────────────
    def all_off(self):
        """Silence every channel — 'all notes off' (CC 123) on all 16, plus a
        program reset. Used on session cleanup so a new instinct starts silent."""
        for ch in range(16):
            self.control_change(ch, 123, 0)
            self.control_change(ch, 120, 0)   # all sound off
