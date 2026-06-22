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

            # Messages buffered during this reflection that got dropped because
            # the soul replaced the instinct. Emit them at their original arrival
            # time, tagged with `dropped: true` so the tracer can fade/strike them.
            for i, msg in enumerate(refl.get("dropped_after", [])):
                content = msg["content"]
                kind = "operator" if content.startswith("OPERATOR:") else "instinct-msg"
                out.append(Event(
                    id=f"r{seq}d{i}",
                    t=float(msg["ts"]),
                    kind=kind,
                    payload={
                        "content": content,
                        "ref_seq": seq,
                        "dropped": True,
                        "dropped_by": seq,
                    },
                ))

            if refl.get("failed"):
                fpayload = {
                    "error": refl.get("error", ""),
                    "ref_seq": seq,
                }
                if refl.get("started_at") is not None:
                    fpayload["started_at"] = float(refl["started_at"])
                    fpayload["latency_s"] = float(refl["ts"]) - float(refl["started_at"])
                out.append(Event(
                    id=f"r{seq}",
                    t=float(refl["ts"]),
                    kind="failed",
                    payload=fpayload,
                ))
            else:
                payload = {
                    "intent": refl.get("intent", ""),
                    "ref_seq": seq,
                    "instinct_changed": bool(refl.get("instinct_changed")),
                    "experience_changed": bool(refl.get("experience_changed")),
                    "instinct_version_out": refl.get("instinct_version_out"),
                    "experience_version_out": refl.get("experience_version_out"),
                }
                if refl.get("usage"):
                    payload["usage"] = refl["usage"]
                if refl.get("started_at") is not None:
                    payload["started_at"] = float(refl["started_at"])
                    payload["latency_s"] = float(refl["ts"]) - float(refl["started_at"])
                out.append(Event(
                    id=f"r{seq}",
                    t=float(refl["ts"]),
                    kind="intent",
                    payload=payload,
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

    def _versions(self) -> dict:
        """List the instinct/experience versions with their line counts.
        Used to plot size-over-time without forcing the frontend to do dir walks."""
        def collect(subdir: str) -> list[dict]:
            out = []
            for path in sorted(glob.glob(os.path.join(self.path, subdir, "*"))):
                with open(path) as f:
                    lines = sum(1 for _ in f)
                out.append({
                    "seq": _filename_seq(path),
                    "ts": _filename_ts(path),
                    "lines": lines,
                    "path": os.path.relpath(path, self.path),
                })
            return out
        return {"instinct": collect("instinct"), "experience": collect("experience")}

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_start": self.session_start,
            "meta": {k: v for k, v in self.meta.items()
                     if k not in ("system_prompt",)},  # heavy; fetched on demand
            "events": [asdict(e) for e in self.events()],
            "versions": self._versions(),
        }


# ── Unified view: one trace.json for any run, with an optional sim "stage" ──
# A run is either a spine/sim-spine *session* (has session.json + reflections)
# or a no-LLM creature-sim run (sim_out/<name>/, just meta.json + I/O jsonl).
# Both reduce to the same shape; the `stage` block carries what the viewer's
# small dancer/device/sound inset needs, with sim I/O kept in sim-ms.

def _repo_root(start: str) -> str:
    p = os.path.abspath(start)
    while p != "/":
        if os.path.exists(os.path.join(p, "pyproject.toml")):
            return p
        p = os.path.dirname(p)
    return os.path.abspath(start)


def _read_jsonl(path: str) -> list:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_IMU_CAP = 2500  # max points per channel kept in trace.json (decimated)


def _decimate(rows: list, cap: int = _IMU_CAP) -> list:
    if len(rows) <= cap:
        return rows
    stride = (len(rows) + cap - 1) // cap
    return rows[::stride]


def _build_imu(run_dir: str, repo_root: str, mocap_rel, wrist, duration_ms) -> dict | None:
    """Dense wrist IMU from the mocap clip (preferred), else the instinct's reads.
    Columnar + decimated so it stays small in trace.json."""
    wrist = wrist or "left"
    # Preferred: synthetic IMU baked into the mocap clip (true wrist signal).
    if mocap_rel:
        path = os.path.join(repo_root, mocap_rel)
        if os.path.isfile(path):
            with open(path) as f:
                clip = json.load(f)
            imu = (clip.get("imu") or {}).get(wrist)
            fps = clip.get("fps") or 1.0
            if imu and imu.get("acc") and imu.get("gyro"):
                acc, gyro = imu["acc"], imu["gyro"]
                n = min(len(acc), len(gyro))
                rows = []
                for i in range(n):
                    ms = i / fps * 1000.0
                    if duration_ms and ms > duration_ms:
                        break
                    rows.append((ms, acc[i], gyro[i]))
                rows = _decimate(rows)
                if rows:
                    return {
                        "ms": [round(r[0], 1) for r in rows],
                        "acc": [[round(v, 4) for v in r[1]] for r in rows],
                        "gyro": [[round(v, 3) for v in r[2]] for r in rows],
                    }
    # Fallback: what the instinct actually sampled.
    reads = _read_jsonl(os.path.join(run_dir, "input", "imu_reads.jsonl"))
    reads = _decimate(reads)
    if reads:
        return {
            "ms": [r.get("t", 0) for r in reads],
            "acc": [[r.get("ax", 0), r.get("ay", 0), r.get("az", 0)] for r in reads],
            "gyro": [[r.get("gx", 0), r.get("gy", 0), r.get("gz", 0)] for r in reads],
        }
    return None


def _build_stage(run_dir: str, repo_root: str) -> dict | None:
    """Assemble the inset 'stage' from a run's sim I/O, or None if there is none."""
    disp_path = os.path.join(run_dir, "output", "display_log.jsonl")
    aud_path = os.path.join(run_dir, "output", "audio_events.jsonl")
    if not (os.path.isfile(disp_path) or os.path.isfile(aud_path)):
        return None

    # Either a creature-sim meta.json or a sim-spine sim_meta.json (or both).
    meta = {}
    for name in ("meta.json", "sim_meta.json"):
        p = os.path.join(run_dir, name)
        if os.path.isfile(p):
            with open(p) as f:
                meta.update(json.load(f))

    display_ops = _read_jsonl(disp_path)
    audio_events = _read_jsonl(aud_path)

    # Ensure audio.wav exists (bake from events on demand), reference by path.
    wav_rel = None
    wav = os.path.join(run_dir, "output", "audio.wav")
    if audio_events:
        if not os.path.isfile(wav):
            try:
                from ..creature_sim.bake_audio import bake as _bake_audio
                _bake_audio(aud_path, wav)
            except Exception:
                pass
        if os.path.isfile(wav):
            wav_rel = os.path.relpath(wav, repo_root)

    ts = [o.get("t", 0) for o in display_ops] + [e.get("t", 0) for e in audio_events]
    duration_ms = meta.get("duration_ms") or (max(ts) if ts else 0)

    return {
        "mocap": meta.get("source"),          # repo-relative path or None
        "fps": meta.get("fps"),
        "screen": meta.get("screen") or {"w": 135, "h": 240},
        "wrist": meta.get("wrist"),
        "device": meta.get("device"),
        "display_ops": display_ops,
        "audio_events": audio_events,
        "audio": wav_rel,
        "duration_ms": duration_ms,
        "imu": _build_imu(run_dir, repo_root, meta.get("source"),
                          meta.get("wrist"), duration_ms),
    }


def build_view(run_dir: str, repo_root: str | None = None) -> dict:
    """Bake any run dir into the unified trace.json the tracer consumes."""
    run_dir = os.path.normpath(run_dir)
    repo_root = repo_root or _repo_root(run_dir)
    stage = _build_stage(run_dir, repo_root)

    if os.path.isfile(os.path.join(run_dir, "session.json")):
        d = Trace(run_dir).to_dict()                 # full reflection timeline
    else:
        meta = {}
        p = os.path.join(run_dir, "meta.json")
        if os.path.isfile(p):
            with open(p) as f:
                meta = json.load(f)
        d = {                                        # no-LLM probe: empty timeline
            "session_id": os.path.basename(run_dir),
            "session_start": 0.0,
            "meta": meta,
            "events": [],
            "versions": {"instinct": [], "experience": []},
        }

    if stage:
        d["stage"] = stage
    return d
