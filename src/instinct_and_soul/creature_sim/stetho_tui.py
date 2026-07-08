"""stetho — the live dashboard for the creature's EEG.

Listens for the stethoscope's UDP-OSC on :9001 (SO_REUSEPORT, so it can sit
beside any other monitor) and renders two panels with rich:

  LEVELS   one row per /probe/<name>: current value + a sparkline
  EVENTS   a scrolling ticker of /organ/<kind> events

Advisory by contract: this shows what arrives; output/organ_events.jsonl in
the session is the authoritative record. Works identically whether the body
is the simulator on this machine or, later, a device on the network.

Usage:
    stetho                 # listen on :9001
    stetho --port 9002
"""
import argparse
import json
import socket
import struct
import time
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

SPARK = "▁▂▃▄▅▆▇█"


def _osc_parse(data):
    """(addr, [args]) for the stethoscope's two shapes (,if and ,is)."""
    try:
        end = data.index(b"\x00")
        addr = data[:end].decode()
        off = (end + 4) & ~3
        tend = data.index(b"\x00", off)
        tags = data[off:tend].decode()[1:]
        off = off + (((tend - off) + 4) & ~3)
        args = []
        for t in tags:
            if t == "i":
                args.append(struct.unpack_from(">i", data, off)[0]); off += 4
            elif t == "f":
                args.append(struct.unpack_from(">f", data, off)[0]); off += 4
            elif t == "s":
                send = data.index(b"\x00", off)
                args.append(data[off:send].decode()); off = (send + 4) & ~3
        return addr, args
    except (ValueError, struct.error, UnicodeDecodeError):
        return None, None


def _spark(values, width=24):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = list(values)[-width:]
    return "".join(SPARK[min(7, int((v - lo) / span * 7.999))] for v in pts)


EVENT_STYLES = {
    "touch": "cyan", "familiar": "green", "familiar_new": "yellow",
    "recognized": "bold green", "reunify": "magenta", "state": "blue",
    "turned": "blue", "startle": "bold red", "attempt": "magenta",
    "strike": "bold cyan",
}


def main():
    ap = argparse.ArgumentParser(description="Live organ dashboard (UDP-OSC :9001).")
    ap.add_argument("--port", type=int, default=9001)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.1)

    probes = {}                 # name -> deque of values
    latest = {}                 # name -> (t_ms, value)
    events = deque(maxlen=18)   # (t_ms, kind, payload)
    n_rx = [0]
    last_rx = [None]

    def render():
        tbl = Table(title=None, expand=True, show_edge=False, pad_edge=False)
        tbl.add_column("level", style="bold", no_wrap=True)
        tbl.add_column("value", justify="right", no_wrap=True)
        tbl.add_column("trend", no_wrap=True)
        for name in sorted(probes):
            t, v = latest[name]
            tbl.add_row(name, f"{v:.2f}", _spark(probes[name]))
        ev = Text()
        for t, kind, payload in events:
            ev.append(f"{t/1000.0:8.2f}s  ", style="dim")
            ev.append(f"{kind:<13}", style=EVENT_STYLES.get(kind, "white"))
            ev.append(f" {payload}\n")
        age = "" if last_rx[0] is None else f" · last packet {time.time()-last_rx[0]:.0f}s ago"
        return Group(
            Panel(tbl, title=f"levels  (:{args.port} · {n_rx[0]} pkts{age})"),
            Panel(ev or Text("waiting for organ events…", style="dim"),
                  title="events"),
        )

    console = Console()
    with Live(render(), console=console, refresh_per_second=8) as live:
        while True:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                live.update(render())
                continue
            except KeyboardInterrupt:
                break
            addr, a = _osc_parse(data)
            if not addr or not a:
                continue
            n_rx[0] += 1
            last_rx[0] = time.time()
            if addr.startswith("/probe/") and len(a) >= 2:
                name = addr[7:]
                probes.setdefault(name, deque(maxlen=48)).append(float(a[1]))
                latest[name] = (a[0], float(a[1]))
            elif addr.startswith("/organ/") and len(a) >= 2:
                kind = addr[7:]
                try:
                    payload = json.loads(a[1])
                    payload = " ".join(f"{k}={v}" for k, v in payload.items())
                except Exception:
                    payload = a[1]
                events.append((a[0], kind, payload))
            live.update(render())


if __name__ == "__main__":
    main()
