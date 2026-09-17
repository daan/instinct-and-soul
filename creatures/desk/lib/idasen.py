"""
idasen.py — a Linak DPG desk (IKEA Idasen and kin) over BLE, and a virtual
desk with the same face for the bench.

Two classes, one interface. The runtime builds ONE of them at boot — the BLE
desk when DESK_MAC is set in main.py, the virtual one otherwise — and hands
the instinct a read-mostly facade over it (`Desk` in main.py). Instinct code
never sees this module.

    height_mm()   float, the surface above the floor. None until the first
                  reading has landed (BLE) — never a guess.
    speed_mms()   signed mm/s from the desk's own report; 0.0 at rest.
    moving()      speed != 0, or a commanded move not yet settled.
    commanded()   True while a move_to() of OURS is in progress. This is the
                  one bit that lets a reader tell OUR motion from THEIR hand:
                  height changing with commanded() False is the paddle.
    target_mm()   where the current commanded move is going, or None.
    connected()   the BLE link is up (the virtual desk is always connected).
    age_ms()      how stale height_mm() is.
    kind()        "ble" | "virtual"
    move_to(mm)   clamp to [MIN_MM, MAX_MM], begin travelling. Returns False
                  when not connected. Non-blocking: the task drives it.
    stop()        halt now. Also the desk's own paddle halts a commanded
                  move — the DPG stops on a paddle press — and the task then
                  reports the move as interrupted.

THE PROTOCOL (Linak DPG1C, as reverse-engineered by idasen-controller /
linak-dpg-bt; UNVERIFIED on this hardware as of 2026-09-17 — the first bench
session with a real desk is where these constants get confirmed):

    service          99fa0001-338a-1024-8a49-009c0215f78a
    control  (write) 99fa0002-...   b"\\x47\\x00" up, b"\\x46\\x00" down,
                                    b"\\xff\\x00" stop, b"\\xfe\\x00" wake
    height (notify)  99fa0021-...   <Hh: height in 0.1 mm above MIN_MM,
                                    speed in 0.01 mm/s (sign = direction)
    ref. input (wr)  99fa0031-...   <H target height, same units. The desk
                                    travels toward it but STOPS if the
                                    value is not refreshed every few
                                    hundred ms — the refresh IS the deadman.

Travel is ~30-40 mm/s, so sit→stand (~400 mm) takes 10-15 s. The desk has
its own collision detection (it reverses a little on hitting something) but
that is a last resort, not a plan: the runtime's own rule about not moving
under a present person is in main.py.
"""

import struct
import time
import uasyncio as asyncio

MIN_MM = 620.0      # Idasen floor-to-surface at the bottom stop
MAX_MM = 1270.0     # ...and at the top stop
DONE_MM = 4.0       # within this of the target counts as arrived
MOVE_TIMEOUT_S = 40.0   # a full-travel move takes ~20 s; more is a fault
REFRESH_MS = 200    # the reference-input deadman refresh
SETTLE_MS = 1500    # speed must read 0 this long before a move is "settled"

_SVC = "99fa0001-338a-1024-8a49-009c0215f78a"
_CTRL = "99fa0002-338a-1024-8a49-009c0215f78a"
_HEIGHT = "99fa0021-338a-1024-8a49-009c0215f78a"
_REFIN = "99fa0031-338a-1024-8a49-009c0215f78a"

CMD_UP = b"\x47\x00"
CMD_DOWN = b"\x46\x00"
CMD_STOP = b"\xff\x00"
CMD_WAKE = b"\xfe\x00"


def clamp(mm):
    return max(MIN_MM, min(MAX_MM, float(mm)))


class _Base:
    """State + the reading side, shared by both desks. Subclasses own the
    task that moves the numbers."""

    def __init__(self):
        self._h = None          # mm, None until known
        self._v = 0.0           # mm/s, signed
        self._t = 0             # ticks_ms of the last height update
        self._target = None     # mm while a commanded move is open
        self._cmd_t = 0         # ticks_ms the command was issued
        self._connected = False
        # Outcome of the last commanded move, for the runtime to journal:
        # ("arrived"|"interrupted"|"timeout"|"lost", from_mm, at_mm, s)
        self.last_result = None
        self._log = print

    # ── reading ──────────────────────────────────────────────────────────
    def height_mm(self):
        return self._h

    def speed_mms(self):
        return self._v

    def moving(self):
        return abs(self._v) > 0.5 or self._target is not None

    def commanded(self):
        return self._target is not None

    def target_mm(self):
        return self._target

    def connected(self):
        return self._connected

    def age_ms(self):
        return time.ticks_diff(time.ticks_ms(), self._t)

    # ── acting ───────────────────────────────────────────────────────────
    def move_to(self, mm):
        if not self._connected:
            return False
        self._target = clamp(mm)
        self._cmd_t = time.ticks_ms()
        self._from = self._h
        return True

    def stop(self):
        self._finish("interrupted")

    def _finish(self, how):
        if self._target is None:
            return
        elapsed = time.ticks_diff(time.ticks_ms(), self._cmd_t) / 1000.0
        self.last_result = (how, self._from, self._h, elapsed)
        self._target = None


class VirtualDesk(_Base):
    """A desk made of arithmetic: travels at SPEED toward a commanded
    target, and toward a HAND target when someone 'presses the paddle'
    (the tuner's `hand` command, delivered as a DESK:<mm> message). Lets
    the whole mind run with no desk in the room."""

    SPEED = 32.0            # mm/s, about what a DPG does

    def __init__(self, start_mm=720.0):
        super().__init__()
        self._h = float(start_mm)
        self._t = time.ticks_ms()
        self._connected = True
        self._hand = None       # where the (pretend) paddle is taking it

    def kind(self):
        return "virtual"

    def hand(self, mm):
        """Someone moved the pretend desk by hand. A hand ALWAYS wins: a
        commanded move in progress is interrupted, exactly as the real
        paddle interrupts the DPG."""
        if self._target is not None:
            self._finish("interrupted")
        self._hand = clamp(mm)

    async def task(self):
        last = time.ticks_ms()
        while True:
            await asyncio.sleep_ms(50)
            now = time.ticks_ms()
            dt = time.ticks_diff(now, last) / 1000.0
            last = now
            goal = self._hand if self._hand is not None else self._target
            if goal is None:
                self._v = 0.0
            else:
                d = goal - self._h
                step = self.SPEED * dt
                if abs(d) <= step:
                    self._h = goal
                    self._v = 0.0
                    if self._hand is not None:
                        self._hand = None
                    else:
                        self._finish("arrived")
                else:
                    self._h += step if d > 0 else -step
                    self._v = self.SPEED if d > 0 else -self.SPEED
            self._t = now


class BleDesk(_Base):
    """The real thing. One task: find the desk by MAC, connect, subscribe to
    height, and drive commanded moves by refreshing the reference input.
    Reconnects forever; while disconnected height_mm() keeps the last value
    and connected() says so."""

    def __init__(self, mac):
        super().__init__()
        self._mac = bytes(int(b, 16) for b in mac.split(":"))
        self._conn = None
        self._ctrl = None
        self._refin = None

    def kind(self):
        return "ble"

    def _decode(self, data):
        if len(data) < 4:
            return
        raw_h, raw_v = struct.unpack("<Hh", data[:4])
        self._h = MIN_MM + raw_h / 10.0
        self._v = raw_v / 100.0
        self._t = time.ticks_ms()

    async def _write(self, ch, data):
        try:
            await ch.write(data, response=False)
            return True
        except Exception as e:
            self._log("desk: write failed:", e)
            return False

    async def task(self):
        import aioble
        import bluetooth
        svc_uuid = bluetooth.UUID(_SVC)
        while True:
            self._connected = False
            try:
                self._log("desk: scanning for", self._mac)
                dev = None
                async with aioble.scan(duration_ms=8000, interval_us=30000,
                                       window_us=30000, active=True) as scanner:
                    async for r in scanner:
                        if bytes(r.device.addr) == self._mac:
                            dev = r.device
                            break
                if dev is None:
                    await asyncio.sleep(5)
                    continue
                self._log("desk: connecting")
                conn = await dev.connect(timeout_ms=10000)
                try:
                    svc = await conn.service(svc_uuid)
                    self._ctrl = await svc.characteristic(bluetooth.UUID(_CTRL))
                    height = await svc.characteristic(bluetooth.UUID(_HEIGHT))
                    self._refin = await svc.characteristic(bluetooth.UUID(_REFIN))
                    self._decode(await height.read())
                    await height.subscribe(notify=True)
                    self._connected = True
                    self._log("desk: connected, height {:.0f} mm".format(self._h))
                    last_refresh = 0
                    moving_since = None
                    still_since = None
                    while True:
                        # The deadman: a commanded move lives only while the
                        # reference input is refreshed.
                        if self._target is not None:
                            now = time.ticks_ms()
                            if time.ticks_diff(now, self._cmd_t) > MOVE_TIMEOUT_S * 1000:
                                await self._write(self._ctrl, CMD_STOP)
                                self._finish("timeout")
                            elif self._h is not None and abs(self._h - self._target) <= DONE_MM:
                                await self._write(self._ctrl, CMD_STOP)
                                self._finish("arrived")
                            elif time.ticks_diff(now, last_refresh) >= REFRESH_MS:
                                last_refresh = now
                                if moving_since is None:
                                    await self._write(self._ctrl, CMD_WAKE)
                                    moving_since = now
                                raw = int((self._target - MIN_MM) * 10)
                                await self._write(self._refin, struct.pack("<H", raw))
                            # The paddle stops the DPG: speed reads 0 for a
                            # while mid-move, short of the target → interrupted.
                            if moving_since is not None and \
                                    time.ticks_diff(now, moving_since) > 2000:
                                if abs(self._v) < 0.5:
                                    if still_since is None:
                                        still_since = now
                                    elif time.ticks_diff(now, still_since) > SETTLE_MS:
                                        self._finish("interrupted")
                                else:
                                    still_since = None
                        else:
                            moving_since = None
                            still_since = None
                        try:
                            data = await height.notified(timeout_ms=REFRESH_MS)
                            self._decode(data)
                        except asyncio.TimeoutError:
                            pass
                finally:
                    self._connected = False
                    if self._target is not None:
                        self._finish("lost")
                    try:
                        await conn.disconnect()
                    except Exception:
                        pass
                    self._log("desk: disconnected")
            except Exception as e:
                self._log("desk: error:", e)
                await asyncio.sleep(5)
