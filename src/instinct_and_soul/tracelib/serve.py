"""trace — bake (if needed) and serve a session in the browser."""
import argparse
import http.server
import json
import os
import socketserver
import sys
import webbrowser
from urllib.parse import quote

from .trace import Trace


def find_repo_root(start: str) -> str:
    p = os.path.abspath(start)
    while p != "/":
        if os.path.exists(os.path.join(p, "pyproject.toml")):
            return p
        p = os.path.dirname(p)
    raise SystemExit(f"could not find pyproject.toml above {start}")


def resolve_session(arg: str) -> str:
    """Accept a session dir (has session.json) or a creature dir (has logs/).
    For creature dirs, picks the most recent session."""
    arg = os.path.abspath(arg)
    if os.path.isfile(os.path.join(arg, "session.json")):
        return arg
    logs = os.path.join(arg, "logs")
    if os.path.isdir(logs):
        sessions = sorted(d for d in os.listdir(logs)
                          if os.path.isdir(os.path.join(logs, d)))
        if not sessions:
            raise SystemExit(f"no sessions in {logs}")
        return os.path.join(logs, sessions[-1])
    raise SystemExit(f"{arg} is neither a session dir nor a creature dir")


def bake_if_needed(session_dir: str, rebake: bool) -> int:
    out_path = os.path.join(session_dir, "trace.json")
    if os.path.exists(out_path) and not rebake:
        print(f"using cached {os.path.relpath(out_path)}", file=sys.stderr)
        with open(out_path) as f:
            return len(json.load(f).get("events", []))
    print(f"baking {os.path.basename(session_dir)}…", file=sys.stderr)
    trace = Trace(session_dir)
    data = trace.to_dict()
    with open(out_path, "w") as f:
        json.dump(data, f)
    n = len(data["events"])
    print(f"  → {n} events", file=sys.stderr)
    return n


def main():
    p = argparse.ArgumentParser(description="Open a spine session in the tracer.")
    p.add_argument("path",
                   help="A session directory, or a creature dir (latest session is picked).")
    p.add_argument("--rebake", action="store_true",
                   help="Force rebake even if trace.json exists.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1",
                   help="Interface to bind. Default localhost only. "
                        "Use 0.0.0.0 to expose on the LAN.")
    p.add_argument("--no-open", action="store_true",
                   help="Don't open the browser automatically.")
    args = p.parse_args()

    session_dir = resolve_session(args.path)
    repo_root = find_repo_root(session_dir)
    n = bake_if_needed(session_dir, args.rebake)

    rel = os.path.relpath(session_dir, repo_root)
    url = f"http://localhost:{args.port}/viewers/tracer/?trace={quote(rel)}"

    os.chdir(repo_root)
    # ThreadingHTTPServer + allow_reuse so consecutive runs don't hit "address in use".
    socketserver.TCPServer.allow_reuse_address = True
    # Bind to localhost only — the server exposes the entire repo to whoever
    # can reach the port. Use --host 0.0.0.0 if you explicitly want LAN access.
    try:
        srv = socketserver.ThreadingTCPServer(
            (args.host, args.port), http.server.SimpleHTTPRequestHandler)
    except OSError as e:
        if e.errno == 48:  # address in use
            print(f"port {args.port} is already in use.", file=sys.stderr)
            print(f"  another tracer is probably running — find it with:", file=sys.stderr)
            print(f"    lsof -ti:{args.port}", file=sys.stderr)
            print(f"  or pick a different port: trace ... --port {args.port + 1}",
                  file=sys.stderr)
            sys.exit(1)
        raise

    with srv:
        print(f"serving from {repo_root}", file=sys.stderr)
        print(f"  → {url}  ({n} events)", file=sys.stderr)
        print("Ctrl+C to stop", file=sys.stderr)
        if not args.no_open:
            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopping", file=sys.stderr)


if __name__ == "__main__":
    main()
