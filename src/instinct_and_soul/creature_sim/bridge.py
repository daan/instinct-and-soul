"""bake-imu — bridge a baked mocap clip into a one-sensor IMU stream (jsonl).

The mocap factory (bake-mocap) writes a rich JSON with both wrists + skeleton.
The simulator wants one sensor's dense stream. This strips it down:

    load data/mocap/out/<clip>.json  →  pick a wrist (default: left)
    t[i] = i / fps * 1000
    write {t, ax, ay, az, gx, gy, gz} per line   # already g & deg/s

The output is the sim's input stream — transient and regenerable, so it lands
under sim_in/ by default. See docs/SIM.md (Decision 4).
"""
import argparse
import json
import os
import sys

import numpy as np


def mocap_to_imu(clip_json_path: str, wrist: str = "left"):
    """Return (t_ms, accel, gyro) for one wrist from a baked mocap clip.

    accel is g, gyro is deg/s — the units bake-mocap already emits.
    """
    with open(clip_json_path) as f:
        d = json.load(f)
    if wrist not in d.get("imu", {}):
        have = ", ".join(sorted(d.get("imu", {}))) or "none"
        raise SystemExit(f"clip has no '{wrist}' wrist (have: {have})")
    fps = float(d["fps"])
    n = int(d["n_frames"])
    imu = d["imu"][wrist]
    accel = np.asarray(imu["acc"], dtype=np.float64)
    gyro = np.asarray(imu["gyro"], dtype=np.float64)
    if accel.shape[0] != n or gyro.shape[0] != n:
        raise SystemExit(
            f"clip imu length ({accel.shape[0]}) != n_frames ({n})")
    t_ms = np.arange(n, dtype=np.float64) / fps * 1000.0
    return t_ms, accel, gyro


def write_imu_jsonl(t_ms, accel, gyro, out_path: str) -> str:
    """Write a {t, ax..az, gx..gz} jsonl stream. Returns out_path."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        for i in range(len(t_ms)):
            a = accel[i]
            g = gyro[i]
            f.write(json.dumps({
                "t": round(float(t_ms[i]), 3),
                "ax": round(float(a[0]), 4), "ay": round(float(a[1]), 4), "az": round(float(a[2]), 4),
                "gx": round(float(g[0]), 4), "gy": round(float(g[1]), 4), "gz": round(float(g[2]), 4),
            }) + "\n")
    return out_path


def bake(clip_json_path: str, wrist: str = "left", out_path: str | None = None) -> str:
    """mocap clip JSON → IMU jsonl stream. Returns the output path."""
    t_ms, accel, gyro = mocap_to_imu(clip_json_path, wrist)
    if out_path is None:
        stem = os.path.splitext(os.path.basename(clip_json_path))[0]
        out_path = os.path.join("sim_in", f"{stem}_{wrist}.jsonl")
    return write_imu_jsonl(t_ms, accel, gyro, out_path)


def main() -> int:
    p = argparse.ArgumentParser(description="Bridge a mocap clip JSON into an IMU jsonl stream.")
    p.add_argument("clip", help="A baked mocap clip JSON (from bake-mocap).")
    p.add_argument("--wrist", default="left", choices=("left", "right"),
                   help="Which wrist to extract (default: left).")
    p.add_argument("-o", "--output", default=None,
                   help="Output jsonl path (default: sim_in/<clip>_<wrist>.jsonl).")
    args = p.parse_args()

    if not os.path.isfile(args.clip):
        print(f"clip not found: {args.clip}", file=sys.stderr)
        return 1

    out = bake(args.clip, args.wrist, args.output)
    t_ms, accel, gyro = mocap_to_imu(args.clip, args.wrist)
    secs = (t_ms[-1] - t_ms[0]) / 1000.0
    print(f"baked {len(t_ms)} samples ({secs:.1f}s, {args.wrist} wrist) → {out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
