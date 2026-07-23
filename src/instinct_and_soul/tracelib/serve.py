"""trace — bake (if needed) and serve a run in the browser viewer.

A run is a spine/sim-spine session dir, a creature dir (latest session), or a
no-LLM creature-sim run dir (sim_out/<name>/). All bake to one trace.json.
"""
import argparse
import glob
import http.server
import json
import os
import socketserver
import sys
import webbrowser
from urllib.parse import quote

from .trace import build_view, write_trace


def list_runs(root: str) -> list[dict]:
    """Creature dirs with a logs/ of sessions, for the viewer's run picker.
    Covers creatures/<name> and sim_creatures/<series>/<experiment>."""
    runs = []
    logs_dirs = sorted(
        glob.glob(os.path.join(root, "creatures", "*", "logs"))
        + glob.glob(os.path.join(root, "sim_creatures", "*", "logs"))
        + glob.glob(os.path.join(root, "sim_creatures", "*", "*", "logs")))
    for logs in logs_dirs:
        sessions = sorted((d for d in os.listdir(logs)
                           if os.path.isdir(os.path.join(logs, d))), reverse=True)
        if sessions:
            runs.append({"creature": os.path.relpath(os.path.dirname(logs), root),
                         "sessions": sessions})
    return runs


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve with caching disabled, so edited viewers show up on a plain refresh."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/api/runs":
            body = json.dumps(list_runs(os.getcwd())).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # Bake on demand: the run picker can land on a session that was never
        # traced. Serving its trace.json bakes it first, then serves the file.
        fpath = self.translate_path(self.path)
        if fpath.endswith("trace.json") and not os.path.exists(fpath):
            run_dir = os.path.dirname(os.path.abspath(fpath))
            root = os.getcwd()
            if run_dir.startswith(root + os.sep) and os.path.isdir(run_dir):
                try:
                    print(f"baking {os.path.relpath(run_dir)}…", file=sys.stderr)
                    write_trace(build_view(run_dir, root), fpath)
                except Exception as e:
                    self.send_error(500, f"bake failed: {e}")
                    return
        super().do_GET()


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
    p.add_argument("--svg", metavar="PATH",
                   help="Render a standalone timeline+log SVG to PATH and exit "
                        "(no server). Self-contained, fit for a figure.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1",
                   help="Interface to bind. Default localhost only. 0.0.0.0 for LAN.")
    p.add_argument("--no-open", action="store_true",
                   help="Don't open the browser automatically.")
    args = p.parse_args()

    run_dir = resolve_run(args.path)
    repo_root = find_repo_root(run_dir)
    data = bake_if_needed(run_dir, repo_root, args.rebake)

    if args.svg:
        from .svg import render_svg
        svg = render_svg(data)
        with open(args.svg, "w") as f:
            f.write(svg)
        print(f"wrote {args.svg}  ({len(svg)} bytes)", file=sys.stderr)
        return

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
