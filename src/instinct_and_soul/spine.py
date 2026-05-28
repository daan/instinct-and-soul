"""spine.py — the embodied-prompting spine: textual TUI + websocket relay.

The reflection cycle and per-session bookkeeping live in ReflectionLoop
(reflection.py). This module is the host adapter: it accepts a websocket
connection from a creature's body, routes messages into the loop, fires
reflections, and renders status/intent/log into a terminal UI.

Usage:
  spine creatures/touchy-pebble            # fresh session
  spine creatures/touchy-pebble --resume   # continue last session
"""
import argparse
import asyncio
import os
import time

import websockets
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static

from .llm import load_llm
from .reflection import Creature, ReflectionLoop

PORT = 8765
HEARTBEAT_TIMEOUT = 12


def fmt_tokens(n):
    if n >= 1000:
        return "{:.1f}K".format(n / 1000)
    return str(n)


class SpineApp(App):
    CSS = """
    #status {
        dock: top;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #intent {
        height: auto;
        max-height: 5;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    #log {
        height: 1fr;
        border: solid $primary;
    }
    #operator-input {
        dock: bottom;
        height: 3;
    }
    /* Cue the operator that we're mid-reflection — their input will queue
       (not be dropped, since spare_operator=True), but won't be seen until
       this reflection completes. */
    #operator-input.reflecting {
        background: $accent 20%;
        border: tall $accent;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit"), ("escape", "quit", "Quit"), ("ctrl+q", "quit", "Quit")]

    def __init__(self, creature, resume=False, llm=None, llm_info=None, creature_ip=None):
        super().__init__()
        self.creature = creature
        self.board_ws = None
        self.last_heartbeat = 0.0
        self._ws_server = None
        self.locked_ip = creature_ip
        self._rejected_seen = set()

        self.loop = ReflectionLoop(
            creature, llm,
            llm_info=llm_info or {},
            resume=resume,
            provenance="device",
            on_log=self._loop_log,
            on_intent=self._loop_intent,
            on_instinct_deploy=self._loop_deploy,
            on_status_change=self.update_status,
        )

    # ── Textual lifecycle ─────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("● disconnected", id="status")
        yield Static("[dim](no intent yet)[/]", id="intent")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder="operator: type a message and press enter", id="operator-input")

    def on_mount(self) -> None:
        self.run_worker(self.ws_server(), exclusive=False)
        self.set_interval(1, self.update_status)
        self.log_msg("creature: {}".format(self.creature.name), style="bold")
        self.log_msg("session: {}".format(self.loop.session_id), style="bold")
        llm_label = self.loop.llm_info.get("llm") or "{}/{}".format(
            self.loop.llm_info.get("api"), self.loop.llm_info.get("model"))
        self.log_msg("llm: {}".format(llm_label), style="bold")
        if self.loop.resumed_from:
            self.log_msg("resumed from: {}".format(self.loop.resumed_from), style="cyan")
        self.log_msg("spine: listening on port {}".format(PORT))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.loop.add_operator(text)
        self.log_msg("OPERATOR: " + text, style="bold cyan")
        self._schedule_reflect()

    def action_quit(self) -> None:
        try:
            self.workers.cancel_all()
        except Exception:
            pass
        if self.board_ws is not None:
            try:
                self.board_ws.transport.close()
            except Exception:
                pass
        if self._ws_server is not None:
            self._ws_server.close()
        self.exit()

    def key_escape(self) -> None:
        self.action_quit()

    # ── ReflectionLoop callbacks ──────────────────────────────────────

    def _loop_log(self, msg: str, style: str = None) -> None:
        self.log_msg(msg, style=style or "")

    def _loop_intent(self, intent: str, ts: float) -> None:
        try:
            time_str = time.strftime("%H:%M:%S", time.localtime(ts))
            self.query_one("#intent", Static).update(
                "[bold magenta]intent[/] [dim]{}[/]\n{}".format(time_str, intent))
        except Exception:
            pass

    async def _loop_deploy(self, code: str, version: int) -> None:
        if self.board_ws is not None:
            try:
                await self.board_ws.send(code)
                self.log_msg("deployed new instinct v{}".format(version), style="cyan")
            except Exception as e:
                self.log_msg("send failed: {}".format(e), style="bold red")
        else:
            self.log_msg("instinct v{} saved (no board to deploy to)".format(version), style="dim")

    # ── Reflection scheduling ─────────────────────────────────────────

    def _schedule_reflect(self) -> None:
        if self.loop.needs_reflection():
            self.run_worker(self._reflect_with_refire(), exclusive=False)

    async def _reflect_with_refire(self) -> None:
        await self.loop.reflect()
        # Messages or crashes may have arrived during reflection.
        if self.loop.needs_reflection():
            self.run_worker(self._reflect_with_refire(), exclusive=False)

    # ── UI helpers ────────────────────────────────────────────────────

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
        try:
            inp = self.query_one("#operator-input", Input)
            if self.loop.reflecting:
                inp.add_class("reflecting")
                inp.placeholder = "in reflection — your input will queue"
            else:
                inp.remove_class("reflecting")
                inp.placeholder = "operator: type a message and press enter"
        except Exception:
            pass

        resume_info = " [cyan]← {}[/cyan]".format(self.loop.resumed_from) if self.loop.resumed_from else ""
        usage_info = ""
        if self.loop.session_usage["reflections"] > 0:
            in_total = (self.loop.session_usage["input_tokens_total"]
                        + self.loop.session_usage["cache_read_input_tokens_total"]
                        + self.loop.session_usage["cache_creation_input_tokens_total"])
            out_total = self.loop.session_usage["output_tokens_total"]
            cost = self.loop.session_usage["cost_total"]
            usage_info = "  · {} in / {} out · ${:.2f}".format(
                fmt_tokens(in_total), fmt_tokens(out_total), cost)
        prefix = "{}{}{}".format(self.creature.name, resume_info, usage_info)
        if self.board_ws is not None and (time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT:
            extra = "  [dim]reflecting...[/dim]" if self.loop.reflecting else ""
            status.update("[bold green]● connected[/]  {}{}".format(prefix, extra))
        elif self.board_ws is not None:
            status.update("[bold yellow]● heartbeat lost[/]  {}".format(prefix))
        else:
            status.update("[bold red]● disconnected[/]  {}".format(prefix))

    # ── Websocket handlers ────────────────────────────────────────────

    async def ws_handler(self, ws):
        self.last_heartbeat = time.time()
        addr = ws.remote_address

        if self.locked_ip is None:
            self.locked_ip = addr[0]
            self.log_msg("locked to board at {}".format(self.locked_ip), style="dim")
        elif addr[0] != self.locked_ip:
            self._reject(addr[0])
            await ws.close()
            return

        self.log_msg("board connected from {}:{}".format(addr[0], addr[1]), style="green")
        self.board_ws = ws

        # Send session id first so the device can detect a fresh-spine restart
        # vs a same-session reconnect / reflection update. On --resume we send
        # the resumed-from id so the device treats it as a continuation.
        session_id = self.loop.resumed_from or self.loop.session_id
        await ws.send("SESSION:" + session_id)

        await ws.send(self.loop.current_instinct)
        self.log_msg("sent instinct v{}".format(self.loop.instinct_version), style="dim")

        try:
            async for msg in ws:
                if msg == "HEARTBEAT":
                    self.last_heartbeat = time.time()
                elif msg.startswith("CRASH:"):
                    self.log_msg(msg, style="bold red")
                    self.loop.add_crash(msg)
                    self._schedule_reflect()
                elif msg.startswith("MEM:"):
                    self.loop.add_memory_snapshot(msg[4:])
                else:
                    self.log_msg(msg)
                    self.loop.add_message(msg)
                    self._schedule_reflect()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self.board_ws = None
            self.log_msg("board disconnected", style="red")

    async def ws_server(self):
        try:
            self._ws_server = await websockets.serve(
                self.ws_handler, "0.0.0.0", PORT, close_timeout=0.5)
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            if self._ws_server is not None:
                self._ws_server.close()


def main():
    parser = argparse.ArgumentParser(description="Embodied-prompting spine")
    parser.add_argument("creature_path",
                        help="Path to the creature directory (e.g. creatures/touchy-pebble)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from the last session's final experience/instinct")
    parser.add_argument("--llm", default=None, metavar="NAME",
                        help="LLM profile to use, read from .config/llm/<NAME>.toml. "
                             "Overrides the default in .config/config.toml.")
    parser.add_argument("--creature-ip", default=None, metavar="IP",
                        help="Only accept connections from this board IP. "
                             "If omitted, locks to whichever board connects first.")
    args = parser.parse_args()
    creature = Creature(args.creature_path)
    llm, llm_info = load_llm(args.llm)
    # mouse=False disables Textual's mouse capture so the terminal can
    # handle drag-selection — lets you copy text out of the log panel.
    SpineApp(creature=creature, resume=args.resume,
             llm=llm, llm_info=llm_info,
             creature_ip=args.creature_ip).run(mouse=False)


if __name__ == "__main__":
    main()
