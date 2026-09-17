"""
tune.py — interactive tuner for the desk creature.

Run:
    tune creatures/desk

Senses:
    scan                         who is on Grove Port A (the ultrasonic
                                 unit answers at 0x57)
    range [present] [absent]     the beam, raw, with the seed's gate —
                                 sit, lean back, leave, come back
    activity                     surface vibration in milli-g — hands
                                 off, then type; sets ACT_MG
    touch                        every tap should land exactly once

The desk:
    desk                         height / speed / link / whose move —
                                 press the paddle and watch
    goto <cm>                    drive the desk (the body rule applies:
                                 refused with someone within a metre)
    stop                         halt
    hand <cm>                    the PRETEND paddle: moves the VIRTUAL
                                 desk as a hand would, without touching
                                 the running instinct (a DESK: message)
    blescan [secs]               list BLE advertisers, to find DESK_MAC

Bring-up:
    deploy baseline|<path>       run the seed live, no spine needed
    tone [vol] | imulog | off
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from instinct_and_soul.spine import _fmt_uptime
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "scan | range [present] [absent] | activity | touch | desk | goto <cm> "
    "| stop | hand <cm> | blescan [s] | deploy baseline|<path> | tone [vol] "
    "| imulog | off"
)

DEPLOY_SHORTCUTS = {
    "baseline": "creatures/desk/seed_instinct.py",
}


class DeskTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "desk"

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

        def num(i, default):
            try:
                return float(parts[i]) if len(parts) > i else default
            except ValueError:
                return default

        try:
            if cmd == "hand":
                # NOT instinct code: a DESK:<mm> message the runtime routes to
                # the virtual desk's pretend paddle. The running instinct
                # keeps running and sees the height change as THEIR move.
                if len(parts) < 2:
                    self.log_msg("hand what? hand <cm>", style="yellow")
                    return
                mm = num(1, 72.0) * 10.0
                await self.board_ws.send("DESK:{:.0f}".format(mm))
                self.log_msg("pretend paddle -> {:.0f} mm".format(mm), style="cyan")
                return

            if cmd == "scan":
                code = format_recipe(RECIPES["scan"])
                self.log_msg("scanning Port A, both pin orders", style="cyan")

            elif cmd == "range":
                code = format_recipe(RECIPES["range"],
                                     present_mm=num(1, 850.0), absent_mm=num(2, 1100.0))
                self.log_msg("the beam + the seed's gate — sit, lean, leave, return",
                             style="cyan")

            elif cmd == "activity":
                code = format_recipe(RECIPES["activity"])
                self.log_msg("hands off first, then type, then mouse — ACT_MG goes "
                             "between the two", style="cyan")

            elif cmd == "touch":
                code = format_recipe(RECIPES["touch"])
                self.log_msg("tap the screen; each tap should land once", style="cyan")

            elif cmd == "desk":
                code = format_recipe(RECIPES["desk"])
                self.log_msg("desk view — press the paddle, or `goto <cm>`", style="cyan")

            elif cmd == "goto":
                if len(parts) < 2:
                    self.log_msg("goto where? goto <cm>", style="yellow")
                    return
                mm = num(1, 72.0) * 10.0
                code = format_recipe(RECIPES["goto"], mm=mm)
                self.log_msg("desk -> {:.0f} mm (refused if someone is within 1 m)"
                             .format(mm), style="cyan")

            elif cmd == "stop":
                code = format_recipe(RECIPES["stop"])
                self.log_msg("stop", style="cyan")

            elif cmd == "blescan":
                code = format_recipe(RECIPES["blescan"], secs=int(num(1, 10)))
                self.log_msg("listing BLE advertisers — look for the desk's name",
                             style="cyan")

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

            elif cmd == "tone":
                code = format_recipe(RECIPES["tone"], vol=int(num(1, 64)))
                self.log_msg("tone every 5 s; `off` to stop", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("raw IMU stream", style="cyan")

            elif cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("silenced, desk stopped", style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)

    def on_board_message(self, msg):
        if msg.startswith("BOOT:"):
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
        if msg.startswith("J:"):
            try:
                t_ms, text = msg[2:].split(":", 1)
                if text.startswith("LOG: "):
                    text = text[5:]
                self.log_msg("[dim]t+{:7.1f}s[/dim]  {}".format(int(t_ms) / 1000, text))
                return
            except ValueError:
                pass
        self.log_msg(msg)


if __name__ == "__main__":
    DeskTuner().run()
