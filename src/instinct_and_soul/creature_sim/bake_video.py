"""bake-video — render an instinct's sonification over a Blender skeleton video.

    bake-video sim_creatures/dancer --from-mocap data/mocap/out/<clip>.json --wrist left \
               [--instinct latest|<session>|<session>:<seq>|<file.py>] [--fps 30] [-o OUT.mp4]

Pipeline (everything reused except the Blender render):
  1. pick an instinct (default: the latest evolved one),
  2. run it on the clip (no LLM) → its sonification WAV (bake-audio),
  3. render the dancer skeleton from the same clip in Blender — cached per clip+fps so
     trying other instincts reuses it,
  4. mux video + WAV with ffmpeg (both share the clip timebase → frame-exact, no stretch).
Output: data/mocap/renders/<clip>__<creature>__<instinct-tag>.mp4
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import devices
from .bridge import bake as bridge_bake
from .fake_imu import load_imu_source
from .runner import run_sim
from .bake_audio import bake as bake_audio
from ..reflection import find_last_session


def resolve_instinct(creature_dir, selector):
    """Return (code, tag) for the chosen instinct.
    selector: None/'seed' | 'latest' | <session_id> | <session_id>:<seq> | <file.py>."""
    logs = os.path.join(creature_dir, "logs")
    if not selector or selector == "seed":
        return open(os.path.join(creature_dir, "seed_instinct.py")).read(), "seed"
    if selector.endswith(".py"):
        return open(selector).read(), os.path.splitext(os.path.basename(selector))[0]
    if ":" in selector:
        sid, seq = selector.split(":", 1)
        # match either store format: v2 `*_v{n:03d}.py` or v1 `{n:03d}_*.py`
        m = (sorted(glob.glob(os.path.join(logs, sid, "instinct", f"*_v{int(seq):03d}.py")))
             or sorted(glob.glob(os.path.join(logs, sid, "instinct", f"{int(seq):03d}_*.py"))))
        if not m:
            raise SystemExit(f"no instinct {seq} in session {sid}")
        return open(m[-1]).read(), f"{sid}_v{int(seq)}"
    sess = find_last_session(logs) if selector == "latest" else os.path.join(logs, selector)
    if not sess or not os.path.isdir(sess):
        raise SystemExit(f"no session for --instinct {selector!r} under {logs}")
    insts = sorted(glob.glob(os.path.join(sess, "instinct", "*.py")))
    if not insts:
        raise SystemExit(f"no instinct files in {sess}")
    from ..reflection import parse_version_filename
    seq = parse_version_filename(insts[-1])[1]
    return open(insts[-1]).read(), f"{os.path.basename(sess)}_v{seq}"


def find_blender():
    b = shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
    if not (os.path.isfile(b) or shutil.which(b)):
        raise SystemExit("Blender not found — install it or put `blender` on PATH.")
    return b


def render_skeleton(clip, out_video, fps, res, samples):
    blender = find_blender()
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "mocaplib", "blender_skeleton.py")
    print(f"rendering skeleton ({fps} fps) → {os.path.relpath(out_video)} (Blender)…",
          file=sys.stderr)
    r = subprocess.run([blender, "--background", "--factory-startup", "--python", script,
                        "--", clip, out_video, "--fps", str(fps), "--res", str(res),
                        "--samples", str(samples)])
    if r.returncode != 0 or not os.path.isfile(out_video):
        raise SystemExit(f"Blender render failed (exit {r.returncode}).")


def main():
    p = argparse.ArgumentParser(description="Render an instinct's sonification over a Blender dancer.")
    p.add_argument("creature_path", help="A creature dir (e.g. sim_creatures/dancer).")
    p.add_argument("--from-mocap", required=True, metavar="CLIP", help="A baked mocap clip JSON.")
    p.add_argument("--wrist", default="left", choices=("left", "right"))
    p.add_argument("--instinct", default="latest",
                   help="latest (default) | <session_id> | <session_id>:<seq> | <file.py> | seed")
    p.add_argument("--fps", type=int, default=30, help="Render framerate (default 30).")
    p.add_argument("--res", type=int, default=1024, help="Square render resolution.")
    p.add_argument("--samples", type=int, default=32, help="Eevee samples.")
    p.add_argument("--rerender", action="store_true", help="Force a fresh Blender render.")
    p.add_argument("-o", "--output", default=None, help="Output mp4 path.")
    args = p.parse_args()

    creature_dir = os.path.normpath(args.creature_path)
    if not os.path.isfile(args.from_mocap):
        raise SystemExit(f"mocap clip not found: {args.from_mocap}")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found — install it (e.g. `brew install ffmpeg`).")

    device = devices.read_device(creature_dir)
    screen = devices.resolve(device)["screen"]
    code, tag = resolve_instinct(creature_dir, args.instinct)
    creature = os.path.basename(creature_dir)
    clip_stem = os.path.splitext(os.path.basename(args.from_mocap))[0]
    renders = os.path.join(os.path.dirname(os.path.dirname(args.from_mocap)), "renders")
    os.makedirs(renders, exist_ok=True)

    print(f"creature: {creature}  device: {device}", file=sys.stderr)
    print(f"instinct: {tag}", file=sys.stderr)

    # 1+2. Run the instinct on the clip → its sonification WAV.
    imu_path = bridge_bake(args.from_mocap, args.wrist)
    imu_source = load_imu_source(imu_path)
    run_dir = os.path.join("sim_out", f"{creature}__{tag}")
    run_sim(instinct_code=code, imu_source=imu_source,
            duration_ms=imu_source.duration_ms, output_dir=run_dir,
            meta={"kind": "sim", "creature": args.creature_path, "source": args.from_mocap,
                  "wrist": args.wrist, "device": device,
                  "screen": {"w": screen[0], "h": screen[1]}},
            screen=screen)
    wav = os.path.join(run_dir, "output", "audio.wav")
    summary = bake_audio(os.path.join(run_dir, "output", "audio_events.jsonl"), wav)
    print(f"audio:    {summary.get('tones', 0)} tones → {os.path.relpath(wav)}", file=sys.stderr)

    # 3. Skeleton video — cached per clip + fps.
    cached_video = os.path.join(renders, f"{clip_stem}__skeleton_{args.fps}fps.mp4")
    if args.rerender or not os.path.isfile(cached_video):
        render_skeleton(args.from_mocap, cached_video, args.fps, args.res, args.samples)
    else:
        print(f"reusing cached skeleton video {os.path.relpath(cached_video)}", file=sys.stderr)

    # 4. Mux (stream-copy video + AAC audio; same timebase → no stretch).
    out = args.output or os.path.join(renders, f"{clip_stem}__{creature}__{tag}.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", cached_video, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-shortest", out], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"\n✓ {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
