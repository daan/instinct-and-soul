"""
flash.py — copy a creature's main.py onto a USB-attached MicroPython board.

Usage:
    flash creatures/cores3
    flash creatures/cores3 --port /dev/ttyACM0

Without --port, looks for a single USB serial device and uses it.
Errors clearly when zero or multiple ports are found.
"""

import argparse
import os
import subprocess
import sys

from serial_device import usb_devices


def _describe(d):
    return f"{d.device}  {d.manufacturer or '?'}  {d.product or '?'}"


def detect_port():
    devices = usb_devices()
    if not devices:
        raise SystemExit("flash: no USB serial device found — pass --port explicitly")
    if len(devices) > 1:
        lines = ["flash: multiple USB serial devices detected — pass --port to choose:"]
        for d in devices:
            lines.append(f"  {_describe(d)}")
        raise SystemExit("\n".join(lines))
    d = devices[0]
    print(f"flash: found USB device: {_describe(d)}")
    return d.device


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
