"""
tune.py — interactive tuner for the sticks3 creature.

This body has no motor — only IMU + speaker. Commands are limited to
sound generation and sensor logging.

Run:
    tune creatures/sticks3
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "off | imulog | tone <hz> <ms> [vol] | chirp [vol] | shake [vol]"
)


def clamp_vol(v):
    return max(0, min(255, int(v)))


class M5StickS3Tuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "sticks3"

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

        try:
            if cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("speaker stopped", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU variance stream", style="cyan")

            elif cmd == "tone":
                freq = max(20, min(20000, int(parts[1]))) if len(parts) > 1 else 440
                ms = max(10, min(5000, int(parts[2]))) if len(parts) > 2 else 200
                vol = clamp_vol(parts[3]) if len(parts) > 3 else 64
                code = format_recipe(RECIPES["tone"], freq=freq, ms=ms, vol=vol)
                self.log_msg("tone {}Hz {}ms vol={}".format(freq, ms, vol), style="cyan")

            elif cmd == "chirp":
                vol = clamp_vol(parts[1]) if len(parts) > 1 else 64
                code = format_recipe(RECIPES["chirp"], vol=vol)
                self.log_msg("chirp 200..2000Hz vol={}".format(vol), style="cyan")

            elif cmd == "shake":
                vol = clamp_vol(parts[1]) if len(parts) > 1 else 32
                code = format_recipe(RECIPES["shake"], vol=vol)
                self.log_msg("shake -> tone demo, vol={}".format(vol), style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    M5StickS3Tuner().run()
