"""synth.py — device-side `Synth`: drive an M5Stack Unit-Synth (SAM2695)
General-MIDI module over the Grove port as raw MIDI-over-UART.

Inherited from the midi_dancer line with two additions the kata voice needs:
`pitch_bend` (the pan-flute scoop is a bend ridden through every gust) and
`master_volume` (GM universal SysEx — the output stage ahead of per-channel
CC 7, the knob the volume/energy tuner sweeps).

The SAM2695 is a hardware GM synthesizer: it sustains and releases notes for
you, so there is no audio loop to tick (unlike the built-in Speaker, which needs
M5.update() in a tight loop). We only ever transmit — MIDI bytes out on the
UART's TX line — so RX is unused.

API mirrors the simulator's `Synth` (creature_sim/fake_synth.py):

    Synth.program(ch, program)             # GM instrument 0..127
    Synth.note_on(ch, note, velocity)      # raw note on
    Synth.note_off(ch, note)               # raw note off
    Synth.note(ch, note, ms, velocity)     # fire-and-forget: on now, off after ms
    Synth.control_change(ch, control, value)
    Synth.pitch_bend(ch, value)            # -8192..8191, 0 = center
    Synth.master_volume(value)             # 0..127, SysEx, all channels
    Synth.all_off()                        # silence everything

Channel 9 is the GM drum kit. Notes are MIDI numbers (60 = middle C).

── WIRING ────────────────────────────────────────────────────────────────────
The Unit-Synth plugs into the M5StickS3 Grove port (HY2.0-4P). Only TX matters.
The StickS3 Grove data pins are G9/G10; TX = G9 was confirmed by ear with the
tuner's `synthcheck` (2026-07-13). A wrong TX pin is a SILENT failure (no
notes, no error) — if this driver moves to another board, run synthcheck
first. The synth's own UART runs at 31250 baud (standard MIDI); do not change
SYNTH_BAUD.
"""

import uasyncio as asyncio
from machine import UART, Pin

SYNTH_UART_ID = 1
SYNTH_TX_PIN = 9       # StickS3 Grove data pin (board -> synth), synthcheck-verified
SYNTH_RX_PIN = 10      # the other Grove data pin (unused; synth is receive-only)
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

    def pitch_bend(self, ch, value):
        """value -8192..8191, 0 = center. Range defaults to +-2 semitones;
        widen per channel via RPN 0 (CC 101=0, 100=0, then CC 6=semitones)."""
        ch = _clamp(ch, 0, 15)
        v = _clamp(value, -8192, 8191) + 8192
        self._send(0xE0 | ch, v & 0x7F, (v >> 7) & 0x7F)

    def master_volume(self, value):
        """GM master volume, 0..127 — universal SysEx, scales every channel.
        The energy knob: the Unit-Synth's amp current tracks this."""
        self._send(0xF0, 0x7F, 0x7F, 0x04, 0x01, 0x00,
                   _clamp(value, 0, 127), 0xF7)

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
        """Silence every channel AND reset controller state — 'all notes off'
        (CC 123), 'all sound off' (CC 120), and 'reset all controllers'
        (CC 121: expression back to 127, bend centered, modulation off).
        Runs between instinct swaps: without the reset, an instinct that
        killed its sound by zeroing expression leaves the NEXT instinct's
        notes silent (CCs persist on the SAM2695 across swaps)."""
        for ch in range(16):
            self.control_change(ch, 123, 0)
            self.control_change(ch, 120, 0)
            self.control_change(ch, 121, 0)
