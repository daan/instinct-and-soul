"""creature-sim — run a creature's instinct.py in a fake M5 environment."""
import argparse
import os
import sys

from . import devices
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
    p.add_argument("--device", default=None, choices=sorted(devices.DEVICES),
                   help="Override the body. Default: the creature.toml device "
                        f"(else {devices.DEFAULT_DEVICE}).")
    args = p.parse_args()

    instinct_path = _resolve_instinct_path(args.code_path)

    # Resolve the body: --device override, else the creature.toml device.
    creature_dir = (args.code_path if os.path.isdir(args.code_path)
                    else os.path.dirname(os.path.abspath(args.code_path)))
    device = args.device or devices.read_device(creature_dir)
    screen = devices.resolve(device)["screen"]

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
        # Name the run after the creature dir, not the instinct file — every
        # creature's instinct is seed_instinct.py, so the file stem collides.
        code_path = os.path.normpath(args.code_path)
        if os.path.isdir(code_path):
            stem = os.path.basename(code_path)
        else:
            stem = os.path.splitext(os.path.basename(code_path))[0]
        output = os.path.join("sim_out", stem)
    else:
        output = args.output

    with open(instinct_path) as f:
        instinct_code = f.read()

    print(f"instinct: {instinct_path}", file=sys.stderr)
    print(f"device:   {device}  ({screen[0]}x{screen[1]})", file=sys.stderr)
    print(f"imu:      {imu_path}  ({source_s:.2f}s, {len(imu_source.t_ms)} samples)", file=sys.stderr)
    print(f"duration: {duration_ms/1000.0:.2f}s", file=sys.stderr)
    print(f"output:   {output}", file=sys.stderr)

    # Nominal sample rate of the driving stream (exact source fps for mocap).
    fps = (round((len(imu_source.t_ms) - 1) / (imu_source.duration_ms / 1000.0), 3)
           if imu_source.duration_ms > 0 else None)
    meta = {
        "kind": "sim",
        "creature": args.code_path,
        "instinct": os.path.relpath(instinct_path),
        "source": args.from_mocap or imu_path,
        "wrist": args.wrist if args.from_mocap else None,
        "fps": fps,
        "device": device,
        "screen": {"w": screen[0], "h": screen[1]},
        "params": {},
    }

    summary = run_sim(
        instinct_code=instinct_code,
        imu_source=imu_source,
        duration_ms=duration_ms,
        output_dir=output,
        meta=meta,
        screen=screen,
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
