"""skeleton — bake (if needed) and serve the mocap skeleton + IMU viewer.

    skeleton                       # newest JSON in data/mocap/out/
    skeleton data/mocap/out/x.json # serve a specific baked JSON
    skeleton data/mocap/raw/x.npz  # bake it first, then serve
"""
import argparse
import http.server
import os
import socketserver
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

from . import find_repo_root
from .extract import process, default_out_dir


def resolve_json(arg: str | None) -> Path:
    """Return a baked JSON path. Bakes a .npz; defaults to newest baked file."""
    if arg is None:
        out_dir = default_out_dir()
        jsons = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not jsons:
            raise SystemExit(
                f"no baked mocap in {out_dir} — run `bake-mocap <raw.npz>` first")
        return jsons[-1]
    p = Path(arg)
    if not p.exists():
        raise SystemExit(f"not found: {p}")
    if p.suffix == ".npz":
        print(f"baking {p.name}…", file=sys.stderr)
        return process(p)
    if p.suffix == ".json":
        return p
    raise SystemExit(f"expected a .json or .npz, got {p}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the mocap skeleton + IMU viewer.")
    ap.add_argument("path", nargs="?", default=None,
                    help="A baked .json, a raw .npz (baked first), or omitted (newest baked).")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    root = find_repo_root()
    if not root:
        raise SystemExit("could not find pyproject.toml above the current directory")

    json_path = resolve_json(args.path).resolve()
    try:
        rel = json_path.relative_to(root)
    except ValueError:
        raise SystemExit(f"{json_path} is outside the repo ({root})")

    data_url = "/" + quote(str(rel))
    view_url = f"http://127.0.0.1:{args.port}/skeleton/index.html?data={quote(data_url)}"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *a):
            pass  # quiet

    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"serving {rel}", file=sys.stderr)
        print(f"  {view_url}  (Ctrl-C to stop)", file=sys.stderr)
        if not args.no_browser:
            webbrowser.open(view_url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
