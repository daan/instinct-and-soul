"""Read a single spine session directory and produce a flat event stream."""
import glob
import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class Event:
    id: str
    t: float           # unix seconds
    kind: str          # see KINDS below
    payload: dict = field(default_factory=dict)


# Event kinds the tracer renders. Adding a new one requires a frontend change.
KINDS = (
    "instinct-msg",    # one accumulated instinct→soul message
    "operator",        # OPERATOR:-prefixed message from the spine TUI
    "intent",          # soul's reply (may carry instinct/experience bump flags)
    "failed",          # reflection that errored
    "crash",           # device-side crash report
    "mem",             # device Mem snapshot
)


def _filename_ts(path: str) -> float:
    """Pull the unix-seconds suffix out of a `NNN_TS.ext` filename."""
    name = os.path.basename(path)
    stem = name.rsplit(".", 1)[0]
    return float(stem.split("_", 1)[1])


def _filename_seq(path: str) -> int:
    name = os.path.basename(path)
    return int(name.split("_", 1)[0])


class Trace:
    """One spine session on disk."""

    def __init__(self, path: str):
        self.path = os.path.normpath(path)
        self.session_id = os.path.basename(self.path)
        with open(os.path.join(self.path, "session.json")) as f:
            self.meta = json.load(f)

    @property
    def session_start(self) -> float:
        return float(self.meta["ts"])

    def events(self) -> list[Event]:
        out: list[Event] = []
        out.extend(self._reflection_events())
        out.extend(self._crash_events())
        out.extend(self._mem_events())
        out.sort(key=lambda e: e.t)
        return out

    def _reflection_events(self) -> list[Event]:
        out: list[Event] = []
        for path in sorted(glob.glob(os.path.join(self.path, "reflections", "*.json"))):
            with open(path) as f:
                refl = json.load(f)
            seq = refl["seq"]

            for i, msg in enumerate(refl.get("messages_since_last", [])):
                content = msg["content"]
                kind = "operator" if content.startswith("OPERATOR:") else "instinct-msg"
                out.append(Event(
                    id=f"r{seq}m{i}",
                    t=float(msg["ts"]),
                    kind=kind,
                    payload={"content": content, "ref_seq": seq},
                ))

            if refl.get("failed"):
                out.append(Event(
                    id=f"r{seq}",
                    t=float(refl["ts"]),
                    kind="failed",
                    payload={
                        "error": refl.get("error", ""),
                        "ref_seq": seq,
                    },
                ))
            else:
                out.append(Event(
                    id=f"r{seq}",
                    t=float(refl["ts"]),
                    kind="intent",
                    payload={
                        "intent": refl.get("intent", ""),
                        "ref_seq": seq,
                        "instinct_changed": bool(refl.get("instinct_changed")),
                        "experience_changed": bool(refl.get("experience_changed")),
                        "instinct_version_out": refl.get("instinct_version_out"),
                        "experience_version_out": refl.get("experience_version_out"),
                    },
                ))
        return out

    def _crash_events(self) -> list[Event]:
        out: list[Event] = []
        for path in sorted(glob.glob(os.path.join(self.path, "crashes", "*.txt"))):
            with open(path) as f:
                content = f.read()
            out.append(Event(
                id=f"c{_filename_seq(path)}",
                t=_filename_ts(path),
                kind="crash",
                payload={"content": content},
            ))
        return out

    def _mem_events(self) -> list[Event]:
        out: list[Event] = []
        for path in sorted(glob.glob(os.path.join(self.path, "memory", "*.json"))):
            out.append(Event(
                id=f"m{_filename_seq(path)}",
                t=_filename_ts(path),
                kind="mem",
                payload={"path": os.path.relpath(path, self.path)},
            ))
        return out

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_start": self.session_start,
            "meta": {k: v for k, v in self.meta.items()
                     if k not in ("system_prompt",)},  # heavy; fetched on demand
            "events": [asdict(e) for e in self.events()],
        }
