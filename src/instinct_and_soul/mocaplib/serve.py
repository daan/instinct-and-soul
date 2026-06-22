"""skeleton — bake (if needed) and serve the mocap skeleton + IMU viewer.

    skeleton                            # newest clip in data/mocap/
    skeleton data/mocap/<clip>/         # serve that clip's skeleton_view.json
    skeleton data/mocap/<clip>/x.json   # serve a specific baked skeleton JSON
    skeleton path/to/clip.bvh           # bake a BVH into a clip first, then serve
    skeleton path/to/raw.npz            # bake an AMASS npz first, then serve
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
from .extract import process_any, default_mocap_dir


def _clip_view(clip_dir: Path) -> Path:
    """The viewer JSON inside a clip directory (view, else full skeleton)."""
    for name in ("skeleton_view.json", "skeleton.json"):
        if (clip_dir / name).is_file():
            return clip_dir / name
    raise SystemExit(f"clip {clip_dir} has no skeleton_view.json — re-bake it?")


def resolve_json(arg: str | None) -> Path:
    """Return a skeleton JSON to serve. Bakes a .npz/.bvh; defaults to newest clip."""
    if arg is None:
        clips = sorted(default_mocap_dir().glob("*/clip.json"),
                       key=lambda p: p.stat().st_mtime)
        if not clips:
            raise SystemExit(
                f"no baked clips in {default_mocap_dir()} — run "
                f"`bake-mocap <clip.bvh|raw.npz>` first")
        return _clip_view(clips[-1].parent)
    p = Path(arg)
    if not p.exists():
        raise SystemExit(f"not found: {p}")
    if p.is_dir():
        return _clip_view(p)
    if p.name == "clip.json":
        return _clip_view(p.parent)
    if p.suffix.lower() in (".npz", ".bvh"):
        print(f"baking {p.name}…", file=sys.stderr)
        return _clip_view(Path(process_any(p)))
    if p.suffix == ".json":
        return p
    raise SystemExit(f"expected a clip dir, a .json, or a .npz/.bvh, got {p}")


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
    view_url = f"http://127.0.0.1:{args.port}/viewers/skeleton/index.html?data={quote(data_url)}"

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
