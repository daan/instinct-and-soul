"""
tune.py — interactive motor + IMU tuner for the touchy-pebble (Xiao ESP32-C3).

Run:
    tune creatures/touchy-pebble

Then flash creatures/touchy-pebble/main.py onto the Xiao and watch it connect
on port 8765. Type a recipe name (with optional args) and the corresponding
instinct code is hot-swapped onto the board.

Commands:
  <duty>             — set both motors to constant duty (0–1023)
  <a> <b>            — set motor A and B separately
  off                — stop both motors
  sweep              — ramp duty 0 -> 1023, 25 step, 3s each
  heartbeat <duty>   — double-pulse heartbeat pattern
  breathe <duty>     — slow sine ramp up and down
  pulse <duty> <ms>  — square wave: on for <ms>, off for <ms>
  ripple <duty>      — alternating motors, wave-like
  mix <a> <b>        — different duty on each motor
  mixsweep <a>       — hold A at <a>, sweep B from 0 to 1023
  imutune            — measure IMU variance at each motor duty level
  imulog             — live stream accel variance (motors off)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "duty | a b | off | sweep | heartbeat <d> | breathe <d> | pulse <d> <ms> | "
    "ripple <d> | mix <a> <b> | mixsweep <a> | imutune | imulog"
)


def clamp_duty(v):
    return max(0, min(1023, int(v)))


class TouchyPebbleTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "touchy-pebble"

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
                code = format_recipe(RECIPES["constant"], a=0, b=0)
                self.log_msg("motors off", style="cyan")

            elif cmd == "sweep":
                code = format_recipe(RECIPES["sweep"])
                self.log_msg("starting sweep 0->1023", style="cyan")

            elif cmd == "heartbeat":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 80
                code = format_recipe(RECIPES["heartbeat"], duty=d)
                self.log_msg("heartbeat duty={}".format(d), style="cyan")

            elif cmd == "breathe":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 80
                code = format_recipe(RECIPES["breathe"], duty=d)
                self.log_msg("breathe peak={}".format(d), style="cyan")

            elif cmd == "pulse":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 80
                ms = max(10, min(5000, int(parts[2]))) if len(parts) > 2 else 300
                code = format_recipe(RECIPES["pulse"], duty=d, ms=ms)
                self.log_msg("pulse duty={} {}ms".format(d, ms), style="cyan")

            elif cmd == "ripple":
                d = clamp_duty(parts[1]) if len(parts) > 1 else 80
                code = format_recipe(RECIPES["ripple"], duty=d)
                self.log_msg("ripple duty={}".format(d), style="cyan")

            elif cmd == "mix":
                a = clamp_duty(parts[1]) if len(parts) > 1 else 200
                b = clamp_duty(parts[2]) if len(parts) > 2 else 600
                code = format_recipe(RECIPES["mix"], a=a, b=b)
                self.log_msg("mix a={} b={}".format(a, b), style="cyan")

            elif cmd == "mixsweep":
                a = clamp_duty(parts[1]) if len(parts) > 1 else 300
                code = format_recipe(RECIPES["mixsweep"], a=a)
                self.log_msg("mixsweep A fixed at {}, sweeping B".format(a), style="cyan")

            elif cmd == "imutune":
                code = format_recipe(RECIPES["imutune"])
                self.log_msg("starting IMU/motor crosstalk measurement — don't touch the pebble!", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU variance — motors off. pick it up, hold, shake...", style="cyan")

            else:
                # numeric: constant duty (single value or pair)
                if len(parts) == 1:
                    a = b = clamp_duty(parts[0])
                elif len(parts) == 2:
                    a = clamp_duty(parts[0])
                    b = clamp_duty(parts[1])
                else:
                    self.log_msg("unknown command", style="yellow")
                    return
                code = format_recipe(RECIPES["constant"], a=a, b=b)
                self.log_msg("constant a={} b={}".format(a, b), style="cyan")

        except Exception as e:
            self.log_msg("error: {} — try: 80 | heartbeat 60 | breathe 100 | pulse 80 300 | ripple 60".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    TouchyPebbleTuner().run()
