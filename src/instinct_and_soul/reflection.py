"""ReflectionLoop — the LLM-driven soul cycle, decoupled from UI/network.

Owns per-session state (current instinct, current experience, buffer, usage)
and the `reflect()` coroutine. Hosts plug in via callbacks for the
environment-specific bits:

  spine.py     ── TUI + websocket adapter (real device)
  sim_spine.py ── in-process fake-hardware driver (simulator)

Also exports Creature and VersionStore (moved from spine.py for reuse).
"""
import glob
import json
import os
import re
import time
import tomllib
from typing import Awaitable, Callable, Optional

from .creature_sim.devices import DEFAULT_DEVICE
from .llm import compute_cost
from .message_buffer import MessageBuffer


# ── Creature loading ──────────────────────────────────────────────────────

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
        # Body: an optional creature.toml declares the device (see devices.py).
        self.config = self._read_config()
        self.device = self.config.get("device", DEFAULT_DEVICE)

    def _read(self, name):
        p = os.path.join(self.path, name)
        if not os.path.isfile(p):
            raise FileNotFoundError("missing {} in creature {}".format(name, self.path))
        with open(p) as f:
            return f.read()

    def _read_config(self):
        p = os.path.join(self.path, "creature.toml")
        if not os.path.isfile(p):
            return {}
        with open(p, "rb") as f:
            return tomllib.load(f)


# ── XML parsing ───────────────────────────────────────────────────────────

def extract_xml_tag(text, tag):
    m = re.search(r"<{0}>(.*?)</{0}>".format(tag), text, re.DOTALL)
    return m.group(1).strip() if m else None


# ── Session resume ────────────────────────────────────────────────────────

def find_last_session(logs_dir):
    if not os.path.isdir(logs_dir):
        return None
    sessions = sorted(
        d for d in os.listdir(logs_dir)
        if os.path.isdir(os.path.join(logs_dir, d))
    )
    return os.path.join(logs_dir, sessions[-1]) if sessions else None


def load_last_state(session_dir):
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


# ── Version store ─────────────────────────────────────────────────────────

class VersionStore:
    """Writes per-session artifacts (instinct, experience, reflections, etc.)."""

    def __init__(self, logs_dir, now: Callable[[], float] = time.time):
        # session_id stays wall-clock (it names the dir); _now drives the
        # timeline timestamps so a sim can put them on its virtual axis.
        self._now = now
        session_id = time.strftime("%Y%m%d_%H%M%S")
        self.base = os.path.join(logs_dir, session_id)
        self.session_id = session_id
        self.seq = 0
        for subdir in ("instinct", "experience", "reflections", "crashes", "memory"):
            os.makedirs(os.path.join(self.base, subdir), exist_ok=True)

    def save_session_config(self, system_prompt, character, llm_info=None,
                            resumed_from=None, provenance="device"):
        path = os.path.join(self.base, "session.json")
        with open(path, "w") as f:
            json.dump({
                "session_id": self.session_id,
                "ts": self._now(),
                "provenance": provenance,
                "resumed_from": resumed_from,
                "llm": llm_info,
                "system_prompt": system_prompt,
                "character": character,
            }, f, indent=2)
        return path

    def save_seeds(self, creature):
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
        path = os.path.join(self.base, "instinct", "{:03d}_{}.py".format(seq, int(self._now())))
        with open(path, "w") as f:
            f.write(code)
        return path

    def save_experience(self, seq, text):
        path = os.path.join(self.base, "experience", "{:03d}_{}.md".format(seq, int(self._now())))
        with open(path, "w") as f:
            f.write(text)
        return path

    def save_reflection(self, seq, data):
        path = os.path.join(self.base, "reflections", "{:03d}_{}.json".format(seq, int(self._now())))
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def save_usage(self, totals):
        path = os.path.join(self.base, "usage.json")
        with open(path, "w") as f:
            json.dump(totals, f, indent=2)
        return path

    def save_crash(self, seq, error):
        path = os.path.join(self.base, "crashes", "{:03d}_{}.txt".format(seq, int(self._now())))
        with open(path, "w") as f:
            f.write(error)
        return path

    def save_memory(self, seq, payload):
        path = os.path.join(self.base, "memory", "{:03d}_{}.json".format(seq, int(self._now())))
        with open(path, "w") as f:
            f.write(payload)
        return path

    def save_operator_command(self, text):
        path = os.path.join(self.base, "operator.log")
        with open(path, "a") as f:
            f.write("{}\t{}\n".format(time.time(), text))
        return path


# ── Reflection loop ───────────────────────────────────────────────────────

LogCb     = Callable[[str, Optional[str]], None]
IntentCb  = Callable[[str, float], None]
DeployCb  = Callable[[str, int], Awaitable[None]]
StatusCb  = Callable[[], None]


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return "{:.1f}K".format(n / 1000)
    return str(n)


class ReflectionLoop:
    """Per-session state + the reflect() cycle. Host-agnostic."""

    def __init__(self, creature: Creature, llm, *,
                 llm_info: Optional[dict] = None,
                 resume: bool = False,
                 provenance: str = "device",
                 on_log: Optional[LogCb] = None,
                 on_intent: Optional[IntentCb] = None,
                 on_instinct_deploy: Optional[DeployCb] = None,
                 on_status_change: Optional[StatusCb] = None,
                 now: Callable[[], float] = time.time):
        self.creature = creature
        self.llm = llm
        self.llm_info = llm_info or {}
        self.model = self.llm_info.get("model")
        # Timeline clock. Default is wall time (real spine). The simulator injects
        # its sim clock so reflection events land on the same axis as IMU/audio.
        self._now = now

        self._on_log = on_log or (lambda msg, style=None: None)
        self._on_intent = on_intent or (lambda intent, ts: None)
        self._on_instinct_deploy = on_instinct_deploy   # may be None
        self._on_status_change = on_status_change or (lambda: None)

        # Resume state must be loaded BEFORE VersionStore creates the new
        # session dir, otherwise find_last_session() picks up the just-created
        # (empty) directory as "most recent" and the resume silently no-ops.
        self.current_experience = creature.seed_experience
        self.current_instinct   = creature.seed_instinct
        self.resumed_from: Optional[str] = None

        if resume:
            last = find_last_session(creature.logs_dir)
            if last:
                experience, instinct = load_last_state(last)
                if experience:
                    self.current_experience = experience
                if instinct:
                    self.current_instinct = instinct
                self.resumed_from = os.path.basename(last)

        self.store = VersionStore(creature.logs_dir, now=now)
        self.buffer = MessageBuffer(
            drop_after_instinct_change=True,
            spare_operator=True,
        )

        self.instinct_version = 0
        self.experience_version = 0
        self.last_crashed = False
        self.last_crash_msg = ""
        self._reflecting = False
        self.session_usage = {
            "llm": self.llm_info,
            "started_at": time.time(),
            "updated_at": time.time(),
            "reflections": 0,
            "input_tokens_total": 0,
            "cache_read_input_tokens_total": 0,
            "cache_creation_input_tokens_total": 0,
            "output_tokens_total": 0,
            "cost_total": 0.0,
        }

        self.store.save_session_config(
            creature.system_prompt, creature.character,
            self.llm_info, self.resumed_from, provenance=provenance,
        )
        self.store.save_seeds(creature)
        seq = self.store.next_seq()
        self.instinct_version = seq
        self.store.save_instinct(seq, self.current_instinct)
        seq = self.store.next_seq()
        self.experience_version = seq
        self.store.save_experience(seq, self.current_experience)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self.store.session_id

    @property
    def reflecting(self) -> bool:
        return self._reflecting

    def _set_reflecting(self, value: bool) -> None:
        if self._reflecting != value:
            self._reflecting = value
            try:
                self._on_status_change()
            except Exception:
                pass

    # ── Inputs from host ──────────────────────────────────────────────

    def add_message(self, content: str) -> None:
        self.buffer.add({"ts": self._now(), "content": content})

    def add_operator(self, text: str) -> None:
        tagged = "OPERATOR: " + text
        self.store.save_operator_command(text)
        self.buffer.add({"ts": self._now(), "content": tagged})

    def add_crash(self, error_msg: str) -> None:
        self.last_crashed = True
        self.last_crash_msg = error_msg
        self.store.save_crash(self.store.next_seq(), error_msg)

    def add_memory_snapshot(self, payload: str) -> None:
        self.store.save_memory(self.store.next_seq(), payload)

    def needs_reflection(self) -> bool:
        return not self._reflecting and (self.buffer.has_pending() or self.last_crashed)

    # ── Reflection cycle ──────────────────────────────────────────────

    async def reflect(self) -> None:
        """One reflection cycle. Caller orchestrates scheduling / re-fire."""
        self._set_reflecting(True)
        started_at = self._now()

        messages = self.buffer.drain()
        crashed = self.last_crashed
        crash_msg = self.last_crash_msg
        self.last_crashed = False
        self.last_crash_msg = ""

        messages_xml = "\n".join("  [{ts}] {content}".format(**m) for m in messages)
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

        self._on_log("reflecting ({} messages)...".format(len(messages)), "dim")

        try:
            result = await self.llm.call(self.creature.system_prompt, reflection_prompt)
            reply = result["text"]
            usage = result["usage"]

            self.session_usage["reflections"] += 1
            self.session_usage["input_tokens_total"] += usage["input_tokens"]
            self.session_usage["cache_read_input_tokens_total"] += usage["cache_read_input_tokens"]
            self.session_usage["cache_creation_input_tokens_total"] += usage["cache_creation_input_tokens"]
            self.session_usage["output_tokens_total"] += usage["output_tokens"]
            cost_inc = compute_cost(self.model, usage)
            if cost_inc is not None:
                self.session_usage["cost_total"] += cost_inc
            self.session_usage["updated_at"] = time.time()
            self.store.save_usage(self.session_usage)

            input_total = (usage["input_tokens"] + usage["cache_read_input_tokens"]
                           + usage["cache_creation_input_tokens"])
            cache_str = ""
            if usage["cache_read_input_tokens"] > 0:
                cache_str = " ({} cached)".format(_fmt_tokens(usage["cache_read_input_tokens"]))
            cost_str = " · ${:.4f}".format(cost_inc) if cost_inc is not None else ""
            self._on_log("reflected: {} in{} / {} out{}".format(
                _fmt_tokens(input_total), cache_str,
                _fmt_tokens(usage["output_tokens"]), cost_str), "dim")

            intent = extract_xml_tag(reply, "intent")
            new_experience = extract_xml_tag(reply, "experience")
            new_instinct = extract_xml_tag(reply, "instinct")

            if not intent:
                self._on_log("soul: no intent in response", "bold red")
                return

            self._on_log("intent: {}".format(intent), "bold magenta")
            try:
                self._on_intent(intent, time.time())
            except Exception:
                pass

            seq = self.store.next_seq()
            reflection = {
                "seq": seq,
                "ts": self._now(),
                "started_at": started_at,
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

                if self._on_instinct_deploy is not None:
                    try:
                        await self._on_instinct_deploy(new_instinct, iseq)
                    except Exception as e:
                        self._on_log("instinct deploy callback raised: {}".format(e), "bold red")

                dropped = self.buffer.on_instinct_changed()
                if dropped:
                    reflection["dropped_after"] = dropped
                    self._on_log(
                        "dropped {} stale message(s) after instinct change".format(len(dropped)),
                        "dim",
                    )

            if new_experience is not None:
                self.current_experience = new_experience
                eseq = self.store.next_seq()
                self.experience_version = eseq
                self.store.save_experience(eseq, new_experience)
                reflection["experience_version_out"] = eseq
                self._on_log("updated experience v{}".format(eseq), "cyan")

            self.store.save_reflection(seq, reflection)

        except Exception as e:
            fseq = self.store.next_seq()
            self.store.save_reflection(fseq, {
                "seq": fseq,
                "ts": self._now(),
                "started_at": started_at,
                "messages_since_last": messages,
                "instinct_version_in": self.instinct_version,
                "crashed": crashed,
                "prompt": reflection_prompt,
                "error": str(e),
                "failed": True,
            })
            self._on_log("reflection error: {}".format(e), "bold red")
        finally:
            self._set_reflecting(False)
