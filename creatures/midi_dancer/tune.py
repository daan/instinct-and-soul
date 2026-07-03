"""
tune.py — interactive tuner for the midi_dancer creature.

This body senses with the IMU and speaks through the Grove SAM2695 GM synth.
Commands exercise both surfaces so you can verify the sensor and the MIDI voice
before letting a soul loose on them.

Run:
    tune creatures/midi_dancer

IMU:
    imulog                          live per-axis accel/gyro mean + variance
    shake [ch] [prog]               motion -> note, to feel the IMU/synth coupling

Synth:
    note [ch] [note] [ms] [vel]     play one note (default ch0 C4 500ms vel90)
    program <ch> <prog>             set GM instrument, play a test triad
    chord [root] [ms] [vel]         hold a major triad, then release
    arp [ch] [prog] [vel]           ascending C-major scale on an instrument
    drum [vel]                      kick/snare/hat pattern on channel 9
    off                             all notes off (silence the synth)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "imulog | shake [ch] [prog] | note [ch] [n] [ms] [vel] | program <ch> <prog> "
    "| chord [root] [ms] [vel] | arp [ch] [prog] [vel] | drum [vel] | off"
)


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class MidiDancerTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "midi_dancer"

    def compose(self) -> ComposeResult:
        yield Static("● disconnected", id="status")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder=PLACEHOLDER, id="input")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.clear()
        self.history_index = -1
        if not line:
            return
        self.cmd_history.append(line)

        if self.board_ws is None:
            self.log_msg("no board connected", style="yellow")
            return

        parts = line.split()
        cmd = parts[0].lower()

        def arg(i, lo, hi, default):
            return clamp(parts[i], lo, hi) if len(parts) > i else default

        try:
            if cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("synth silenced", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU mean/variance stream", style="cyan")

            elif cmd == "note":
                ch = arg(1, 0, 15, 0)
                note = arg(2, 0, 127, 60)
                ms = arg(3, 10, 8000, 500)
                vel = arg(4, 1, 127, 90)
                code = format_recipe(RECIPES["note"], ch=ch, note=note, ms=ms, vel=vel)
                self.log_msg("note ch={} n={} {}ms vel={}".format(ch, note, ms, vel), style="cyan")

            elif cmd == "program":
                ch = arg(1, 0, 15, 0)
                prog = arg(2, 0, 127, 11)
                code = format_recipe(RECIPES["program"], ch=ch, prog=prog)
                self.log_msg("program ch={} -> GM {}".format(ch, prog), style="cyan")

            elif cmd == "chord":
                root = arg(1, 0, 127, 60)
                ms = arg(2, 50, 8000, 800)
                vel = arg(3, 1, 127, 80)
                code = format_recipe(RECIPES["chord"], root=root, ms=ms, vel=vel)
                self.log_msg("chord root={} {}ms vel={}".format(root, ms, vel), style="cyan")

            elif cmd == "arp":
                ch = arg(1, 0, 15, 0)
                prog = arg(2, 0, 127, 11)
                vel = arg(3, 1, 127, 90)
                code = format_recipe(RECIPES["arp"], ch=ch, prog=prog, vel=vel)
                self.log_msg("arp ch={} GM {} vel={}".format(ch, prog, vel), style="cyan")

            elif cmd == "drum":
                vel = arg(1, 1, 127, 100)
                code = format_recipe(RECIPES["drum"], vel=vel)
                self.log_msg("drum pattern vel={}".format(vel), style="cyan")

            elif cmd == "shake":
                ch = arg(1, 0, 15, 0)
                prog = arg(2, 0, 127, 11)
                code = format_recipe(RECIPES["shake"], ch=ch, prog=prog)
                self.log_msg("shake -> note, ch={} GM {}".format(ch, prog), style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    MidiDancerTuner().run()
