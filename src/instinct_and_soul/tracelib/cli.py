"""Bake one session directory into a trace.json the tracer frontend can load."""
import argparse
import json
import os
import sys

from .trace import Trace


def main():
    p = argparse.ArgumentParser(description="Bake a spine session into trace.json.")
    p.add_argument("session_path", help="Path to a session directory under creatures/<x>/logs/")
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

    trace = Trace(args.session_path)
    data = trace.to_dict()
    text = json.dumps(data, indent=2 if args.pretty else None)

    with open(out_path, "w") as f:
        f.write(text)
    n = len(data["events"])
    print(f"baked {n} events from {trace.session_id} → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
