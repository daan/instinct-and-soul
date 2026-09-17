"""
pull_recordings.py — bring the board's IMU traces over USB and unpack them.

The `record` tuner recipe writes each take to flash as rec_NNN.bin: a 64-byte
header and then one 28-byte record per sample. This copies them off, converts
to the .jsonl the offline tools already read (creature_sim/fake_imu.py's
JsonlImuSource — the same shape a sim session logs to input/imu_stream.jsonl),
and writes a sidecar .meta.json with the take's label and its sampling health.

Usage:
    uv run creatures/kata_master/condition_1/pull_recordings.py
    uv run .../pull_recordings.py --list              # what is on the board
    uv run .../pull_recordings.py --out recordings/   # where they land
    uv run .../pull_recordings.py --delete            # remove after a good pull
    uv run .../pull_recordings.py --port /dev/cu.usbmodem1101
    uv run .../pull_recordings.py --convert rec_001.bin   # a local .bin, no board

The board keeps its copy unless --delete is passed, and --delete only fires
after the file has been read back and converted — a take is hard to re-perform,
so nothing is removed on the strength of a copy that was never opened.

Wire format (little-endian; written by the `record` recipe in recipes.py):
    header, 64 B   0  magic b"KATAREC1"
                   8  H  nominal hz        10  I  n_samples
                  14  I  end mark, us      18  I  board uptime at save, ms
                  22  I  worst gap, us     26  I  count of late samples
                  30  I  nominal period, us
                  48  16s label, nul-padded
    sample, 28 B   0  I  microseconds since the SYNC MARK (t=0)
                   4  6f ax ay az (g), gx gy gz (deg/s)
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys

HDR = 64
REC = 28
MAGIC = b"KATAREC1"
# The recipe writes to /flash when the build has it, else the root. Which one
# mpremote sees depends on the firmware's VFS layout, so look in both.
DEVICE_DIRS = (":", ":flash/")
NAME_RE = re.compile(r"^rec_(\d{3})\.bin$")


# ── talking to the board ───────────────────────────────────────────────────

def detect_port():
    """Reuse the flash tool's port detection, so both agree on the board."""
    try:
        from instinct_and_soul.flash import detect_port as _dp
    except ImportError:
        sys.exit("pull_recordings: run me with `uv run` from the repo root "
                 "so instinct_and_soul is importable, or pass --port")
    return _dp()


def mpremote(port, *args):
    r = subprocess.run(["mpremote", "connect", port, *args],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace").strip()
        raise RuntimeError("mpremote {}: {}".format(" ".join(args), err))
    return r.stdout.decode(errors="replace")


def list_takes(port):
    """[(device_path, name, size)] for every rec_NNN.bin the board holds.

    The name is carried separately rather than recovered with basename: a
    device path is ":rec_001.bin", whose basename keeps the colon and would
    end up in the filenames we write locally."""
    seen = {}
    for d in DEVICE_DIRS:
        try:
            out = mpremote(port, "fs", "ls", d)
        except RuntimeError:
            continue          # that directory does not exist on this build
        for line in out.splitlines():
            bits = line.split()
            if len(bits) != 2:
                continue
            size, name = bits
            # depending on the firmware's VFS layout the same file can list
            # under both roots — first sighting wins
            if NAME_RE.match(name) and name not in seen:
                seen[name] = (d + name, name, int(size))
    return [seen[n] for n in sorted(seen)]


# ── the file itself ────────────────────────────────────────────────────────

def parse(blob, source):
    if len(blob) < HDR or blob[:8] != MAGIC:
        raise ValueError("{}: not a KATAREC1 trace".format(source))
    hz, n, end_us, uptime_ms, max_gap_us, gaps, period_us = struct.unpack_from(
        "<HIIIIII", blob, 8)
    label = blob[48:64].split(b"\x00")[0].decode("ascii", "replace")

    body = blob[HDR:]
    have = len(body) // REC
    if have < n:
        print("  ! header claims {} samples, file holds {} — using {}".format(
            n, have, have), file=sys.stderr)
        n = have

    samples = []
    for i in range(n):
        t_us, ax, ay, az, gx, gy, gz = struct.unpack_from("<Iffffff", body,
                                                          i * REC)
        samples.append((t_us, ax, ay, az, gx, gy, gz))

    meta = {
        "label": label,
        "hz_nominal": hz,
        "period_us_nominal": period_us,
        "samples": n,
        "duration_s": (samples[-1][0] / 1e6) if samples else 0.0,
        "sync_mark_s": 0.0,      # t=0 IS the click+flash: line the video up here
        "end_mark_s": end_us / 1e6,
        "board_uptime_s_at_save": uptime_ms / 1000.0,
        "worst_gap_ms": max_gap_us / 1000.0,
        "late_samples": gaps,
        "source": source,
    }
    if samples:
        meta["hz_actual"] = (n - 1) / (samples[-1][0] / 1e6) if samples[-1][0] else 0.0
        # A dead IMU is not an exception, it is six zero channels under
        # perfect timestamps (aug20_1, 2026-08-20 — a filmed session's take,
        # discovered flat only days later). Count them here so a bad take is
        # loud at PULL time, while re-recording is still cheap.
        meta["all_zero_samples"] = sum(
            1 for s in samples
            if s[1] == 0.0 and s[2] == 0.0 and s[3] == 0.0
            and s[4] == 0.0 and s[5] == 0.0 and s[6] == 0.0)
    return meta, samples


def write_jsonl(path, samples):
    with open(path, "w") as f:
        for t_us, ax, ay, az, gx, gy, gz in samples:
            # `t` is milliseconds — what JsonlImuSource and the sim clock use
            f.write(json.dumps({"t": t_us / 1000.0, "ax": ax, "ay": ay,
                                "az": az, "gx": gx, "gy": gy, "gz": gz}) + "\n")


def report(meta):
    print("  label {!r}  {} samples  {:.1f}s  {:.1f} Hz actual "
          "(nominal {})".format(meta["label"], meta["samples"],
                                meta["duration_s"], meta.get("hz_actual", 0.0),
                                meta["hz_nominal"]))
    late, worst = meta["late_samples"], meta["worst_gap_ms"]
    verdict = "clean" if late == 0 else "{} late".format(late)
    print("  sampling: {}, worst gap {:.1f} ms (nominal {:.1f})".format(
        verdict, worst, meta["period_us_nominal"] / 1000.0))
    if late:
        print("  ! gaps mean samples landed off-cadence. The timestamps stay "
              "honest, so a replay is still valid — but if the gaps land on "
              "strikes, peak speed01 reads low. Check before trusting peaks.")
    print("  video sync: t=0 is the click+flash; the end mark is at "
          "{:.3f}s".format(meta["end_mark_s"]))
    zeros = meta.get("all_zero_samples", 0)
    if zeros == meta["samples"]:
        print("  !! EVERY sample is all-zero: the IMU was dead for this "
              "take. The file is a diary of nothing — reboot the stick "
              "and re-record.")
    elif zeros > meta["samples"] // 10:
        print("  ! {} of {} samples are all-zero — the IMU dropped out "
              "during the take".format(zeros, meta["samples"]))


def convert(blob, source, out_dir, stem):
    meta, samples = parse(blob, source)
    if not samples:
        print("  ! no samples — nothing written", file=sys.stderr)
        return None
    os.makedirs(out_dir, exist_ok=True)
    jsonl = os.path.join(out_dir, stem + ".jsonl")
    write_jsonl(jsonl, samples)
    with open(os.path.join(out_dir, stem + ".meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    report(meta)
    print("  -> {}".format(jsonl))
    return jsonl


# ── entry point ────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default=None, help="USB serial device")
    p.add_argument("--out", default="recordings",
                   help="where the .jsonl land (default: recordings/)")
    p.add_argument("--list", action="store_true",
                   help="show the board's takes and exit")
    p.add_argument("--delete", action="store_true",
                   help="remove each take from the board once converted")
    p.add_argument("--convert", metavar="FILE", nargs="+",
                   help="convert local .bin files; never touches the board")
    args = p.parse_args()

    if args.convert:
        for path in args.convert:
            print(os.path.basename(path))
            with open(path, "rb") as f:
                convert(f.read(), path, args.out,
                        os.path.splitext(os.path.basename(path))[0])
        return

    port = args.port or detect_port()
    takes = list_takes(port)
    if not takes:
        print("no rec_NNN.bin on the board. Deploy the recorder from the "
              "tuner (`record <label> <secs>`) and press BtnA to take one.")
        return

    print("{} take(s) on {}".format(len(takes), port))
    for path, _name, size in takes:
        print("  {}  {:.1f} KB  (~{:.0f}s at 200 Hz)".format(
            path, size / 1024.0, max(0, size - HDR) / REC / 200.0))
    if args.list:
        return

    for path, name, _size in takes:
        stem = os.path.splitext(name)[0]
        print("\n{}".format(stem))
        # `fs cp`, not `fs cat`: cat routes the bytes through a text stream,
        # and a trace is binary. The .bin is kept alongside the .jsonl — it
        # is the original, and a take cannot be re-performed.
        os.makedirs(args.out, exist_ok=True)
        raw = os.path.join(args.out, stem + ".bin")
        mpremote(port, "fs", "cp", path, raw)
        with open(raw, "rb") as f:
            blob = f.read()
        if convert(blob, path, args.out, stem) and args.delete:
            mpremote(port, "fs", "rm", path)
            print("  removed from board")


if __name__ == "__main__":
    main()
