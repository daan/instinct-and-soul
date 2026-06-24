"""Bake one session directory into a trace.json the tracer frontend can load."""
import argparse
import os
import sys

from .trace import build_view, write_trace


def main():
    p = argparse.ArgumentParser(description="Bake any run into trace.json for the viewer.")
    p.add_argument("session_path",
                   help="A session dir (creatures/<x>/logs/<ts>/) or a sim run dir (sim_out/<x>/).")
    p.add_argument("-o", "--output", default=None,
                   help="Output path. Defaults to <session_path>/trace.json.")
    p.add_argument("--rebake", action="store_true",
                   help="Overwrite an existing trace.json instead of skipping.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print the JSON.")
    args = p.parse_args()

    out_path = args.output or os.path.join(args.session_path, "trace.json")

    if os.path.exists(out_path) and not args.rebake and args.output is None:
        print(f"trace.json already exists at {out_path} (use --rebake to overwrite)",
              file=sys.stderr)
        return

    data = build_view(args.session_path)
    write_trace(data, out_path, pretty=args.pretty)
    n = len(data["events"])
    stage = " + stage" if data.get("stage") else ""
    print(f"baked {n} events from {data['session_id']}{stage} → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
