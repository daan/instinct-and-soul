"""
tune.py — interactive tuner for the CORES3 creature.

Run:
    tune creatures/cores3

Then flash creatures/cores3/main.py onto the CORES3 (set STA_SSID/PASS first)
and watch it connect on port 8765. Type a recipe name (with optional args)
and the corresponding instinct code is hot-swapped onto the board.

Commands:
  off                   — stop motor + speaker
  <duty>                — Grove motor (GPIO1) at constant duty (0–1023)
  sweep                 — ramp motor 0 -> 1023, step 25, 3s each
  heartbeat <duty>      — double-pulse heartbeat (default 500)
  breathe <duty>        — sine ramp up/down (default 500)
  pulse <duty> <ms>     — square wave on/off (default 500 300)
  tone <freq> <ms> <v>  — single tone via speaker (default 440 300 64)
  chirp [vol]           — ascending tone sweep 200..2000 Hz (default vol 64)
  imulog                — live IMU variance + ALS stream (motor off)
  imutune               — measure IMU/motor crosstalk per duty level
  alslog                — live light + proximity stream
  shake [vol]           — motion-driven tone demo (default vol 32)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "<duty> | off | sweep | heartbeat <d> | breathe <d> | pulse <d> <ms> | "
    "tone <hz> <ms> <vol> | chirp [vol] | imulog | imutune | alslog | shake [vol]"
)


def clamp_duty(v):
    return max(0, min(1023, int(v)))


def clamp_vol(v):
    return max(0, min(255, int(v)))


class CORES3Tuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "cores3"

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
                self.log_msg("motor off, speaker stopped", style="cyan")

            elif cmd == "sweep":
                code = format_recipe(RECIPES["sweep"])
                self.log_msg("sweep duty 0->1023", style="cyan")

            elif cmd == "heartbeat":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 500
                code = format_recipe(RECIPES["heartbeat"], duty=d)
                self.log_msg("heartbeat duty={}".format(d), style="cyan")

            elif cmd == "breathe":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 500
                code = format_recipe(RECIPES["breathe"], duty=d)
                self.log_msg("breathe peak={}".format(d), style="cyan")

            elif cmd == "pulse":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 500
                ms = max(10, min(5000, int(parts[2]))) if len(parts) > 2 else 300
                code = format_recipe(RECIPES["pulse"], duty=d, ms=ms)
                self.log_msg("pulse duty={} {}ms".format(d, ms), style="cyan")

            elif cmd == "tone":
                freq = max(20, min(20000, int(parts[1]))) if len(parts) > 1 else 440
                ms = max(10, min(5000, int(parts[2]))) if len(parts) > 2 else 300
                vol = clamp_vol(parts[3]) if len(parts) > 3 else 64
                code = format_recipe(RECIPES["tone"], freq=freq, ms=ms, vol=vol)
                self.log_msg("tone {}Hz {}ms vol={}".format(freq, ms, vol), style="cyan")

            elif cmd == "chirp":
                vol = clamp_vol(parts[1]) if len(parts) > 1 else 64
                code = format_recipe(RECIPES["chirp"], vol=vol)
                self.log_msg("chirp 200..2000Hz vol={}".format(vol), style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU variance + ALS — motor off", style="cyan")

            elif cmd == "imutune":
                code = format_recipe(RECIPES["imutune"])
                self.log_msg("IMU/motor crosstalk measurement — don't touch!", style="cyan")

            elif cmd == "alslog":
                code = format_recipe(RECIPES["alslog"])
                self.log_msg("live light + proximity stream", style="cyan")

            elif cmd == "shake":
                vol = clamp_vol(parts[1]) if len(parts) > 1 else 32
                code = format_recipe(RECIPES["shake"], vol=vol)
                self.log_msg("shake -> tone demo, vol={}".format(vol), style="cyan")

            else:
                # numeric: constant duty on Grove motor
                d = clamp_duty(parts[0])
                code = format_recipe(RECIPES["constant"], duty=d)
                self.log_msg("motor duty={}".format(d), style="cyan")

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    CORES3Tuner().run()
