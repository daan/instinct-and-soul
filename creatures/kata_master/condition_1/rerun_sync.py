"""
rerun_sync.py — one timeline for a kata take: the IMU trace beside the video.

The webcam records VARIABLE frame rate, so an NLE's constant-fps timeline
quietly shears the two apart. Rerun does not: the mp4's own frame timestamps
are read out of the container (the QuickTime -> `ffmpeg -c copy` remux
preserves them exactly) and every IMU sample is placed at its measured
microsecond. One shared clock, both instruments honest.

THE CLOCK'S ZERO is the take's SYNC MARK: the `record` recipe counts in with
low wood-block clicks, then at t=0 sounds a HIGH wood block and flashes the
stick's screen WHITE. The .jsonl already starts at that mark (t=0); the video
needs you to tell it where the mark is once:

    mpv "~/Movies/2026-08-20 13-29-36.mp4"
        pause near the flash, then , and . step single frames; the OSD
        timecode at the first white-screen frame is your --sync. (The high
        click on the audio track is the same instant, if the flash is
        off-camera.)

THE REPLAY IS THE POINT. Beside the raw trace, the take is run through
lib/kata_sense.py — the very organ the creature wears — and its speed01, the
four thresholds of its ladder, and every launch/land/overrun it would have
fired land on the same timeline. Scrub to a kata in the video and see what
the sense made of it; nudge a knob and run again:

    --knob launch=0.70 --knob set_dwell_s=0.30     (repeatable; the defaults
                                                    are test_kata_parity's)

Usage:
    uv run creatures/kata_master/condition_1/rerun_sync.py \
        --take 4 --video ~/Movies/"2026-08-20 13-29-36.mp4" --sync 3.42

    --take N        recordings/rec_NNN.jsonl (+ .meta.json for the label)
    --imu PATH      or name the .jsonl directly
    --video PATH    the mp4 (H.264 plays in the viewer natively)
    --sync SECS     video time of the white flash / high click (default 0)
    --knob K=V      override a KataSense knob for this replay
    --dir DIR       where the takes live (default recordings/)
    --save PATH     write an .rrd instead of spawning the viewer

If the viewer shows the video entity but no picture, the codec is one it
cannot decode — re-encode once with
    ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4
(the timestamps survive a re-encode; only `-r` would destroy them).
"""

import argparse
import json
import os
import sys

import numpy as np
import rerun as rr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from calc import Calc
from kata_sense import KataSense

TIMELINE = "kata"

# test_kata_parity.py's knob set — the documented calibration, so a replay
# with no --knob shows exactly what the parity-tested organ would have heard.
KNOBS = dict(quiet=0.20, spent=0.30, rearm=0.55, launch=0.75,
             set_dwell_s=0.35, land_hold_s=0.22, refract_s=0.20,
             max_flight_s=1.2, set_linger_s=0.25,
             rot_fs=600.0, acc_fs=25.0,
             speed_tau_s=0.04, grav_tau_s=0.12, act_tau_s=2.0)


def load_imu(path):
    """The .jsonl pull_recordings.py writes: t in MILLISECONDS from the sync
    mark (the same convention creature_sim's JsonlImuSource reads)."""
    t, acc, gyr = [], [], []
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            t.append(d["t"] / 1000.0)
            acc.append((d["ax"], d["ay"], d["az"]))
            gyr.append((d["gx"], d["gy"], d["gz"]))
    return np.asarray(t), np.asarray(acc), np.asarray(gyr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--take", type=int, help="recordings/rec_NNN")
    ap.add_argument("--imu", help="path to a rec_NNN.jsonl")
    ap.add_argument("--video", required=True, help="the take's mp4")
    ap.add_argument("--sync", type=float, default=0.0,
                    help="video time (s) of the white flash / high click")
    ap.add_argument("--knob", action="append", default=[],
                    metavar="K=V", help="override a KataSense knob")
    ap.add_argument("--dir", default="recordings")
    ap.add_argument("--save", help="write .rrd here instead of spawning")
    args = ap.parse_args()

    if args.imu:
        imu_path = args.imu
    elif args.take is not None:
        imu_path = os.path.join(args.dir, "rec_{:03d}.jsonl".format(args.take))
    else:
        ap.error("give --take N or --imu PATH")
    if not os.path.exists(imu_path):
        sys.exit("no such take: {}".format(imu_path))
    video_path = os.path.expanduser(args.video)
    if not os.path.exists(video_path):
        sys.exit("no such video: {}".format(video_path))

    label = os.path.basename(imu_path)
    meta_path = imu_path.replace(".jsonl", ".meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        label = "{} ({} @{:.0f}Hz, {:.1f}s)".format(
            meta.get("label", label), os.path.basename(imu_path),
            meta.get("hz_actual", 0), meta.get("duration_s", 0))

    rr.init("kata_sync", spawn=args.save is None)
    if args.save:
        rr.save(args.save)

    # ── the IMU, at its measured microseconds ─────────────────────────────
    t_s, acc, gyr = load_imu(imu_path)
    for group, data, axes in (("accel_g", acc, "xyz"), ("gyro_dps", gyr, "xyz")):
        for i, ax_name in enumerate(axes):
            rr.send_columns(
                "imu/{}/{}".format(group, ax_name),
                indexes=[rr.TimeColumn(TIMELINE, duration=t_s)],
                columns=rr.Scalars.columns(scalars=data[:, i]),
            )
    print("imu:   {} samples over {:.2f}s  <- {}".format(
        len(t_s), t_s[-1] - t_s[0], imu_path))

    # ── the organ itself, replayed over the take ──────────────────────────
    knobs = dict(KNOBS)
    for kv in args.knob:
        k, _, v = kv.partition("=")
        if k not in knobs:
            sys.exit("unknown knob {!r} — knows: {}".format(
                k, " ".join(sorted(knobs))))
        knobs[k] = float(v)
    ks = KataSense(Calc, **knobs)
    speed01 = np.empty(len(t_s))
    activity = np.empty(len(t_s))
    events = []
    for i in range(len(t_s)):
        ev = ks.step(tuple(acc[i]), tuple(gyr[i]), float(t_s[i]))
        speed01[i] = ks.speed01
        activity[i] = ks.activity
        if ev is not None:
            events.append((float(t_s[i]), ev))

    rr.send_columns(
        "sense/speed01",
        indexes=[rr.TimeColumn(TIMELINE, duration=t_s)],
        columns=rr.Scalars.columns(scalars=speed01),
    )
    # the ladder, as flat lines through the same plot: where speed01 sits
    # relative to them IS the organ's whole decision
    ends = np.array([t_s[0], t_s[-1]])
    for name in ("quiet", "spent", "rearm", "launch"):
        rr.send_columns(
            "sense/{}".format(name),
            indexes=[rr.TimeColumn(TIMELINE, duration=ends)],
            columns=rr.Scalars.columns(scalars=np.full(2, knobs[name])),
        )
    rr.send_columns(
        "activity/dps",
        indexes=[rr.TimeColumn(TIMELINE, duration=t_s)],
        columns=rr.Scalars.columns(scalars=activity),
    )
    for t_ev, ev in events:
        rr.set_time(TIMELINE, duration=t_ev)
        rr.log("events", rr.TextLog("{:.2f}s  {}".format(t_ev, ev),
                                    level="INFO"))
    kinds = [ev[0] for _, ev in events]
    print("sense: {} events over the take: {}".format(
        len(events), " ".join(kinds) if kinds else "none"))
    for t_ev, ev in events:
        print("       {:7.2f}s  {}".format(t_ev, ev))

    # ── the video, at the container's own (VFR) timestamps ────────────────
    video = rr.AssetVideo(path=video_path)
    rr.set_time(TIMELINE, duration=-args.sync)
    rr.log("video", video)
    frame_ns = video.read_frame_timestamps_nanos()
    frame_s = 1e-9 * np.asarray(frame_ns) - args.sync   # sync mark -> t=0
    rr.send_columns(
        "video",
        indexes=[rr.TimeColumn(TIMELINE, duration=frame_s)],
        columns=rr.VideoFrameReference.columns_nanos(frame_ns),
    )
    print("video: {} frames, {:.2f}s, sync mark at {:.3f}s  <- {}".format(
        len(frame_ns), frame_s[-1] - frame_s[0], args.sync, video_path))

    rr.log("take", rr.TextDocument(label), static=True)
    if args.save:
        print("wrote {}".format(args.save))
    else:
        print("viewer spawned — timeline '{}', t=0 is the sync mark".format(
            TIMELINE))


if __name__ == "__main__":
    main()
