"""creature-sim — run a creature's instinct.py in a fake M5 environment."""
import argparse
import os
import sys

from .bridge import bake
from .fake_imu import load_imu_source
from .runner import run_sim


def _resolve_instinct_path(arg: str) -> str:
    """arg may be a creature dir (use seed_instinct.py) or a specific .py."""
    if os.path.isfile(arg) and arg.endswith(".py"):
        return arg
    # creature dir
    seed = os.path.join(arg, "seed_instinct.py")
    if os.path.isfile(seed):
        return seed
    raise SystemExit(f"could not find instinct code at {arg} "
                     f"(expected a .py file or a creature dir with seed_instinct.py)")


def main():
    p = argparse.ArgumentParser(description="Run a creature's instinct.py in a fake M5 environment.")
    p.add_argument("code_path",
                   help="A creature directory (uses seed_instinct.py) or a specific .py file.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--imu",
                     help="Path to an IMU stream: .npz (t_ms/accel/gyro) or .jsonl.")
    src.add_argument("--from-mocap", metavar="CLIP",
                     help="A baked mocap clip JSON (bake-mocap output); bridged to an "
                          "IMU stream on the fly under sim_in/.")
    p.add_argument("--wrist", default="left", choices=("left", "right"),
                   help="Wrist to extract when using --from-mocap (default: left).")
    p.add_argument("--duration", type=float, default=None,
                   help="Simulated duration in seconds. Defaults to IMU source length. "
                        "Cannot exceed IMU source length.")
    p.add_argument("-o", "--output", default=None,
                   help="Output directory. Defaults to sim_out/<code-stem>/.")
    args = p.parse_args()

    instinct_path = _resolve_instinct_path(args.code_path)

    if args.from_mocap:
        if not os.path.isfile(args.from_mocap):
            raise SystemExit(f"mocap clip not found: {args.from_mocap}")
        imu_path = bake(args.from_mocap, args.wrist)
        print(f"bridged {os.path.basename(args.from_mocap)} ({args.wrist} wrist) "
              f"→ {imu_path}", file=sys.stderr)
    else:
        imu_path = args.imu
    imu_source = load_imu_source(imu_path)

    source_s = imu_source.duration_ms / 1000.0
    if args.duration is None:
        duration_ms = imu_source.duration_ms
    else:
        if args.duration > source_s + 1e-6:
            raise SystemExit(
                f"--duration {args.duration:.2f}s exceeds IMU source length ({source_s:.2f}s)")
        duration_ms = args.duration * 1000.0

    if args.output is None:
        stem = os.path.splitext(os.path.basename(instinct_path))[0]
        output = os.path.join("sim_out", stem)
    else:
        output = args.output

    with open(instinct_path) as f:
        instinct_code = f.read()

    print(f"instinct: {instinct_path}", file=sys.stderr)
    print(f"imu:      {imu_path}  ({source_s:.2f}s, {len(imu_source.t_ms)} samples)", file=sys.stderr)
    print(f"duration: {duration_ms/1000.0:.2f}s", file=sys.stderr)
    print(f"output:   {output}", file=sys.stderr)

    summary = run_sim(
        instinct_code=instinct_code,
        imu_source=imu_source,
        duration_ms=duration_ms,
        output_dir=output,
    )

    print(f"--- summary ---", file=sys.stderr)
    print(f"  final virtual time: {summary['final_ms']/1000.0:.2f}s", file=sys.stderr)
    print(f"  imu reads:    {summary['imu_reads']}", file=sys.stderr)
    print(f"  audio events: {summary['audio_events']}", file=sys.stderr)
    print(f"  display calls:{summary['display_calls']}", file=sys.stderr)
    print(f"  sent:         {summary['sent']}", file=sys.stderr)
    if summary['crashed']:
        print(f"  CRASHED — see crash.txt in {output}", file=sys.stderr)

    if summary['audio_events'] > 0:
        print(f"\nRender audio: bake-audio {output}/output/audio_events.jsonl "
              f"-o {output}/output/audio.wav", file=sys.stderr)


if __name__ == "__main__":
    main()
