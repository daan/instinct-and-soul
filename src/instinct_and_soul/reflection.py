"""ReflectionLoop — the LLM-driven soul cycle, decoupled from UI/network.

Owns per-session state (current instinct, current experience, buffer, usage)
and the `reflect()` coroutine. Hosts plug in via callbacks for the
environment-specific bits:

  spine.py     ── TUI + websocket adapter (real device)
  sim_spine.py ── in-process fake-hardware driver (simulator)

Also exports Creature and VersionStore (moved from spine.py for reuse).
"""
import asyncio
import glob
import json
import os
import re
import time
import tomllib
from typing import Awaitable, Callable, Optional

from .creature_sim.devices import DEFAULT_DEVICE
from .llm import LLM_HARD_TIMEOUT_S, LLM_MAX_TOKENS, compute_cost
from .message_buffer import MessageBuffer


def _is_truncated(stop_reason) -> bool:
    """True if the provider cut the reply at the token cap (anthropic
    'max_tokens', openai 'length', gemini 'MAX_TOKENS')."""
    if stop_reason is None:
        return False
    s = str(stop_reason).lower()
    return "max_tokens" in s or s == "length"


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

# Store format 2 (2026-07): artifact filenames are
#     {t_ms:08d}_v{n:03d}.{ext}
# — creature-clock milliseconds first (lexicographic = chronological), then a
# PER-TYPE version counter (instinct v1 = the seed, v2 = the first rewrite).
# Format 1 named files {global_seq:03d}_{t_s} — the global counter made the
# soul's self-narrative lie ("instinct v4" was its first rewrite). The global
# seq survives as an event-ordering field inside reflection records; readers
# discriminate formats via session.json's "store_format" (absent = 1).
STORE_FORMAT = 2


def parse_version_filename(path):
    """(t, version) from either store format's artifact filename.
    Format 2: {t_ms}_v{n}  ->  (t_ms/1000, n).  Format 1: {seq}_{t_s} ->
    (t_s, seq). Lexicographic order is chronological in both."""
    stem = os.path.splitext(os.path.basename(path))[0]
    a, _, b = stem.partition("_")
    if b.startswith("v"):
        return int(a) / 1000.0, int(b[1:])
    return float(b or 0), int(a)


class VersionStore:
    """Writes per-session artifacts (instinct, experience, reflections, etc.)."""

    def __init__(self, logs_dir, now: Callable[[], float] = time.time):
        # session_id stays wall-clock (it names the dir); _now drives the
        # timeline timestamps so a sim can put them on its virtual axis.
        self._now = now
        session_id = time.strftime("%Y%m%d_%H%M%S")
        # Atomically claim a unique dir. Parallel runs that start in the same
        # second would otherwise collide on the second-resolution name; the
        # first to create the dir wins, the rest bump _1, _2, … This is
        # race-safe because os.makedirs (without exist_ok) fails if it exists.
        os.makedirs(logs_dir, exist_ok=True)
        suffix = 0
        while True:
            sid = session_id if suffix == 0 else "{}_{}".format(session_id, suffix)
            base = os.path.join(logs_dir, sid)
            try:
                os.makedirs(base)
                break
            except FileExistsError:
                suffix += 1
        self.base = base
        self.session_id = sid
        self.seq = 0            # global event counter (ordering, cross-refs)
        self._counts = {}       # per-type version counters (filenames, souls)
        for subdir in ("instinct", "experience", "reflections", "crashes", "memory"):
            os.makedirs(os.path.join(self.base, subdir), exist_ok=True)

    def next_version(self, kind):
        """The next per-type version number: instinct v1, v2, … reflection
        n1, n2, … Counted separately per kind, unlike the global seq."""
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return self._counts[kind]

    def _vpath(self, subdir, n, ext):
        return os.path.join(self.base, subdir, "{:08d}_v{:03d}.{}".format(
            int(self._now() * 1000.0), n, ext))

    def save_session_config(self, system_prompt, character, llm_info=None,
                            resumed_from=None, provenance="device"):
        path = os.path.join(self.base, "session.json")
        with open(path, "w") as f:
            json.dump({
                "session_id": self.session_id,
                "store_format": STORE_FORMAT,
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
        # The organs define the body — a session without them is not
        # reproducible (their constants are calibration provenance).
        organs = os.path.join(creature.path, "organs.py")
        if os.path.isfile(organs):
            with open(organs) as src, \
                 open(os.path.join(self.base, "organs.py"), "w") as dst:
                dst.write(src.read())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def save_instinct(self, n, code):
        path = self._vpath("instinct", n, "py")
        with open(path, "w") as f:
            f.write(code)
        return path

    def save_experience(self, n, text):
        path = self._vpath("experience", n, "md")
        with open(path, "w") as f:
            f.write(text)
        return path

    def save_reflection(self, n, data):
        path = self._vpath("reflections", n, "json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def save_usage(self, totals):
        path = os.path.join(self.base, "usage.json")
        with open(path, "w") as f:
            json.dump(totals, f, indent=2)
        return path

    def save_crash(self, n, error):
        path = self._vpath("crashes", n, "txt")
        with open(path, "w") as f:
            f.write(error)
        return path

    def save_memory(self, n, payload):
        path = self._vpath("memory", n, "json")
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
                 max_reflections: Optional[int] = None,
                 now: Callable[[], float] = time.time):
        self.creature = creature
        self.llm = llm
        # Hard cap on the number of LLM reflections (cost ceiling for pricey
        # models). None = unbounded. Once hit, needs_reflection() returns False
        # and the body keeps performing with the last instinct (no more LLM
        # calls) until the clip ends — so cost is bounded but the performance
        # still runs full-length for beat-lock measurement.
        self.max_reflections = max_reflections
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
            drop_after_instinct_change=False,   # journal semantics: never drop
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
        # Per-type versions: the seed (or inherited state) is instinct v1 /
        # experience v1 of this session; the first rewrite will be v2.
        self.instinct_version = self.store.next_version("instinct")
        self.store.save_instinct(self.instinct_version, self.current_instinct)
        self.experience_version = self.store.next_version("experience")
        self.store.save_experience(self.experience_version, self.current_experience)

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
        # Stamp the authoring instinct version: journal entries are never
        # dropped, so the reflection must be able to attribute each entry to
        # the code that wrote it (entries from before a deploy describe the
        # OLD code's behavior — but the world-facts in them are still facts).
        self.buffer.add({"ts": self._now(), "content": content,
                         "v": self.instinct_version})

    def add_operator(self, text: str) -> None:
        tagged = "OPERATOR: " + text
        self.store.save_operator_command(text)
        self.buffer.add({"ts": self._now(), "content": tagged})

    def add_crash(self, error_msg: str) -> None:
        self.last_crashed = True
        self.last_crash_msg = error_msg
        self.store.save_crash(self.store.next_version("crash"), error_msg)

    def add_memory_snapshot(self, payload: str) -> None:
        self.store.save_memory(self.store.next_version("memory"), payload)

    def needs_reflection(self) -> bool:
        if (self.max_reflections is not None
                and self.session_usage["reflections"] >= self.max_reflections):
            return False
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

        # Render with provenance: entries written by a previous instinct are
        # marked, so the soul never mistakes the old code's reports for the
        # new code's behavior — the fix that used to be done by dropping them.
        lines = []
        prev_v = None
        for i, m in enumerate(messages):
            v = m.get("v")
            if v is not None and (i == 0 or v != prev_v):
                if v != self.instinct_version:
                    lines.append("  -- entries below were written by instinct "
                                 "v{} (before your latest deploy) --".format(v))
                elif i > 0:
                    lines.append("  -- your current instinct v{} from here "
                                 "on --".format(v))
            prev_v = v
            lines.append("  [{ts}] {content}".format(ts=m["ts"], content=m["content"]))
        messages_xml = "\n".join(lines)
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
            # Hard backstop: even with the SDK's own per-attempt timeout+retries,
            # a stuck connection has been seen to hang for many minutes. wait_for
            # guarantees the reflection fails (and the run continues) instead of
            # freezing the creature forever mid-reflection.
            _gen_t0 = time.monotonic()
            result = await asyncio.wait_for(
                self.llm.call(self.creature.system_prompt, reflection_prompt),
                timeout=LLM_HARD_TIMEOUT_S)
            gen_seconds = round(time.monotonic() - _gen_t0, 3)  # wall-clock generation time
            reply = result["text"]
            usage = result["usage"]
            stop_reason = result.get("stop_reason")
            truncated = _is_truncated(stop_reason)
            if truncated:
                self._on_log(
                    "soul: reply TRUNCATED at the {}-token cap (stop_reason={}) — "
                    "instinct/experience likely incomplete; instinct may not deploy"
                    .format(LLM_MAX_TOKENS, stop_reason), "bold red")

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

            seq = self.store.next_seq()                    # global event id
            rn = self.store.next_version("reflection")     # reflection #rn
            reflection = {
                "seq": seq,
                "n": rn,
                "ts": self._now(),
                "started_at": started_at,
                "gen_seconds": gen_seconds,
                "messages_since_last": messages,
                "instinct_version_in": self.instinct_version,
                "crashed": crashed,
                "intent": intent,
                "stop_reason": stop_reason,
                "truncated": truncated,
                "instinct_changed": new_instinct is not None,
                "experience_changed": new_experience is not None,
                "usage": usage,
                "prompt": reflection_prompt,
                "response": reply,
            }

            if new_instinct is not None:
                self.current_instinct = new_instinct
                iv = self.store.next_version("instinct")
                self.instinct_version = iv
                self.store.save_instinct(iv, new_instinct)
                reflection["instinct_version_out"] = iv

                if self._on_instinct_deploy is not None:
                    try:
                        await self._on_instinct_deploy(new_instinct, iv)
                    except Exception as e:
                        self._on_log("instinct deploy callback raised: {}".format(e), "bold red")

                # Journal principle: entries written during the reflection are
                # never dropped — they carry their authoring version ("v") and
                # the prompt marks them, so the next reflection can attribute
                # them to the old code without losing the world-facts in them.

            if new_experience is not None:
                self.current_experience = new_experience
                ev = self.store.next_version("experience")
                self.experience_version = ev
                self.store.save_experience(ev, new_experience)
                reflection["experience_version_out"] = ev
                self._on_log("updated experience v{}".format(ev), "cyan")

            self.store.save_reflection(rn, reflection)

        except Exception as e:
            # Many failure modes stringify to "" (asyncio.TimeoutError, some
            # Gemini safety blocks) — record the type so "failed" is diagnosable.
            detail = str(e) or repr(e)
            if isinstance(e, asyncio.TimeoutError):
                detail = "LLM call timed out after {:.0f}s".format(LLM_HARD_TIMEOUT_S)
            error_msg = "{}: {}".format(type(e).__name__, detail)
            fseq = self.store.next_seq()
            fn = self.store.next_version("reflection")
            self.store.save_reflection(fn, {
                "seq": fseq,
                "n": fn,
                "ts": self._now(),
                "started_at": started_at,
                "messages_since_last": messages,
                "instinct_version_in": self.instinct_version,
                "crashed": crashed,
                "prompt": reflection_prompt,
                "error": error_msg,
                "failed": True,
            })
            self._on_log("reflection error: {}".format(error_msg), "bold red")
        finally:
            self._set_reflecting(False)
