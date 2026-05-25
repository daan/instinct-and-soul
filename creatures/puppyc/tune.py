"""
tune.py — interactive gait tuner for the puppyc (M5StickS3 + 4-servo hat).

Run:
    tune creatures/puppyc

Commands:
  center                              — all legs to 90
  stand | sit | rest                  — preset poses
  pose <fl> <fr> <bl> <br>            — set every leg
  wiggle <leg> [amp]                  — sine-wiggle one leg (leg 0..3)
  calibrate [amp]                     — sweep each leg forward and back
  trot [amp] [period_ms] [duty%]      — diagonal trot
  walk [amp] [period_ms] [duty%]      — four-phase walk
  pronk [amp] [period_ms] [duty%]     — all four legs in phase
  wave [leg]                          — one-paw hello
  imulog                              — stream IMU values
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "stop | center | stand | sit | rest | pose <fl> <fr> <bl> <br> | "
    "wiggle <leg> [amp] | calibrate [amp] | trot [amp] [ms] [duty%] | "
    "back [amp] [ms] [duty%] | rotate <cw|ccw> [seconds] | "
    "rotate180 <cw|ccw> [degrees] | circle <cw|ccw> [amp] [ms] | "
    "walk [amp] [ms] [duty%] | pronk [amp] [ms] [duty%] | wave [leg] | imulog | miclog"
)


def clamp_angle(v):
    return max(0, min(180, int(v)))


def clamp_amp(v):
    return max(0, min(60, int(v)))


def clamp_leg(v):
    return max(0, min(3, int(v)))


def clamp_period(v):
    return max(100, min(3000, int(v)))


def clamp_duty(v):
    return max(10, min(90, int(v)))


class PuppyCTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "puppyc"

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
            if cmd == "center":
                code = format_recipe(RECIPES["center"])
                self.log_msg("center", style="cyan")

            elif cmd == "stand":
                code = format_recipe(RECIPES["stand"])
                self.log_msg("stand", style="cyan")

            elif cmd == "sit":
                code = format_recipe(RECIPES["sit"])
                self.log_msg("sit", style="cyan")

            elif cmd == "rest":
                code = format_recipe(RECIPES["rest"])
                self.log_msg("rest", style="cyan")

            elif cmd == "pose":
                if len(parts) < 5:
                    self.log_msg("usage: pose <fl> <fr> <bl> <br>", style="yellow")
                    return
                fl, fr, bl, br = (clamp_angle(parts[i]) for i in range(1, 5))
                code = format_recipe(RECIPES["pose"], fl=fl, fr=fr, bl=bl, br=br)
                self.log_msg("pose fl={} fr={} bl={} br={}".format(fl, fr, bl, br), style="cyan")

            elif cmd == "wiggle":
                leg = clamp_leg(parts[1]) if len(parts) > 1 else 0
                amp = clamp_amp(parts[2]) if len(parts) > 2 else 30
                code = format_recipe(RECIPES["wiggle"], leg=leg, amp=amp)
                self.log_msg("wiggle leg={} amp={}".format(leg, amp), style="cyan")

            elif cmd == "calibrate":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 40
                code = format_recipe(RECIPES["calibrate"], amp=amp)
                self.log_msg("calibrate amp={}".format(amp), style="cyan")

            elif cmd == "trot":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 40
                period = clamp_period(parts[2]) if len(parts) > 2 else 500
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 65
                code = format_recipe(RECIPES["trot"], amp=amp, period=period, duty=duty)
                self.log_msg("trot amp={} period={}ms duty={}%".format(amp, period, duty), style="cyan")

            elif cmd == "walk":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 35
                period = clamp_period(parts[2]) if len(parts) > 2 else 800
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 75
                code = format_recipe(RECIPES["walk"], amp=amp, period=period, duty=duty)
                self.log_msg("walk amp={} period={}ms duty={}%".format(amp, period, duty), style="cyan")

            elif cmd == "pronk":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 35
                period = clamp_period(parts[2]) if len(parts) > 2 else 450
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 60
                code = format_recipe(RECIPES["pronk"], amp=amp, period=period, duty=duty)
                self.log_msg("pronk amp={} period={}ms duty={}%".format(amp, period, duty), style="cyan")

            elif cmd == "wave":
                leg = clamp_leg(parts[1]) if len(parts) > 1 else 0
                code = format_recipe(RECIPES["wave"], leg=leg)
                self.log_msg("wave leg={}".format(leg), style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("imulog: streaming IMU", style="cyan")

            elif cmd == "miclog":
                rate = max(8000, min(48000, int(parts[1]))) if len(parts) > 1 else 16000
                window_ms = max(10, min(500, int(parts[2]))) if len(parts) > 2 else 50
                code = format_recipe(RECIPES["miclog"], rate=rate, window_ms=window_ms)
                self.log_msg("miclog rate={}Hz window={}ms".format(rate, window_ms), style="cyan")

            elif cmd == "stop":
                code = format_recipe(RECIPES["stop"])
                self.log_msg("stop", style="cyan")

            elif cmd == "back":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 40
                period = clamp_period(parts[2]) if len(parts) > 2 else 500
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 65
                code = format_recipe(RECIPES["back"], amp=amp, period=period, duty=duty)
                self.log_msg("back amp={} period={}ms duty={}%".format(amp, period, duty), style="cyan")

            elif cmd == "rotate":
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: rotate <cw|ccw> [seconds]", style="yellow")
                    return
                sign = 1 if parts[1].lower() == "ccw" else -1
                seconds = max(1, min(30, int(parts[2]))) if len(parts) > 2 else 4
                code = format_recipe(RECIPES["rotate"], sign=sign, seconds=seconds,
                                     amp=40, period=500, duty=65)
                self.log_msg("rotate {} for {}s".format(parts[1].lower(), seconds), style="cyan")

            elif cmd == "circle":
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: circle <cw|ccw> [amp] [ms]", style="yellow")
                    return
                sign = 1 if parts[1].lower() == "cw" else -1
                amp = clamp_amp(parts[2]) if len(parts) > 2 else 25
                period = clamp_period(parts[3]) if len(parts) > 3 else 2000
                code = format_recipe(RECIPES["circle"], sign=sign, amp=amp, period=period)
                self.log_msg("circle {} amp={} period={}ms".format(parts[1].lower(), amp, period), style="cyan")

            elif cmd == "rotate180":
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: rotate180 <cw|ccw> [degrees]", style="yellow")
                    return
                sign = 1 if parts[1].lower() == "ccw" else -1
                target_deg = max(10, min(720, int(parts[2]))) if len(parts) > 2 else 180
                code = format_recipe(RECIPES["rotate180"], sign=sign, target_deg=target_deg,
                                     amp=40, period=500, duty=65, timeout_s=12)
                self.log_msg("rotate180 {} target={}°".format(parts[1].lower(), target_deg), style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    PuppyCTuner().run()
