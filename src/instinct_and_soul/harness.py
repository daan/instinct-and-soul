"""
harness.py — shared scaffolding for hardware tuner apps.

A tuner is a textual TUI that:
  - runs a WebSocket server for a body to connect to
  - tracks heartbeats and connection state
  - logs board messages to a panel
  - takes user commands from an input field and pushes instinct code to the board

Subclass `TuneAppBase`, override:
  - compose() — declare your widgets (typically Static + RichLog + Input).
  - on_input_submitted(event) — parse commands and push code via self.board_ws.send(...).

Optionally override:
  - INITIAL_INSTINCT — string sent on connect (e.g. an idle/sensor-stream coroutine).
  - STATUS_LABEL — text shown in the status bar (e.g. "touchy-pebble").
  - on_board_message(msg) — custom handling for non-HEARTBEAT, non-CRASH messages.

The base class handles CSS, BINDINGS, websocket server, heartbeat tracking,
log helpers, command history (up/down arrows), quit behavior, and message routing.
"""

import asyncio
import time
import websockets
from textual.app import App
from textual.widgets import RichLog, Static, Input

PORT = 8765
HEARTBEAT_TIMEOUT = 12


class TuneAppBase(App):
    CSS = """
    #status {
        dock: top;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #log {
        height: 1fr;
        border: solid $primary;
    }
    #input {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
    ]

    INITIAL_INSTINCT = None
    STATUS_LABEL = ""

    def __init__(self):
        super().__init__()
        self.board_ws = None
        self.last_heartbeat = 0.0
        self._ws_server = None
        self.cmd_history = []
        self.history_index = -1
        # locked_ip pins the session to one board. Source priority:
        # 1. INSTINCT_CREATURE_IP env var (set by `tune --creature-ip <IP>`)
        # 2. None → locks to whichever board connects first.
        import os as _os
        self.locked_ip = _os.environ.get("INSTINCT_CREATURE_IP") or None
        self._rejected_seen = set()

    def on_mount(self) -> None:
        self.run_worker(self.ws_server(), exclusive=False)
        self.set_interval(1, self.update_status)
        suffix = " — {}".format(self.STATUS_LABEL) if self.STATUS_LABEL else ""
        self.log_msg("tuner: listening on port {}{}".format(PORT, suffix))
        # mouse=False means clicks can't focus widgets, so set focus on the
        # input field at startup. Keystrokes go straight to the prompt.
        try:
            self.query_one("#input", Input).focus()
        except Exception:
            pass

    def log_msg(self, msg, style=""):
        ts = time.strftime("%H:%M:%S")
        try:
            log = self.query_one("#log", RichLog)
        except Exception:
            return
        if style:
            log.write("[{}]{}[/{}]  {}".format(style, ts, style, msg))
        else:
            log.write("{}  {}".format(ts, msg))

    def _reject(self, ip):
        if ip in self._rejected_seen:
            return
        self._rejected_seen.add(ip)
        self.log_msg("rejected board at {} (locked to {})".format(ip, self.locked_ip), style="yellow")

    def update_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except Exception:
            return
        suffix = "  {}".format(self.STATUS_LABEL) if self.STATUS_LABEL else ""
        if self.board_ws is not None and (time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT:
            status.update("[bold green]● connected[/]" + suffix)
        elif self.board_ws is not None:
            status.update("[bold yellow]● heartbeat lost[/]" + suffix)
        else:
            status.update("[bold red]● disconnected[/]" + suffix)

    def on_key(self, event) -> None:
        try:
            inp = self.query_one("#input", Input)
        except Exception:
            return
        if event.key == "up":
            if self.cmd_history and self.history_index < len(self.cmd_history) - 1:
                self.history_index += 1
                inp.value = self.cmd_history[-(self.history_index + 1)]
                inp.cursor_position = len(inp.value)
            event.prevent_default()
        elif event.key == "down":
            if self.history_index > 0:
                self.history_index -= 1
                inp.value = self.cmd_history[-(self.history_index + 1)]
                inp.cursor_position = len(inp.value)
            elif self.history_index == 0:
                self.history_index = -1
                inp.value = ""
            event.prevent_default()

    async def ws_handler(self, ws):
        self.last_heartbeat = time.time()
        addr = ws.remote_address

        # First-board-wins lock. Subclasses or callers can pre-set
        # self.locked_ip to pin the session to a specific board.
        if self.locked_ip is None:
            self.locked_ip = addr[0]
            self.log_msg("locked to board at {}".format(self.locked_ip), style="dim")
        elif addr[0] != self.locked_ip:
            self._reject(addr[0])
            await ws.close()
            return

        self.log_msg("board connected from {}:{}".format(addr[0], addr[1]), style="green")

        self.board_ws = ws

        if self.INITIAL_INSTINCT is not None:
            await ws.send(self.INITIAL_INSTINCT)
            self.log_msg("sent initial instinct", style="dim")

        try:
            async for msg in ws:
                if msg == "HEARTBEAT":
                    self.last_heartbeat = time.time()
                elif msg.startswith("CRASH:"):
                    self.log_msg(msg, style="bold red")
                else:
                    self.on_board_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self.board_ws = None
            self.log_msg("board disconnected", style="red")

    def on_board_message(self, msg):
        """Default: log the message. Override for richer parsing."""
        self.log_msg(msg)

    def key_escape(self) -> None:
        self.action_quit()

    def action_quit(self) -> None:
        if self.board_ws is not None:
            try:
                self.board_ws.transport.close()
            except Exception:
                pass
        if self._ws_server is not None:
            self._ws_server.close()
        self.exit()

    async def ws_server(self):
        try:
            self._ws_server = await websockets.serve(self.ws_handler, "0.0.0.0", PORT)
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            if self._ws_server is not None:
                self._ws_server.close()

    def run(self, *args, mouse: bool = False, **kwargs):
        # mouse=False disables Textual's mouse capture so the terminal
        # handles drag-selection — lets you copy text out of the log panel.
        return super().run(*args, mouse=mouse, **kwargs)


def format_recipe(spec, **kwargs):
    """Format a recipe template with kwargs.

    spec is a dict with keys: "args" (list of (name, type, default)) and "code" (str).
    kwargs provide values for the named args; defaults fill the rest.
    Returns the formatted code string ready to send to the board.
    Recipes with no args are returned verbatim (no .format() call).
    """
    args = spec.get("args", [])
    if not args:
        return spec["code"]
    parsed = {}
    for name, _type, default in args:
        parsed[name] = kwargs.get(name, default)
    return spec["code"].format(**parsed)
