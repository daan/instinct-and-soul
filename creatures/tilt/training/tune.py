"""
tune.py — interactive tuner for the tilt TRAINING condition.

condition_1 with the instinct's tempo hoisted into organs.py, so `set`
reaches the whole clock live: FROZEN_AFTER_S, CALL_EVERY_S, OUTCOME_S,
HUSH_WINDOW_S, HUSH_GRACE_S join the organ thresholds in TUNABLES.
Defaults ship at bench tempo (statue after 2 min). Wear condition_1, not
this — training exists to find values, condition_1 to hold them.

This body is a PLAIN StickS3 — internal speaker and IMU, nothing attached.
Two things to settle before anyone wears it for real: the CRICKET
vocabulary (trill / up / down — the test is whether you can ignore it) and
the POSTURE read on a real back.

Run:
    tune creatures/tilt/training

Posture / feedback:
    posture                      live angle/stillness stream (worn)
    setref                       capture upright (sit the way you mean it)
    verbs                        movement-verb stream (MICRO_SHIFT / SHIFT /
                                 FULL_STRETCH / MOVED_OFF) — tune the grammar
    tap                          tap-detection test (bursts + calibration peaks)

Organ calibration (the live bench — run `stetho` in a second terminal):
    stetho [ip] | stetho off     stream organ events/levels (rot_ema,
                                 posture_deg, still_s, ep_start, verbs) as
                                 UDP-OSC to the laptop's stetho dashboard;
                                 ip is auto-detected from this connection
    set <param> <value>          live-patch an organs.py threshold or a
                                 tempo constant (e.g. `set STILL_DPS 8`,
                                 `set FROZEN_AFTER_S 1200`) — takes effect
                                 without reflashing, lost on reboot; when a
                                 value feels right, write it into organs.py
                                 (thresholds) or condition_1's seed (tempo)
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
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "posture | setref | verbs | tap | stetho [ip|off] | set <param> <val> "
    "| params | cricket [1-3] [vol] | lowbat [vol] "
    "| deploy baseline|<path> | vbat | power | imulog | off"
)

# The organs.py thresholds that `set` may live-patch. Module attributes,
# read at call time by the organ — assignment takes effect immediately and
# survives instinct hot-swaps (not reboots).
TUNABLES = (
    "STILL_DPS", "GRAV_TAU_S",
    "EP_SETTLE_S", "SHIFT_DEG", "STRETCH_DEG", "AWAY_S",
    "FLAVOR_UP_DEG", "FLAVOR_FWD_DEG",
    "TAP_G", "TAP_REFRACT_S", "TAP_BURST_GAP_S",
    # instinct tempo (training only — the seed reads these live via Tempo)
    "FROZEN_AFTER_S", "CALL_EVERY_S", "OUTCOME_S",
    "HUSH_WINDOW_S", "HUSH_GRACE_S",
)

DEPLOY_SHORTCUTS = {
    "baseline": "creatures/tilt/training/seed_instinct.py",
}


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class TiltTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "tilt-training"

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
        overlay = cmd in ("set", "params", "stetho")

        try:
            if cmd == "posture":
                code = format_recipe(RECIPES["posture"])
                self.log_msg("live posture stream", style="cyan")

            elif cmd == "setref":
                code = format_recipe(RECIPES["setref"])
                self.log_msg("capturing upright in 3s — sit the way you mean it", style="cyan")

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

            elif cmd == "verbs":
                code = format_recipe(RECIPES["verbs"])
                self.log_msg("movement-verb stream — fidget, shift, stretch, walk", style="cyan")

            elif cmd == "tap":
                code = format_recipe(RECIPES["tap"])
                self.log_msg("tap test — tap the stick, watch bursts + peaks", style="cyan")

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

            elif cmd == "set":
                if len(parts) != 3:
                    self.log_msg("set <param> <value> — params: " + " ".join(TUNABLES),
                                 style="yellow")
                    return
                name = parts[1].upper()
                if name not in TUNABLES:
                    self.log_msg("unknown param {} — one of: {}".format(
                        name, " ".join(TUNABLES)), style="yellow")
                    return
                val = float(parts[2])
                code = ("import organs\n"
                        "organs.{n} = {v}\n"
                        "send('set organs.{n} = {v} (live; reboot restores "
                        "the flashed default)')\n").format(n=name, v=val) \
                       + self._stream_code
                self.log_msg("organs.{} = {} — stream resumes".format(name, val),
                             style="cyan")

            elif cmd == "params":
                code = ("import organs\n"
                        "send('params: ' + ' '.join('{}={}'.format(n, getattr(organs, n)) "
                        "for n in " + repr(list(TUNABLES)) + "))\n") + self._stream_code
                self.log_msg("reading live organ params", style="cyan")

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
            self.log_msg("BOARD (RE)BOOTED — " + msg[5:].strip(), style="bold yellow")
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
