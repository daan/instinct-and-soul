"""
boot_watch.py — reboot forensics over USB serial.

MicroPython's machine.reset_cause() reports a brownout as PWRON, so the
tuner can't distinguish "the 5V input dropped" from "the 3.3V rail dipped
under WiFi load". The ROM bootloader can: at the moment of death it prints
its reset reason (e.g. "Brownout detector was triggered", or
"rst:0x15 (USB_UART_CHIP_RESET)") on the USB serial console.

This script tails the StickS3's serial port, timestamps every line, tees
to a log file, and — crucially — survives the reboot: the USB port node
vanishes when the board resets and reappears a second later, so it keeps
re-scanning and reattaches automatically. Reset-related lines are marked
with ">>>".

Run (board on LAPTOP USB — the port must be visible to this machine):
    .venv/bin/python test/STICKS3/boot_watch.py

Then leave it running next to the tuner and wait for a death. Watch for:
    Brownout detector was triggered   -> supply/rail sag (power problem)
    rst:0x1 (POWERON) with no brownout line -> 5V input fully power-cycled
    Guru Meditation / Fatal exception -> firmware crash after all
"""

import glob
import sys
import time

import serial

BAUD = 115200
PORT_GLOBS = ("/dev/tty.usbmodem*", "/dev/tty.usbserial*")
MARKERS = ("Brownout", "brownout", "rst:", "boot:", "reset cause",
           "Guru Meditation", "Fatal", "abort()")

LOG_PATH = time.strftime("boot-watch-%Y%m%d-%H%M%S.log")


def find_port():
    for pattern in PORT_GLOBS:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return None


def main():
    log = open(LOG_PATH, "a")
    print("logging to", LOG_PATH)
    print("waiting for a serial port ({})".format(", ".join(PORT_GLOBS)))
    attached = None
    while True:
        port = find_port()
        if port is None:
            if attached is not None:
                emit(log, "--- port gone (board resetting or unplugged) ---")
                attached = None
            time.sleep(0.5)
            continue
        try:
            with serial.Serial(port, BAUD, timeout=1) as ser:
                attached = port
                emit(log, "--- attached to {} ---".format(port))
                buf = b""
                while True:
                    chunk = ser.read(256)
                    if chunk:
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            text = line.decode("utf-8", "replace").rstrip("\r")
                            if text:
                                mark = ">>> " if any(m in text for m in MARKERS) else "    "
                                emit(log, mark + text)
        except (serial.SerialException, OSError):
            # the port node evaporates on reset — loop around and re-scan
            time.sleep(0.5)
        except KeyboardInterrupt:
            emit(log, "--- boot_watch stopped ---")
            log.close()
            sys.exit(0)


def emit(log, text):
    line = "{}  {}".format(time.strftime("%H:%M:%S"), text)
    print(line, flush=True)
    log.write(line + "\n")
    log.flush()


if __name__ == "__main__":
    main()
