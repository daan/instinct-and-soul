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
from .reflection import REFLECT_PREFIX, Creature, ReflectionLoop

PORT = 8765
HEARTBEAT_TIMEOUT = 12   # default; a BOOT announcing keepalive=N stretches it


def fmt_tokens(n):
    if n >= 1000:
        return "{:.1f}K".format(n / 1000)
    return str(n)


def _fmt_uptime(seconds):
    """A device's uptime, readable. This is the field that says whether a
    BOOT: line means the board actually rebooted — cause= cannot, being
    frozen at the last real reset, and the announce is sent on every connect."""
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "{}s".format(seconds)
    if seconds < 5400:
        return "{:.0f}m".format(seconds / 60)
    return "{:.1f}h".format(seconds / 3600)


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

    def __init__(self, creature, resume=False, llm=None, llm_info=None, creature_ip=None,
                 max_reflections=None):
        super().__init__()
        self.creature = creature
        self.board_ws = None
        self.last_heartbeat = 0.0
        self._ws_server = None
        self.locked_ip = creature_ip
        self._rejected_seen = set()
        # Batch-mode devices announce themselves in BOOT (mode=batch,
        # keepalive=N, iv=<instinct version they run>): the spine adapts its
        # heartbeat timeout, skips redundant instinct pushes, and answers
        # FLUSH-END with NAP once any pending reflection has completed.
        self.device_batch = False
        self.device_napping = False
        self.hb_timeout = HEARTBEAT_TIMEOUT
        # Does this runtime track its instinct version? Signalled by an iv=
        # token in its BOOT line; older runtimes have no IV: handler and would
        # exec the message as instinct code.
        self.device_iv_capable = False
        # Have we deployed to this device yet in THIS spine session? Until we
        # have, a matching iv= means nothing — the device could be carrying a
        # same-numbered instinct from a previous session (v1 is the seed in
        # every session), and the seed on disk may have changed since.
        self.deployed_this_session = False

        self.loop = ReflectionLoop(
            creature, llm,
            llm_info=llm_info or {},
            resume=resume,
            provenance="device",
            on_log=self._loop_log,
            on_intent=self._loop_intent,
            on_instinct_deploy=self._loop_deploy,
            on_status_change=self.update_status,
            max_reflections=max_reflections,
            # The device spine's defining rule: journalling is not asking.
            journal_triggers=False,
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
                if self.device_iv_capable:
                    # the runtime records this as the version it runs, and
                    # announces it as iv= in its next BOOT — which is what
                    # lets a reconnect skip the push instead of restarting
                    # the creature (batch: also skips a re-push on wake)
                    await self.board_ws.send("IV:{}".format(version))
                await self.board_ws.send(code)
                self.log_msg("deployed new instinct v{}".format(version), style="cyan")
            except Exception as e:
                self.log_msg("send failed: {}".format(e), style="bold red")
        else:
            self.log_msg("instinct v{} saved (no board to deploy to)".format(version), style="dim")

    # ── Reflection scheduling ─────────────────────────────────────────

    async def _send_time(self, ws) -> None:
        """The animal gets the hour: laptop clock + tz, one message. Only
        runtimes that advertise mode= parse TIME:; older ones would exec it
        as instinct code. Logged, because a silently missing clock leaves
        every journal entry stamped t+Nm and nothing says why."""
        lt = time.localtime()
        gmtoff = getattr(lt, "tm_gmtoff", 0) or 0
        try:
            await ws.send("TIME:{}:{}".format(int(time.time()), gmtoff))
            self.log_msg("sent clock {} (gmtoff {}s)".format(
                time.strftime("%H:%M:%S", lt), gmtoff), style="dim")
        except Exception as e:
            self.log_msg("clock send failed: {}".format(e), style="bold red")

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
        if self.board_ws is not None and (time.time() - self.last_heartbeat) < self.hb_timeout:
            extra = "  [dim]reflecting...[/dim]" if self.loop.reflecting else ""
            status.update("[bold green]● connected[/]  {}{}".format(prefix, extra))
        elif self.board_ws is not None:
            status.update("[bold yellow]● heartbeat lost[/]  {}".format(prefix))
        elif self.device_napping:
            status.update("[bold cyan]● napping (batch)[/]  {}".format(prefix))
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
        self.device_napping = False

        # Send session id first so the device can detect a fresh-spine restart
        # vs a same-session reconnect / reflection update. On --resume we send
        # the resumed-from id so the device treats it as a continuation.
        session_id = self.loop.resumed_from or self.loop.session_id
        await ws.send("SESSION:" + session_id)

        # Wait briefly for the device to introduce itself (new runtimes send
        # BOOT immediately). A batch device announcing the current instinct
        # version gets no redundant push; anything else gets the instinct as
        # before. Legacy boards that say nothing hit the 2 s timeout.
        first = None
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass
        device_iv = None
        device_uptime = None
        if isinstance(first, str) and first.startswith("BOOT:"):
            self.device_batch = "mode=batch" in first
            for tok in first.split():
                if tok.startswith("keepalive="):
                    try:
                        self.hb_timeout = max(HEARTBEAT_TIMEOUT, 2.5 * int(tok[10:]))
                    except ValueError:
                        pass
                elif tok.startswith("iv="):
                    try:
                        device_iv = int(tok[3:])
                    except ValueError:
                        pass
                elif tok.startswith("uptime="):
                    try:
                        device_uptime = int(tok[7:].rstrip("s"))
                    except ValueError:
                        pass
        # The animal gets the hour: laptop clock + tz, one message. Gated on
        # the runtime advertising a mode= token, which is exactly the family
        # that parses TIME: explicitly — older runtimes have no handler and
        # would exec the message as instinct code. This used to be gated on
        # `device_batch`, which silently denied the clock to the same runtime
        # running live, leaving it with boot-relative time only.
        if isinstance(first, str) and "mode=" in first:
            await self._send_time(ws)
        elif isinstance(first, str):
            # BOOT did not arrive first — a HEARTBEAT can beat it, since the
            # device's heartbeat task runs independently of the connect
            # sequence. The receive loop re-checks every BOOT: it sees, so
            # the clock still lands; say so rather than failing silently.
            self.log_msg("no BOOT in the first frame ({}...) — waiting for it "
                         "to send the clock".format(str(first)[:24]), style="dim")
        self.device_iv_capable = device_iv is not None
        # A RECONNECT must not restart the creature. Pushing the instinct calls
        # swap_instinct on the device, which restarts run() and wipes every
        # local it holds — an open chirp awaiting its outcome, the still/moving
        # state, the ignored-chirp counter. Walking out of WiFi range and back
        # should cost nothing. Batch runtimes always had this skip; live ones
        # never did, because the IV: that teaches a device its own version was
        # itself gated on batch, so a live device reported iv=0 forever and
        # never matched.
        if (self.deployed_this_session and self.device_iv_capable
                and device_iv == self.loop.instinct_version):
            # State the OUTCOME, not the mechanism. A BOOT: line is sent on
            # every connect and its cause= is frozen at the device's last real
            # reset, so "BOOT" reads as "it rebooted" when usually it did not.
            # Say plainly whether the creature is still running.
            self.log_msg(
                "reconnected — board up {}, instinct v{}, creature NOT "
                "restarted".format(_fmt_uptime(device_uptime), device_iv),
                style="bold green")
        else:
            if self.device_iv_capable:
                await ws.send("IV:{}".format(self.loop.instinct_version))
            await ws.send(self.loop.current_instinct)
            # Name why the creature is about to restart, so a restart is never
            # something the reader has to infer from a missing line.
            if not self.device_iv_capable:
                why = "runtime does not track versions"
            elif device_uptime is not None and device_uptime < 60:
                why = "board just powered on"
            elif device_iv != self.loop.instinct_version:
                why = "board had v{}".format(device_iv)
            else:
                why = "first deploy of this session"
            self.deployed_this_session = True
            self.log_msg("sent instinct v{} — creature RESTARTED ({})".format(
                self.loop.instinct_version, why), style="bold yellow")

        try:
            pending = [first] if first is not None else []
            while True:
                msg = pending.pop(0) if pending else await ws.recv()
                if msg == "HEARTBEAT":
                    self.last_heartbeat = time.time()
                elif msg == "FLUSH-END":
                    self.run_worker(self._flush_ack(ws), exclusive=False)
                elif msg.startswith("J:"):
                    # buffered journal line: J:<device_t_ms>:<text>
                    try:
                        t_ms, text = msg[2:].split(":", 1)
                        stamp = "[t+{:.0f}s]".format(int(t_ms) / 1000)
                    except ValueError:
                        stamp, text = "", msg[2:]
                    if text.startswith("CRASH:"):
                        self.log_msg("{} {}".format(stamp, text), style="bold red")
                        self.loop.add_crash(text)
                    else:
                        self.log_msg("{} {}".format(stamp, text), style="dim")
                        self.loop.add_message(text)
                        # A replayed request registers the trigger but does
                        # NOT schedule here: the batch handshake is driven by
                        # FLUSH-END, which reflects once and then NAPs.
                        if text.startswith(REFLECT_PREFIX):
                            self.loop.add_reflect_request(
                                text[len(REFLECT_PREFIX):].strip())
                elif msg.startswith("CRASH:"):
                    self.log_msg(msg, style="bold red")
                    self.loop.add_crash(msg)
                    self._schedule_reflect()
                elif msg.startswith("MEM:"):
                    self.loop.add_memory_snapshot(msg[4:])
                elif msg.startswith("BOOT:"):
                    # A BOOT can arrive here rather than as the first frame
                    # (a HEARTBEAT can beat it), and it arrives again on every
                    # device reboot mid-session. Either way the RTC is now
                    # unset, so re-send the clock — this is what keeps journal
                    # entries stamped with the hour instead of t+Nm.
                    self.log_msg(msg, style="bold yellow")
                    self.loop.add_message(msg)
                    self.device_batch = "mode=batch" in msg
                    if "mode=" in msg:
                        await self._send_time(ws)
                else:
                    self.loop.add_message(msg)
                    # THE trigger. Journal traffic alone no longer reflects —
                    # the creature has to ask, and say why.
                    if msg.startswith(REFLECT_PREFIX):
                        reason = msg[len(REFLECT_PREFIX):].strip()
                        self.log_msg(msg, style="bold yellow")
                        self.loop.add_reflect_request(reason)
                        self._schedule_reflect()
                    else:
                        self.log_msg(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            # Only the handler that still owns board_ws may clear it: a
            # fast-reconnecting board registers its new connection before
            # the old handler unwinds (same race as the tuner harness).
            if self.board_ws is ws:
                self.board_ws = None
                if self.device_batch:
                    self.device_napping = True
                    self.log_msg("board napping (batch) — next wake by its own clock", style="cyan")
                else:
                    self.log_msg("board disconnected", style="red")
            else:
                self.log_msg("stale connection closed (board reconnected)", style="dim")

    async def _flush_ack(self, ws):
        """The batch handshake: journal synced -> reflect if warranted ->
        NAP. The device holds its radio up until the NAP (or a fresh
        instinct) arrives, then sleeps."""
        reflected = False
        if self.loop.needs_reflection():
            await self._reflect_with_refire()
            reflected = True
        try:
            await ws.send("NAP")
            self.log_msg("→ NAP{}".format(" (after reflection)" if reflected else ""),
                         style="cyan")
        except Exception:
            pass

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
    parser.add_argument("--max-reflections", type=int, default=None, metavar="N",
                        help="Hard cap on LLM reflections this session. 0 = no LLM "
                             "at all: deploy the seed and just journal (the feel-gate "
                             "mode, mirroring sim-spine).")
    args = parser.parse_args()
    creature = Creature(args.creature_path)
    llm, llm_info = load_llm(args.llm)
    # mouse=False disables Textual's mouse capture so the terminal can
    # handle drag-selection — lets you copy text out of the log panel.
    SpineApp(creature=creature, resume=args.resume,
             llm=llm, llm_info=llm_info,
             creature_ip=args.creature_ip,
             max_reflections=args.max_reflections).run(mouse=False)


if __name__ == "__main__":
    main()
