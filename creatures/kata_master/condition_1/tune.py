"""
tune.py — interactive tuner for the kata_master creature.

This body senses with the IMU and speaks through the Grove SAM2695 GM synth.
The tuner's first job on real hardware: find the VOICE (the pan-flute gust,
the six pose tones — the SAM's ROM patches differ from FluidR3, so everything
tuned in the sim gets re-auditioned here) and find the VOLUME the battery can
afford — every sound recipe reports battery-voltage sag while playing.

Run:
    tune creatures/kata_master/condition_1

Feel gates (the stage-1/2 calibration experiments, no spine needed):
    deploy kata                     the condition_1 kata seed, live
    deploy swoosh                   the 1_swoosh gust seed, live
    deploy tones                    the 2_tones rest-tone seed, live
    deploy <path>                   any seed file

Live bench (run `stetho` in a second terminal for the dashboard):
    stetho [ip] | stetho off        arm/detach the organ stream (UDP-OSC
                                    :9001) without killing the running
                                    deploy — an overlay, not a replacement

Volume / energy:
    swooshvol                       one gust at CC7 25/50/75/100/127 + vbat sag
    tonevol                         six tones at CC7 25/50/75/100/127 + vbat sag
    swoosh [vol] [reps]             gusts at one volume (default 90, 3x)
    tones [vol]                     the six pose tones at one volume
    mastervol [v]                   GM master volume (SysEx, scales everything)
    vbat                            live battery voltage/level/charging

Voice:
    note [ch] [note] [ms] [vel]     play one note (default ch0 C4 500ms vel90)
    program [ch] [prog]             set GM instrument, play a test note
    off                             all notes off (silence the synth)

IMU:
    imulog                          live accel/gyro means (which axis is which)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "deploy kata|swoosh|tones|<path> | stetho [ip|off] | synthcheck "
    "| swooshvol | tonevol | swoosh [vol] [reps] | tones [vol] "
    "| mastervol [v] | vbat | note [ch] [n] [ms] [vel] "
    "| program [ch] [prog] | imulog | off"
)

# Seeds the tuner can deploy directly, no spine session needed: the real
# kata seed, plus the stage-1/2 feel-gate experiments (whose sim series
# stays the canonical source — the same files drive the offline bench).
DEPLOY_SHORTCUTS = {
    "kata": "creatures/kata_master/condition_1/seed_instinct.py",
    "swoosh": "sim_creatures/kata-master/1_swoosh/seed_instinct.py",
    "tones": "sim_creatures/kata-master/2_tones/seed_instinct.py",
}


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class KataMasterTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "kata_master"

    def __init__(self):
        super().__init__()
        # The most recent deploy/recipe: overlay commands (stetho) prepend
        # their few lines to it, so arming the stethoscope doesn't kill the
        # seed you're watching.
        self._stream_code = INSTINCT_IDLE

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

        # overlay commands run a few lines, then fall through into the
        # last deploy so the seed keeps running
        overlay = cmd in ("stetho",)

        try:
            if cmd == "deploy":
                if len(parts) < 2:
                    self.log_msg("deploy what? swoosh | tones | <path to seed>", style="yellow")
                    return
                path = DEPLOY_SHORTCUTS.get(parts[1], parts[1])
                try:
                    with open(path) as f:
                        code = f.read()
                    compile(code, path, "exec")
                except OSError:
                    self.log_msg("no such seed: {}".format(path), style="yellow")
                    return
                except SyntaxError as e:
                    self.log_msg("seed has a syntax error: {}".format(e), style="yellow")
                    return
                self.log_msg("deploying {} ({} bytes)".format(path, len(code)), style="cyan")

            elif cmd == "stetho":
                if len(parts) > 1 and parts[1].lower() == "off":
                    code = ("import stethoscope\n"
                            "stethoscope.detach()\n"
                            "send('stethoscope off')\n") + self._stream_code
                    self.log_msg("stethoscope off", style="cyan")
                else:
                    ip = None
                    if len(parts) > 1 and parts[1].lower() != "on":
                        ip = parts[1]
                    else:
                        try:
                            ip = self.board_ws.local_address[0]
                        except Exception:
                            pass
                    if not ip or ip == "0.0.0.0":
                        self.log_msg("can't detect my ip — use: stetho <ip>", style="yellow")
                        return
                    code = ("import stethoscope\n"
                            "stethoscope.attach(\"{ip}\", 9001)\n"
                            "send('stethoscope -> {ip}:9001')\n").format(ip=ip) \
                           + self._stream_code
                    self.log_msg("organ stream -> {}:9001 — run `stetho` in "
                                 "another terminal".format(ip), style="cyan")

            elif cmd == "synthcheck":
                code = format_recipe(RECIPES["synthcheck"])
                self.log_msg("probing Grove 5V + candidate TX pins — listen", style="cyan")

            elif cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("synth silenced", style="cyan")

            elif cmd == "vbat":
                code = format_recipe(RECIPES["vbat"])
                self.log_msg("live battery stream", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU stream", style="cyan")

            elif cmd == "swoosh":
                vol = arg(1, 1, 127, 90)
                reps = arg(2, 1, 20, 3)
                code = format_recipe(RECIPES["swoosh"], vol=vol, reps=reps)
                self.log_msg("swoosh vol={} x{}".format(vol, reps), style="cyan")

            elif cmd == "tones":
                vol = arg(1, 1, 127, 90)
                code = format_recipe(RECIPES["tones"], vol=vol)
                self.log_msg("six pose tones at vol={}".format(vol), style="cyan")

            elif cmd == "swooshvol":
                code = format_recipe(RECIPES["swooshvol"])
                self.log_msg("gust volume sweep 25..127 + vbat sag", style="cyan")

            elif cmd == "tonevol":
                code = format_recipe(RECIPES["tonevol"])
                self.log_msg("tone volume sweep 25..127 + vbat sag", style="cyan")

            elif cmd == "mastervol":
                v = arg(1, 0, 127, 100)
                code = format_recipe(RECIPES["mastervol"], v=v)
                self.log_msg("master volume -> {}".format(v), style="cyan")

            elif cmd == "note":
                ch = arg(1, 0, 15, 0)
                note = arg(2, 0, 127, 60)
                ms = arg(3, 10, 8000, 500)
                vel = arg(4, 1, 127, 90)
                code = format_recipe(RECIPES["note"], ch=ch, note=note, ms=ms, vel=vel)
                self.log_msg("note ch={} n={} {}ms vel={}".format(ch, note, ms, vel), style="cyan")

            elif cmd == "program":
                ch = arg(1, 0, 15, 0)
                prog = arg(2, 0, 127, 75)
                code = format_recipe(RECIPES["program"], ch=ch, prog=prog)
                self.log_msg("program ch={} -> GM {}".format(ch, prog), style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        if not overlay:
            self._stream_code = code
        await self.board_ws.send(code)


if __name__ == "__main__":
    KataMasterTuner().run()
