"""trace — bake (if needed) and serve a run in the browser viewer.

A run is a spine/sim-spine session dir, a creature dir (latest session), or a
no-LLM creature-sim run dir (sim_out/<name>/). All bake to one trace.json.
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import webbrowser
from urllib.parse import quote

from .trace import build_view, write_trace


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve with caching disabled, so edited viewers show up on a plain refresh."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):
        pass


def find_repo_root(start: str) -> str:
    p = os.path.abspath(start)
    while p != "/":
        if os.path.exists(os.path.join(p, "pyproject.toml")):
            return p
        p = os.path.dirname(p)
    raise SystemExit(f"could not find pyproject.toml above {start}")


def resolve_run(arg: str) -> str:
    """A session dir (session.json), a creature dir (logs/), or a sim run dir
    (meta.json / output/). Creature dirs resolve to their most recent session."""
    arg = os.path.abspath(arg)
    if os.path.isfile(os.path.join(arg, "session.json")):
        return arg
    if os.path.isfile(os.path.join(arg, "meta.json")) or \
       os.path.isfile(os.path.join(arg, "output", "display_log.jsonl")):
        return arg
    logs = os.path.join(arg, "logs")
    if os.path.isdir(logs):
        sessions = sorted(d for d in os.listdir(logs)
                          if os.path.isdir(os.path.join(logs, d)))
        if not sessions:
            raise SystemExit(f"no sessions in {logs}")
        return os.path.join(logs, sessions[-1])
    raise SystemExit(f"{arg} is not a session, creature, or sim run dir")


def bake_if_needed(run_dir: str, repo_root: str, rebake: bool) -> dict:
    out_path = os.path.join(run_dir, "trace.json")
    if os.path.exists(out_path) and not rebake:
        print(f"using cached {os.path.relpath(out_path)}", file=sys.stderr)
        with open(out_path) as f:
            return json.load(f)
    print(f"baking {os.path.basename(run_dir)}…", file=sys.stderr)
    data = build_view(run_dir, repo_root)
    write_trace(data, out_path)
    stage = " + stage" if data.get("stage") else ""
    print(f"  → {len(data['events'])} events{stage}", file=sys.stderr)
    return data


def main():
    p = argparse.ArgumentParser(description="Open a run in the timeline viewer.")
    p.add_argument("path",
                   help="A session dir, a creature dir (latest session), or a sim run dir.")
    p.add_argument("--rebake", action="store_true",
                   help="Force rebake even if trace.json exists.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1",
                   help="Interface to bind. Default localhost only. 0.0.0.0 for LAN.")
    p.add_argument("--no-open", action="store_true",
                   help="Don't open the browser automatically.")
    args = p.parse_args()

    run_dir = resolve_run(args.path)
    repo_root = find_repo_root(run_dir)
    data = bake_if_needed(run_dir, repo_root, args.rebake)

    rel = os.path.relpath(run_dir, repo_root)
    url = f"http://localhost:{args.port}/viewers/tracer/?trace={quote(rel)}"

    os.chdir(repo_root)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        srv = socketserver.ThreadingTCPServer((args.host, args.port), NoCacheHandler)
    except OSError as e:
        if e.errno == 48:  # address in use
            print(f"port {args.port} is already in use.", file=sys.stderr)
            print(f"  pick a different port: trace ... --port {args.port + 1}",
                  file=sys.stderr)
            sys.exit(1)
        raise

    with srv:
        print(f"serving from {repo_root}", file=sys.stderr)
        n = len(data["events"])
        stage = " + stage" if data.get("stage") else ""
        print(f"  → {url}  ({n} events{stage})", file=sys.stderr)
        print("Ctrl+C to stop", file=sys.stderr)
        if not args.no_open:
            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopping", file=sys.stderr)


if __name__ == "__main__":
    main()
