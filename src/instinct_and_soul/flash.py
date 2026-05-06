"""
flash.py — copy a creature's main.py onto a USB-attached MicroPython board.

Usage:
    flash creatures/cores3
    flash creatures/cores3 --port /dev/cu.usbmodem3101

Without --port, looks for a single /dev/cu.usbmodem* device and uses it.
Errors clearly when zero or multiple ports are found.
"""

import argparse
import glob
import os
import subprocess
import sys


def detect_port():
    candidates = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not candidates:
        raise SystemExit("flash: no /dev/cu.usbmodem* device found — pass --port explicitly")
    if len(candidates) > 1:
        raise SystemExit(
            "flash: multiple boards detected ({}) — pass --port to choose".format(
                ", ".join(candidates)))
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="Flash main.py onto a board")
    parser.add_argument("creature_path",
                        help="Path to a directory containing main.py (e.g. creatures/cores3)")
    parser.add_argument("--port", default=None,
                        help="Serial port (auto-detected if omitted)")
    args = parser.parse_args()

    main_py = os.path.join(args.creature_path, "main.py")
    if not os.path.isfile(main_py):
        parser.error("no main.py in {}".format(args.creature_path))

    port = args.port or detect_port()
    print("flash: {} -> {}".format(main_py, port))

    cmds = [
        ["mpremote", "connect", port, "cp", main_py, ":main.py"],
        ["mpremote", "connect", port, "reset"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            sys.exit(result.returncode)


if __name__ == "__main__":
    main()
