"""Live IMU over OSC: receive the CoreS3Recorder stream, log it, serve reads.

The CoreS3Recorder osc firmware (env:m5stack-cores3-osc) broadcasts each fresh
IMU sample as one OSC message to UDP :9000 at ~100 Hz:

    /imu ,iffffff   (int32 t_ms, accel g x3, gyro dps x3)

Device axes (CoreS3): X across the display left→right, Y up the display
bottom→top, Z perpendicular out of the display — so lying display-up on a
table reads gravity on Z.

Two classes mirror the replay path in fake_imu.py:

  OscImuSource — datagram endpoint that keeps the latest sample and appends
                 every received packet to input/imu_stream.jsonl in the same
                 {t, ax..az, gx..gz} contract the sim replays with --imu, so a
                 live session is automatically a replayable clip. `t` is the
                 creature clock at receipt (the session timeline); the device's
                 own t_ms rides along as `dt` for jitter diagnosis.
  _LiveImu     — the instinct-facing Imu: getAccel()/getGyro() return the
                 latest sample and log each read to imu_reads.jsonl, exactly
                 like _CapturingImu does for replayed streams.

Also a sender for loopback tests and for replaying any clip *through the live
path* (registered as the `osc-send` script):

    osc-send data/mocap/lala/imu_hips.jsonl --host 127.0.0.1
"""
import argparse
import asyncio
import json
import os
import struct
import sys
import time

OSC_PORT = 9000


# ── OSC packet codec ─────────────────────────────────────────────────────

def _pad4(n: int) -> int:
    return (n + 4) & ~3          # length of a null-terminated, 4-aligned string


def parse_imu_packet(data: bytes):
    """Decode one /imu OSC packet → (t_ms, (ax,ay,az), (gx,gy,gz)) or None.

    Tolerant: any other address (or a malformed packet) returns None so stray
    traffic on the port can't kill the receiver.
    """
    try:
        end = data.index(b"\x00")
        if data[:end] != b"/imu":
            return None
        off = _pad4(end)
        tt_end = data.index(b"\x00", off)
        if data[off:tt_end] != b",iffffff":
            return None
        off = off + _pad4(tt_end - off)
        t_ms, ax, ay, az, gx, gy, gz = struct.unpack_from(">i6f", data, off)
        return t_ms, (ax, ay, az), (gx, gy, gz)
    except (ValueError, struct.error):
        return None


def parse_mag_packet(data: bytes):
    """Decode one /mag OSC packet → (t_ms, (mx,my,mz)) or None.
    The CoreS3 firmware sends the calibrated field vector, device frame."""
    try:
        end = data.index(b"\x00")
        if data[:end] != b"/mag":
            return None
        off = _pad4(end)
        tt_end = data.index(b"\x00", off)
        if data[off:tt_end] != b",ifff":
            return None
        off = off + _pad4(tt_end - off)
        t_ms, mx, my, mz = struct.unpack_from(">i3f", data, off)
        return t_ms, (mx, my, mz)
    except (ValueError, struct.error):
        return None


def build_imu_packet(t_ms: int, accel, gyro) -> bytes:
    return (b"/imu\x00\x00\x00\x00" + b",iffffff\x00\x00\x00\x00"
            + struct.pack(">i6f", int(t_ms) & 0x7FFFFFFF,
                          accel[0], accel[1], accel[2],
                          gyro[0], gyro[1], gyro[2]))


# ── Receiver ─────────────────────────────────────────────────────────────

class OscImuSource(asyncio.DatagramProtocol):
    """Listen for /imu packets; keep the latest sample; log the full stream."""

    def __init__(self, port: int, clock, stream_log_path: str,
                 mag_log_path: str | None = None):
        self.port = port
        self._clock = clock
        os.makedirs(os.path.dirname(stream_log_path), exist_ok=True)
        self._log = open(stream_log_path, "w")
        # /mag packets (if the firmware sends them) go to their own file —
        # imu_stream.jsonl must stay pure {t, ax..gz} so --imu replay works.
        self._mag_log = open(mag_log_path, "w") if mag_log_path else None
        # Resting defaults until the first packet: flat on a table, 1 g up.
        self.accel = (0.0, 0.0, 1.0)
        self.gyro = (0.0, 0.0, 0.0)
        self.mag = (0.0, 0.0, 0.0)     # calibrated field, device frame (uT)
        self.packets = 0
        self.mag_packets = 0
        self.last_rx_wall = None       # time.monotonic() of the last packet
        self.sender = None             # (ip, port) of the streaming device
        self._transport = None

    async def start(self):
        import socket
        # The device *broadcasts*; REUSEPORT lets the sim listen alongside any
        # other monitor (a plotter, a recorder) already on the port.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("0.0.0.0", self.port))
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: self, sock=sock)

    def datagram_received(self, data, addr):
        parsed = parse_imu_packet(data)
        if parsed is None:
            m = parse_mag_packet(data)
            if m is not None:
                t_dev, self.mag = m
                self.mag_packets += 1
                if self._mag_log is not None:
                    v = self.mag
                    self._mag_log.write(json.dumps({
                        "t": self._clock.now_ms, "mx": v[0], "my": v[1],
                        "mz": v[2], "dt": t_dev}) + "\n")
            return
        t_dev, self.accel, self.gyro = parsed
        self.packets += 1
        self.last_rx_wall = time.monotonic()
        self.sender = addr
        a, g = self.accel, self.gyro
        self._log.write(json.dumps({
            "t": self._clock.now_ms, "ax": a[0], "ay": a[1], "az": a[2],
            "gx": g[0], "gy": g[1], "gz": g[2], "dt": t_dev,
        }) + "\n")

    def age_s(self) -> float | None:
        """Seconds since the last packet, or None if none arrived yet."""
        if self.last_rx_wall is None:
            return None
        return time.monotonic() - self.last_rx_wall

    def close(self):
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        try:
            self._log.close()
        except Exception:
            pass
        if self._mag_log is not None:
            try:
                self._mag_log.close()
            except Exception:
                pass


class _LiveImu:
    """Instinct-facing Imu backed by the live OSC stream; logs every read."""

    def __init__(self, source: OscImuSource, clock, log_path: str):
        self._source = source
        self._clock = clock
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w")

    def getAccel(self):
        v = self._source.accel
        g = self._source.gyro
        self._log.write(json.dumps({
            "t": self._clock.now_ms, "ax": v[0], "ay": v[1], "az": v[2],
            "gx": g[0], "gy": g[1], "gz": g[2],
        }) + "\n")
        return v

    def getGyro(self):
        # Logged via getAccel above (same convention as _CapturingImu).
        return self._source.gyro

    def getMag(self):
        """Calibrated field vector (uT, device frame) when the firmware
        streams /mag; zeros otherwise."""
        return self._source.mag

    def close(self):
        try:
            self._log.close()
        except Exception:
            pass


# ── Sender (loopback tests / replaying a clip through the live path) ─────

def send_main():
    p = argparse.ArgumentParser(
        description="Replay an IMU clip (.jsonl with {t, ax..gz}) as the "
                    "CoreS3Recorder OSC stream — for loopback-testing "
                    "`sim-spine --osc` without the device.")
    p.add_argument("clip", help="IMU .jsonl to stream")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=OSC_PORT)
    p.add_argument("--limit", type=float, default=None, metavar="SECONDS",
                   help="Stop after this many seconds of clip time.")
    p.add_argument("--loop", action="store_true",
                   help="Restart the clip when it ends.")
    args = p.parse_args()

    samples = []
    with open(args.clip) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                samples.append((float(d["t"]), (d["ax"], d["ay"], d["az"]),
                                (d["gx"], d["gy"], d["gz"])))
    if not samples:
        raise SystemExit(f"no samples in {args.clip}")
    t0 = samples[0][0]

    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    dur = samples[-1][0] - t0
    print(f"streaming {args.clip} ({len(samples)} samples, {dur/1000:.1f}s) "
          f"→ {args.host}:{args.port}", file=sys.stderr)

    sent = 0
    while True:
        start = time.monotonic()
        for t, acc, gyr in samples:
            rel_s = (t - t0) / 1000.0
            if args.limit is not None and rel_s > args.limit:
                break
            lag = rel_s - (time.monotonic() - start)
            if lag > 0:
                time.sleep(lag)
            sock.sendto(build_imu_packet(t - t0, acc, gyr), (args.host, args.port))
            sent += 1
        if not args.loop:
            break
    print(f"sent {sent} packets", file=sys.stderr)


if __name__ == "__main__":
    send_main()
