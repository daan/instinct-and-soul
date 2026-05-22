"""
spine.py — the embodied-prompting spine with textual terminal UI and Claude reflection.

Accepts a WebSocket connection from a creature's body, accumulates messages,
calls Claude for reflection, and deploys updated instinct code back.

A creature is a folder under creatures/ containing:
  system_prompt.md   — hardware truth, given to Claude as system prompt
  character.md       — the creature's desire / goal
  seed_experience.md — initial personality, used on first session
  seed_instinct.py   — initial instinct code, deployed to the body
  logs/              — per-session subfolders written by the spine

Usage:
  spine creatures/touchy-pebble            # fresh session
  spine creatures/touchy-pebble --resume   # continue last session

Requires: pip install websockets textual anthropic openai
"""

import argparse
import asyncio
import glob
import json
import os
import re
import time
import websockets
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static

from .llm import load_llm, compute_cost

PORT = 8765
HEARTBEAT_TIMEOUT = 12


def fmt_tokens(n):
    """Format token count as '4.5K' or '127'."""
    if n >= 1000:
        return "{:.1f}K".format(n / 1000)
    return str(n)

# ── Creature loading ───────────────────────────────────────────────────────

class Creature:
    """A creature on disk: its prompts, seeds, and log directory."""

    def __init__(self, path):
        self.path = os.path.normpath(path)
        self.name = os.path.basename(self.path)
        self.system_prompt = self._read("system_prompt.md")
        self.character = self._read("character.md").strip()
        self.seed_experience = self._read("seed_experience.md")
        self.seed_instinct = self._read("seed_instinct.py")
        self.logs_dir = os.path.join(self.path, "logs")

    def _read(self, name):
        p = os.path.join(self.path, name)
        if not os.path.isfile(p):
            raise FileNotFoundError("missing {} in creature {}".format(name, self.path))
        with open(p) as f:
            return f.read()


# ── XML parsing ────────────────────────────────────────────────────────────

def extract_xml_tag(text, tag):
    """Extract content of an XML tag from text. Returns None if not found."""
    m = re.search(r"<{0}>(.*?)</{0}>".format(tag), text, re.DOTALL)
    return m.group(1).strip() if m else None


# ── Session management ─────────────────────────────────────────────────────

def find_last_session(logs_dir):
    """Find the most recent session directory inside a creature's logs/."""
    if not os.path.isdir(logs_dir):
        return None
    sessions = sorted(
        d for d in os.listdir(logs_dir)
        if os.path.isdir(os.path.join(logs_dir, d))
    )
    return os.path.join(logs_dir, sessions[-1]) if sessions else None


def load_last_state(session_dir):
    """Load the final experience and instinct from a session directory."""
    experience = None
    instinct = None

    # Prefer the new "experience" subdir; fall back to legacy "soul" so that
    # sessions written before the rename can still be resumed.
    exp_files = sorted(glob.glob(os.path.join(session_dir, "experience", "*.md")))
    if not exp_files:
        exp_files = sorted(glob.glob(os.path.join(session_dir, "soul", "*.md")))
    if exp_files:
        with open(exp_files[-1]) as f:
            experience = f.read()

    instinct_files = sorted(glob.glob(os.path.join(session_dir, "instinct", "*.py")))
    if instinct_files:
        with open(instinct_files[-1]) as f:
            instinct = f.read()

    return experience, instinct


# ── Versioning ─────────────────────────────────────────────────────────────

class VersionStore:
    """Saves instinct, experience, and reflection files to a session directory."""

    def __init__(self, logs_dir):
        session_id = time.strftime("%Y%m%d_%H%M%S")
        self.base = os.path.join(logs_dir, session_id)
        self.session_id = session_id
        self.seq = 0
        for subdir in ("instinct", "experience", "reflections", "crashes", "memory"):
            os.makedirs(os.path.join(self.base, subdir), exist_ok=True)

    def save_session_config(self, system_prompt, character, llm_info=None, resumed_from=None):
        path = os.path.join(self.base, "session.json")
        with open(path, "w") as f:
            json.dump({
                "session_id": self.session_id,
                "ts": int(time.time()),
                "resumed_from": resumed_from,
                "llm": llm_info,
                "system_prompt": system_prompt,
                "character": character,
            }, f, indent=2)
        return path

    def save_seeds(self, creature):
        # Snapshot the creature's editable inputs into the session dir so
        # we can correlate behaviour changes to edits made during development.
        for name, content in (
            ("character.md", creature.character),
            ("system_prompt.md", creature.system_prompt),
            ("seed_experience.md", creature.seed_experience),
            ("seed_instinct.py", creature.seed_instinct),
        ):
            with open(os.path.join(self.base, name), "w") as f:
                f.write(content)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def save_instinct(self, seq, code):
        path = os.path.join(self.base, "instinct", "{:03d}_{}.py".format(seq, int(time.time())))
        with open(path, "w") as f:
            f.write(code)
        return path

    def save_experience(self, seq, text):
        path = os.path.join(self.base, "experience", "{:03d}_{}.md".format(seq, int(time.time())))
        with open(path, "w") as f:
            f.write(text)
        return path

    def save_reflection(self, seq, data):
        path = os.path.join(self.base, "reflections", "{:03d}_{}.json".format(seq, int(time.time())))
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def save_usage(self, totals):
        path = os.path.join(self.base, "usage.json")
        with open(path, "w") as f:
            json.dump(totals, f, indent=2)
        return path

    def save_crash(self, seq, error):
        path = os.path.join(self.base, "crashes", "{:03d}_{}.txt".format(seq, int(time.time())))
        with open(path, "w") as f:
            f.write(error)
        return path

    def save_memory(self, seq, payload):
        path = os.path.join(self.base, "memory", "{:03d}_{}.json".format(seq, int(time.time())))
        with open(path, "w") as f:
            f.write(payload)
        return path

    def save_operator_command(self, text):
        path = os.path.join(self.base, "operator.log")
        with open(path, "a") as f:
            f.write("{}\t{}\n".format(int(time.time()), text))
        return path


# ── App ────────────────────────────────────────────────────────────────────

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
    """

    BINDINGS = [("ctrl+c", "quit", "Quit"), ("escape", "quit", "Quit"), ("ctrl+q", "quit", "Quit")]

    def __init__(self, creature, resume=False, llm=None, llm_info=None):
        super().__init__()
        self.creature = creature
        self.llm = llm
        self.llm_info = llm_info or {}
        self.model = self.llm_info.get("model")
        self.board_ws = None
        self.last_heartbeat = 0.0
        self._ws_server = None

        # Resume state must be loaded BEFORE VersionStore creates the new
        # session dir, otherwise find_last_session() picks up the just-created
        # (empty) directory as "most recent" and the resume silently no-ops.
        self.current_experience = creature.seed_experience
        self.current_instinct = creature.seed_instinct
        self.resumed_from = None

        if resume:
            last = find_last_session(creature.logs_dir)
            if last:
                experience, instinct = load_last_state(last)
                if experience:
                    self.current_experience = experience
                if instinct:
                    self.current_instinct = instinct
                self.resumed_from = os.path.basename(last)

        self.store = VersionStore(creature.logs_dir)

        self.instinct_version = 0
        self.experience_version = 0
        self.messages_since_last = []
        self.last_crashed = False
        self.last_crash_msg = ""
        self.reflecting = False
        self.session_usage = {
            "llm": self.llm_info,
            "started_at": int(time.time()),
            "updated_at": int(time.time()),
            "reflections": 0,
            "input_tokens_total": 0,
            "cache_read_input_tokens_total": 0,
            "cache_creation_input_tokens_total": 0,
            "output_tokens_total": 0,
            "cost_total": 0.0,
        }

        # save session config and initial state
        self.store.save_session_config(creature.system_prompt, creature.character, self.llm_info, self.resumed_from)
        self.store.save_seeds(creature)
        seq = self.store.next_seq()
        self.instinct_version = seq
        self.store.save_instinct(seq, self.current_instinct)
        seq = self.store.next_seq()
        self.experience_version = seq
        self.store.save_experience(seq, self.current_experience)

    def compose(self) -> ComposeResult:
        yield Static("● disconnected", id="status")
        yield Static("[dim](no intent yet)[/]", id="intent")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder="operator: type a message and press enter", id="operator-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        tagged = "OPERATOR: " + text
        self.store.save_operator_command(text)
        self.log_msg(tagged, style="bold cyan")
        self.messages_since_last.append({
            "ts": int(time.time()),
            "content": tagged,
        })
        if not self.reflecting:
            self.run_worker(self.reflect(), exclusive=False)

    def on_mount(self) -> None:
        self.run_worker(self.ws_server(), exclusive=False)
        self.set_interval(1, self.update_status)
        self.log_msg("creature: {}".format(self.creature.name), style="bold")
        self.log_msg("session: {}".format(self.store.session_id), style="bold")
        llm_label = self.llm_info.get("llm") or "{}/{}".format(
            self.llm_info.get("api"), self.llm_info.get("model"))
        self.log_msg("llm: {}".format(llm_label), style="bold")
        if self.resumed_from:
            self.log_msg("resumed from: {}".format(self.resumed_from), style="cyan")
        self.log_msg("spine: listening on port {}".format(PORT))

    async def call_llm(self, system_prompt, user_message):
        """Delegate to the active LLMClient. Returns {"text", "usage"}."""
        return await self.llm.call(system_prompt, user_message)

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

    def update_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except Exception:
            return
        resume_info = " [cyan]← {}[/cyan]".format(self.resumed_from) if self.resumed_from else ""
        usage_info = ""
        if self.session_usage["reflections"] > 0:
            in_total = (self.session_usage["input_tokens_total"]
                        + self.session_usage["cache_read_input_tokens_total"]
                        + self.session_usage["cache_creation_input_tokens_total"])
            out_total = self.session_usage["output_tokens_total"]
            cost = self.session_usage["cost_total"]
            usage_info = "  · {} in / {} out · ${:.2f}".format(
                fmt_tokens(in_total), fmt_tokens(out_total), cost)
        prefix = "{}{}{}".format(self.creature.name, resume_info, usage_info)
        if self.board_ws is not None and (time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT:
            extra = "  [dim]reflecting...[/dim]" if self.reflecting else ""
            status.update("[bold green]● connected[/]  {}{}".format(prefix, extra))
        elif self.board_ws is not None:
            status.update("[bold yellow]● heartbeat lost[/]  {}".format(prefix))
        else:
            status.update("[bold red]● disconnected[/]  {}".format(prefix))

    async def ws_handler(self, ws):
        self.board_ws = ws
        self.last_heartbeat = time.time()
        addr = ws.remote_address
        self.log_msg("board connected from {}:{}".format(addr[0], addr[1]), style="green")

        # Send session id first so the device can detect a fresh-spine
        # restart vs a same-session reconnect / reflection update.
        # On --resume we send the resumed-from id, so the device treats
        # it as a continuation and doesn't clear screen/actuators.
        session_id = self.resumed_from or self.store.session_id
        await ws.send("SESSION:" + session_id)

        await ws.send(self.current_instinct)
        self.log_msg("sent instinct v{}".format(self.instinct_version), style="dim")

        try:
            async for msg in ws:
                if msg == "HEARTBEAT":
                    self.last_heartbeat = time.time()
                elif msg.startswith("CRASH:"):
                    self.log_msg(msg, style="bold red")
                    self.last_crashed = True
                    self.last_crash_msg = msg
                    self.store.save_crash(self.store.next_seq(), msg)
                    if not self.reflecting:
                        self.run_worker(self.reflect(), exclusive=False)
                elif msg.startswith("MEM:"):
                    self.store.save_memory(self.store.next_seq(), msg[4:])
                else:
                    self.log_msg(msg)
                    self.messages_since_last.append({
                        "ts": int(time.time()),
                        "content": msg,
                    })
                    if not self.reflecting:
                        self.run_worker(self.reflect(), exclusive=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self.board_ws = None
            self.log_msg("board disconnected", style="red")

    async def reflect(self):
        """Call Claude with the reflection prompt, parse response, act on it."""
        self.reflecting = True

        # snapshot and clear message buffer
        messages = list(self.messages_since_last)
        self.messages_since_last.clear()
        crashed = self.last_crashed
        crash_msg = self.last_crash_msg
        self.last_crashed = False
        self.last_crash_msg = ""

        # build reflection prompt
        messages_xml = "\n".join(
            "  [{ts}] {content}".format(**m) for m in messages
        )
        crashed_xml = "true\n{}".format(crash_msg) if crashed else "false"

        reflection_prompt = (
            "<character>{character}</character>\n"
            "<experience>{experience}</experience>\n"
            "<instinct>{instinct}</instinct>\n"
            "<crashed>{crashed}</crashed>\n"
            "<messages>\n{messages}\n</messages>"
        ).format(
            character=self.creature.character,
            experience=self.current_experience,
            instinct=self.current_instinct,
            crashed=crashed_xml,
            messages=messages_xml,
        )

        self.log_msg("reflecting ({} messages)...".format(len(messages)), style="dim")

        try:
            result = await self.call_llm(self.creature.system_prompt, reflection_prompt)
            reply = result["text"]
            usage = result["usage"]

            # update running session totals + write usage.json
            self.session_usage["reflections"] += 1
            self.session_usage["input_tokens_total"] += usage["input_tokens"]
            self.session_usage["cache_read_input_tokens_total"] += usage["cache_read_input_tokens"]
            self.session_usage["cache_creation_input_tokens_total"] += usage["cache_creation_input_tokens"]
            self.session_usage["output_tokens_total"] += usage["output_tokens"]
            cost_inc = compute_cost(self.model, usage)
            if cost_inc is not None:
                self.session_usage["cost_total"] += cost_inc
            self.session_usage["updated_at"] = int(time.time())
            self.store.save_usage(self.session_usage)

            # log per-reflection summary
            input_total = (usage["input_tokens"] + usage["cache_read_input_tokens"]
                           + usage["cache_creation_input_tokens"])
            cache_str = ""
            if usage["cache_read_input_tokens"] > 0:
                cache_str = " ({} cached)".format(fmt_tokens(usage["cache_read_input_tokens"]))
            cost_str = " · ${:.4f}".format(cost_inc) if cost_inc is not None else ""
            self.log_msg("reflected: {} in{} / {} out{}".format(
                fmt_tokens(input_total), cache_str,
                fmt_tokens(usage["output_tokens"]), cost_str), style="dim")

            intent = extract_xml_tag(reply, "intent")
            new_experience = extract_xml_tag(reply, "experience")
            new_instinct = extract_xml_tag(reply, "instinct")

            if not intent:
                self.log_msg("soul: no intent in response", style="bold red")
                self.reflecting = False
                return

            self.log_msg("intent: {}".format(intent), style="bold magenta")
            try:
                ts = time.strftime("%H:%M:%S")
                self.query_one("#intent", Static).update(
                    "[bold magenta]intent[/] [dim]{}[/]\n{}".format(ts, intent))
            except Exception:
                pass

            # build reflection record
            seq = self.store.next_seq()
            reflection = {
                "seq": seq,
                "ts": int(time.time()),
                "messages_since_last": messages,
                "instinct_version_in": self.instinct_version,
                "crashed": crashed,
                "intent": intent,
                "instinct_changed": new_instinct is not None,
                "experience_changed": new_experience is not None,
                "usage": usage,
                "prompt": reflection_prompt,
                "response": reply,
            }

            if new_instinct is not None:
                self.current_instinct = new_instinct
                iseq = self.store.next_seq()
                self.instinct_version = iseq
                self.store.save_instinct(iseq, new_instinct)
                reflection["instinct_version_out"] = iseq

                if self.board_ws is not None:
                    await self.board_ws.send(new_instinct)
                    self.log_msg("deployed new instinct v{}".format(iseq), style="cyan")

            if new_experience is not None:
                self.current_experience = new_experience
                eseq = self.store.next_seq()
                self.experience_version = eseq
                self.store.save_experience(eseq, new_experience)
                reflection["experience_version_out"] = eseq
                self.log_msg("updated experience v{}".format(eseq), style="cyan")

            self.store.save_reflection(seq, reflection)

        except Exception as e:
            self.log_msg("reflection error: {}".format(e), style="bold red")
        finally:
            self.reflecting = False
            # A crash or new messages may have arrived during this reflection;
            # re-fire so the soul gets to see them.
            if self.last_crashed or self.messages_since_last:
                self.run_worker(self.reflect(), exclusive=False)

    def key_escape(self) -> None:
        self.action_quit()

    def action_quit(self) -> None:
        if self.board_ws is not None:
            self.board_ws.transport.close()
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


def main():
    parser = argparse.ArgumentParser(description="Embodied-prompting spine")
    parser.add_argument("creature_path",
                        help="Path to the creature directory (e.g. creatures/touchy-pebble)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from the last session's final experience/instinct")
    parser.add_argument("--llm", default=None, metavar="NAME",
                        help="LLM profile to use, read from .config/llm/<NAME>.toml. "
                             "Overrides the default in .config/config.toml.")
    args = parser.parse_args()
    creature = Creature(args.creature_path)
    llm, llm_info = load_llm(args.llm)
    # mouse=False disables Textual's mouse capture so the terminal can
    # handle drag-selection — lets you copy text out of the log panel.
    SpineApp(creature=creature, resume=args.resume,
             llm=llm, llm_info=llm_info).run(mouse=False)


if __name__ == "__main__":
    main()
