"""
tune.py — interactive tuner for the tilt condition_4 creature.

This body is a PLAIN StickS3 — internal speaker and IMU, nothing attached.
Two things to settle before anyone wears it for real: the CRICKET
vocabulary (trill / up / down — the test is whether you can ignore it) and
the POSTURE read on a real back.

Run:
    tune creatures/tilt/condition_4

Posture / feedback:
    state                        what the SEED sees: still / lean-from-ref /
                                 rot — the condition_4 calibration view
    posture                      live angle/stillness stream (worn)
    setref                       capture upright (sit the way you mean it)
    verbs                        movement-verb stream (MICRO_SHIFT / SHIFT /
                                 FULL_STRETCH / MOVED_OFF) — tune the grammar
    button                       THE explicit channel: press BtnA, watch every
                                 press land exactly once. The BOOT line names
                                 the live edge: btn=cb:WAS_PRESSED | ...

Organ calibration (the live bench — run `stetho` in a second terminal):
    stetho [ip] | stetho off     stream organ events/levels (rot_ema,
                                 posture_deg, still_s, ep_start, verbs) as
                                 UDP-OSC to the laptop's stetho dashboard;
                                 ip is auto-detected from this connection
    params                       report the current (possibly patched) values

Cricket:
    cricket [1-3] [vol]          audition a chirp design, looping every 4s
                                 (1 trill, 2 up, 3 down)
    lowbat [vol]                 audition the low-battery alarm (dying cricket)
    off                          silence

Bring-up:
    deploy baseline|<path>       run a seed live, no spine needed
    vbat | imulog                battery / raw IMU streams
    power                        1Hz vbus/vbat/charging forensics — tells a
                                 benign charger top-off flip (VBUS holds 5V)
                                 from a real 5V dropout (VBUS collapses)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from instinct_and_soul.spine import _fmt_uptime
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "state [still_dps] | offset [secs] | button | stetho [ip|off] "
    "| cricket [1-3] [vol] | lowbat [vol] "
    "| deploy baseline|<path> | vbat | power | imulog | off"
)

DEPLOY_SHORTCUTS = {
    "baseline": "creatures/tilt/condition_4/seed_instinct.py",
}


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class TiltTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "tilt-c4"

    def __init__(self):
        super().__init__()
        # The most recent stream recipe: overlay commands (set / params /
        # stetho) prepend their few lines to it, so patching a threshold
        # doesn't kill the stream you're watching.
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
        # last stream so the view keeps flowing
        overlay = cmd in ("stetho",)

        try:
            if cmd == "state":
                code = format_recipe(RECIPES["state"], parts[1:])
                self.log_msg("the seed's own sense: still / lean / rot / up. "
                             "`state 8` to try a different STILL_DPS",
                             style="cyan")

            elif cmd == "offset":
                code = format_recipe(RECIPES["offset"], parts[1:])
                self.log_msg("STAND UP and hold still — measures your mount "
                             "offset (ZERO_FWD / ZERO_SIDE)", style="cyan")

            elif cmd == "cricket":
                variant = arg(1, 1, 3, 1)
                vol = arg(2, 1, 255, 60)
                code = format_recipe(RECIPES["cricket"], variant=variant, vol=vol)
                self.log_msg("cricket variant {} vol {} — can you ignore it?".format(
                    variant, vol), style="cyan")

            elif cmd == "deploy":
                if len(parts) < 2:
                    self.log_msg("deploy what? baseline | <path to seed>", style="yellow")
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

            elif cmd == "button":
                code = format_recipe(RECIPES["button"])
                self.log_msg("press BtnA — slowly, then fast. Each press "
                             "should land exactly once", style="cyan")

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

            elif cmd == "lowbat":
                vol = arg(1, 1, 255, 100)
                code = format_recipe(RECIPES["lowbat"], vol=vol)
                self.log_msg("low-battery alarm audition at vol {}".format(vol), style="cyan")

            elif cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("silenced", style="cyan")

            elif cmd == "vbat":
                code = format_recipe(RECIPES["vbat"])
                self.log_msg("live battery stream", style="cyan")

            elif cmd == "power":
                code = format_recipe(RECIPES["power"])
                self.log_msg("power forensics: 1Hz vbus/vbat/chg — a CHG FLIP "
                             "with vbus still ~5000mV is benign top-off; vbus "
                             "collapsing = the 5V input really dropped", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU stream", style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        if not overlay:
            self._stream_code = code
        await self.board_ws.send(code)

    def on_board_message(self, msg):
        # The batch runtime journals its sends: J:<device_t_ms>:<text>.
        # Render the device clock readably — a t+ that RESTARTS near zero
        # means the board rebooted between lines.
        if msg.startswith("BOOT:"):
            # The device sends this announce on EVERY connect, so the prefix
            # says nothing about whether the board restarted. Labelling all of
            # them "(RE)BOOTED" is precisely the confusion the lifecycle work exists
            # to remove — decode `wake=` and say which lifecycle moved.
            body = msg[5:].strip()
            tok = {}
            for part in body.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    tok[k] = v
            try:
                up = _fmt_uptime(int(tok.get("uptime", "0").rstrip("s")))
            except ValueError:
                up = "unknown"
            wake = tok.get("wake")
            if wake == "reconnect":
                self.log_msg("LINK back after {} — board up {}, NOT rebooted"
                             .format(tok.get("down", "?"), up), style="green")
                self.log_msg(body, style="dim")
            elif wake == "poweron":
                self.log_msg("BOARD POWERED ON — up {} — {}".format(up, body),
                             style="bold yellow")
            else:
                self.log_msg("BOARD (RE)BOOTED — " + body, style="bold yellow")
            return
        if msg == "FLUSH-END":
            self.log_msg("journal synced", style="dim")
            return
        if msg.startswith("J:"):
            try:
                t_ms, text = msg[2:].split(":", 1)
                if text.startswith("LOG: "):
                    text = text[5:]      # the type marker is for the soul,
                                         # not for a bench instrument
                self.log_msg("[dim]t+{:7.1f}s[/dim]  {}".format(int(t_ms) / 1000, text))
                return
            except ValueError:
                pass
        self.log_msg(msg)


if __name__ == "__main__":
    TiltTuner().run()
