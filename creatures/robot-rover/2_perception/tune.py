"""
tune.py — the wall-bench tuner for robot-rover 2_perception
(M5StickS3 + M5Stack RoverC + VL53L0X ToF, M5 Thermal2 optional).

Run:
    flash creatures/robot-rover/2_perception --wifi <profile>
    tune  creatures/robot-rover/2_perception

Every argument is optional and positional. `speed` is a WHOLE NUMBER 0..100 —
it becomes a signed byte to the motors, so 1 is not "slow", it is nothing at
all; the interesting range starts somewhere around 30. Durations (`secs`,
`side_s`) are seconds and may be fractional. `raw` and `drive` take signed
values, -100..100, because direction is part of what you are asking for there.

Commands:
  joy                                — drive it yourself, from the keyboard.
                                       LATCHED: a key commands a movement and
                                       it keeps going until the next key.
                                       Layout:

                                            w            u i o
                                           a s d         j k l
                                            q e          m , .

                                       wasd translate, qe rotate; the 3x3 grid
                                       adds the four DIAGONALS, which is the
                                       move this base has and a wheeled one
                                       does not. space or k stops, 1-9 sets
                                       speed 10..90, [ ] nudge it by 5, - =
                                       do the same for rotation, h reprints
                                       the map, esc or x leaves.

                                       While you drive, the instinct is a
                                       passive watcher: every segment is
                                       scored and journalled exactly as a
                                       recipe's would be, so steering by feel
                                       and measuring are the same act.
  scan                               — who is home, on WHICH bus? Wants 0x38
                                       (rover) on the HAT bus, and says where
                                       0x29 (ToF) and 0x32 (thermal) landed —
                                       the chassis Grove ports and the stick's
                                       own Grove port are different wiring,
                                       and this settles which one you used.
                                       Run it first every session; see below.
  tof                                — stream the beam. Wave a hand: 0 is NO
                                       ECHO ("I don't know"), never "far".
  blob [period_ms]                   — both senses at rest: thermal noise
                                       floor, blob-area-vs-distance pairs.
                                       BtnA on the stick cycles the delta.
  wall [speed] [secs]                — THE BENCH: face a wall 600-1000 mm out.
                                       Forward/backward legs, each bracketed
                                       by the beam: mm travelled, mm/s this
                                       speed buys, coast after stop, veer.
  step [speed] [ms] [n]              — the SMALLEST move: n short pulses, mm
                                       each. Mean, spread, and how many bought
                                       nothing. The resolution of "careful".
  vfloor [start] [step] [secs]       — the straight-line stiction floor,
                                       measured off the wall (the measured 21
                                       was a SPIN floor; this one is its own
                                       number).
  hold [target] [band] [speed]       — keep a distance to the wall, closed
                                       loop: % in band, straight-through
                                       crossings, worst error. The rehearsal
                                       for keep-distance-from-a-human.
  face [pace] [pulse_ms] [band_px]   — turn to hold the warm shape at frame
                                       centre; logs px-per-deg and flips its
                                       own handedness map when wrong.
  motors [speed] [secs]              — ONE motor index at a time, raw. Rover on
                                       a book. This is the recipe that tells
                                       you MOTOR_CORNER and MOTOR_SIGN, and
                                       nothing else works until it has.
  raw <m0> <m1> <m2> <m3> [secs]     — four bytes straight at the hardware. No
                                       mixer, no calibration gate: test a
                                       corner map on paper before committing
                                       it, or ask whether the bus is alive.
  floor [step] [secs]                — ramp a spin until the gyro sees it. The
                                       first speed that MOVED is SPEED_FLOOR
                                       on this surface.
  spin [speed] [secs]                — cw then ccw. Equal and OPPOSITE dps is
                                       a balanced body.
  straight [speed] [secs]            — forward then backward; `turned` is VEER.
  slide [speed] [secs]               — right then left. The mecanum check:
                                       moves, does NOT turn.
  box [speed] [side_s]               — fwd/right/back/left, no rotation at all.
                                       The square only mecanum can drive.
  square [speed] [side_s]            — forward + quarter-turn x4, the turning
                                       square, for comparison with `box`.
  drive <fwd> <strafe> <spin> [secs] — the mixer itself, e.g. `drive 50 50 0`
                                       for a 45-degree diagonal, nose still.
  imulog                             — motors idle: the noise floor, and a
                                       chance to confirm yaw's sign by hand.
  vbat                               — battery under load
  off | stop                         — motors off and hold

# the rover has its own power switch, and that is a trap

The stick and the rover are two machines with two batteries. The stick will
boot from USB alone, join wifi, connect to this tuner and accept every command
you type while the rover under it is switched OFF — and nothing will move.
That failure is indistinguishable, from up here, from a wrong corner map, a
speed under the stiction floor, a flat rover battery, and a stick not pushed
all the way onto the 8-pin header. `scan` is what tells them apart: it asks the
bus who is listening and wants to hear 0x38. Nothing there means nobody is
home, and no calibration fixes that.

# the order to run them in (a bench session)

    0. scan       0x38 answers, and 0x29 answers SOMEWHERE. A sensor plugged
                  in after power-on shows up in the scan but stays unbound —
                  reboot the stick so boot can bind it.
    1. tof        wave a hand. Real mm close in, 0 when nothing echoes.
    2. blob       if the thermal is fitted: stand at a known distance, read
                  the pairs.
    3. wall       the bench proper, 600-1000 mm from a bare wall. Try 25,
                  30, 40, 60 — the mm/s-per-speed curve and the coast.
    4. vfloor     the straight-line floor. Compare with the spin floor (21).
    5. step       at the floor speed, pulses of 100-300 ms: the smallest
                  reliable move and its spread.
    6. hold       put the numbers to work: how tight a band survives contact
                  with reality. Then walk a book toward the beam.
    7. face       the turning half, if the thermal is fitted.

The stage-1 calibration recipes (motors, floor, spin, straight, slide, box,
square, drive, raw, imulog, vbat) are all still here, unchanged — calibration
carried over in lib/drive.py, so they are for re-checks and new floors, not
for first light.

# what this tuner measures now that stage 1 could not

Rotation was always MEASURED: the gyro, integrated about the found vertical,
signed, positive clockwise from above. DISTANCE is new: with the ToF looking
at a wall, every bout is bracketed in real millimetres (`mm0 -> mm1`), which
is what turns "did it move?" into "how far, how fast, and how far past the
stop did it keep going?". Off the wall — no echo at either end — the bench
recipes refuse to score rather than guess, and every straight-line report
falls back to stage 1's honesty: veer, stir, and a STALL flag that deserves
your eyes before your belief.
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe, HEARTBEAT_TIMEOUT
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "joy | scan | tof | blob [ms] | wall [speed] [secs] | step [speed] [ms] [n] | "
    "vfloor [start] [step] [secs] | hold [target] [band] [speed] | "
    "face [pace] [pulse_ms] [band_px] | motors | raw | floor | spin | straight | "
    "slide | box | square | drive <f> <s> <r> | imulog | vbat | off"
)


def clamp_speed(v):
    return max(0, min(100, int(v)))


def clamp_signed(v):
    """A mixer axis or a raw motor byte: -100..100, direction included."""
    return max(-100, min(100, int(v)))


def clamp_secs(v):
    return max(0.2, min(20.0, float(v)))


def clamp_step(v):
    return max(1, min(50, int(v)))


def clamp_ms(v):
    """A pulse length: short enough to be a step, long enough to exist."""
    return max(50, min(2000, int(v)))


def clamp_mm(v):
    """A hold target: above the bench's abort distance, inside the beam's
    honest range."""
    return max(150, min(1200, int(v)))


# ── joystick mode ──────────────────────────────────────────────────────────
#
# LATCHED, because a terminal has no key-up event: pressing `w` commands
# forward and the rover keeps going until you press something else. What makes
# that safe is the runtime's deadman — the tuner re-sends the current vector
# every KEEPALIVE_S, and the board stops the motors by itself 400 ms after the
# last one. So quitting the tuner, closing the laptop or walking out of wifi
# range all stop the rover; only letting go of the key does not.
#
# Each entry is (fwd, strafe, spin) as UNIT directions, scaled by the current
# speed at send time. + is forward, + is to the RIGHT, + is clockwise.
_D = 0.7071  # diagonals: each axis gets speed/sqrt(2), so a diagonal travels
             # at the same body speed as a cardinal move instead of 1.41x
             # faster. Without this, `speed 40` means two different things
             # depending on which key you pressed.

JOY_KEYS = {
    # the six obvious ones
    "w": (1, 0, 0, "forward"),
    "s": (-1, 0, 0, "backward"),
    "a": (0, -1, 0, "slide_left"),
    "d": (0, 1, 0, "slide_right"),
    "q": (0, 0, -1, "ccw"),
    "e": (0, 0, 1, "cw"),
    # the 3x3 grid, laid out as it sits under the hand — this is the
    # teleop_twist_keyboard convention, and it exists here for the four
    # diagonals, which are the move a mecanum base has and a wheeled one
    # does not.
    "u": (_D, -_D, 0, "diag_fwd_left"),
    "i": (1, 0, 0, "forward"),
    "o": (_D, _D, 0, "diag_fwd_right"),
    "j": (0, -1, 0, "slide_left"),
    "k": (0, 0, 0, "stop"),
    "l": (0, 1, 0, "slide_right"),
    "m": (-_D, -_D, 0, "diag_back_left"),
    ",": (-1, 0, 0, "backward"),
    ".": (-_D, _D, 0, "diag_back_right"),
}

JOY_HELP = [
    "  w              forward           u i o    diagonals forward",
    " a s d           left/back/right   j k l    slide / stop / slide",
    "  q e            rotate ccw / cw   m , .    diagonals back",
    "",
    "  space or k     stop           1-9   speed 10..90",
    "  [ ]            speed -/+ 5    - =   spin speed -/+ 5",
    "  h              this help      esc or x   leave joystick mode",
]

KEEPALIVE_S = 0.2


class RoverCTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "robot-rover 2_perception"

    def __init__(self):
        super().__init__()
        self.joy = False              # is the joystick holding the keyboard?
        self.joy_speed = 40           # translation, 0..100
        self.joy_spin = 30            # rotation, usually wants less
        self.joy_vec = (0, 0, 0)      # what the board has been told
        self.joy_label = "stop"

    def on_mount(self) -> None:
        # No super() call: Textual dispatches on_mount to every class in the
        # MRO that defines one, so the base handler already runs — calling it
        # again starts a second ws_server worker, which dies binding port
        # 8765 (EADDRINUSE) and takes the whole app down with it.
        self.set_interval(KEEPALIVE_S, self._joy_keepalive)

    # ── the wire ───────────────────────────────────────────────────────────

    def _joy_send(self, vec, label):
        """One CTL frame. Fire-and-forget: a dropped joystick packet is a
        stale packet, and the next keepalive is 200 ms away."""
        self.joy_vec = vec
        self.joy_label = label
        if self.board_ws is None:
            return
        msg = "CTL:{},{},{},{}".format(vec[0], vec[1], vec[2], label)
        self.run_worker(self.board_ws.send(msg), exclusive=False)

    def _joy_keepalive(self) -> None:
        """Tell the board we are still here. Re-sending the SAME vector only
        refreshes its deadman — it does not re-issue the command, so this
        costs no I2C traffic and does not chop the record into 5 bouts a
        second."""
        if self.joy and self.joy_vec != (0, 0, 0):
            self._joy_send(self.joy_vec, self.joy_label)

    def _joy_status(self):
        below = ""
        floor = 21   # measured 2026-08-15; `floor` re-measures it per surface
        if 0 < self.joy_speed < floor:
            below = "  [bold red]BELOW FLOOR {}[/]".format(floor)
        return "  [bold]joy[/] {} spd {} spin {}{}".format(
            self.joy_label, self.joy_speed, self.joy_spin, below)

    def update_status(self) -> None:
        # The whole line, composed here rather than appended to the base's —
        # the base runs on a 1 s interval and would otherwise wipe the
        # joystick state off the bar between keystrokes, and reading its
        # rendered markup back out to append to it loses the colours.
        if not self.joy:
            super().update_status()
            return
        try:
            status = self.query_one("#status", Static)
        except Exception:
            return
        import time as _time
        if self.board_ws is not None and \
                (_time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT:
            head = "[bold green]● connected[/]"
        elif self.board_ws is not None:
            head = "[bold yellow]● heartbeat lost[/]"
        else:
            head = "[bold red]● disconnected[/]"
        status.update("{}  {}{}".format(head, self.STATUS_LABEL,
                                        self._joy_status()))

    # ── entering and leaving ───────────────────────────────────────────────

    async def _joy_enter(self):
        self.joy = True
        # Take the instinct's hands off the wheel first: whatever recipe was
        # running may be driving, and two things writing the motors is not a
        # thing to debug at 40.
        await self.board_ws.send(format_recipe(RECIPES["joy"]))
        self._joy_send((0, 0, 0), "stop")
        self.set_focus(None)          # so keystrokes reach on_key, not the input
        self.log_msg("joystick ON — latched. keys:", style="bold cyan")
        for line in JOY_HELP:
            self.log_msg(line, style="cyan")
        self.log_msg("the board stops itself 400 ms after the tuner goes "
                     "quiet, so quitting is also a stop", style="dim")
        self.update_status()

    def _joy_exit(self):
        self._joy_send((0, 0, 0), "stop")
        self.joy = False
        try:
            self.query_one("#input", Input).focus()
        except Exception:
            pass
        self.log_msg("joystick OFF — motors stopped", style="cyan")
        self.update_status()

    def on_key(self, event) -> None:
        if not self.joy:
            super().on_key(event)
            return

        key = event.key
        # Textual names the printable ones by character, but not all of them.
        char = getattr(event, "character", None)
        k = char if (char and len(char) == 1) else key

        handled = True
        if key in ("escape", "x"):
            self._joy_exit()
        elif key == "space" or k == " ":
            self._joy_send((0, 0, 0), "stop")
        elif k in JOY_KEYS:
            fwd, strafe, spin, label = JOY_KEYS[k]
            vec = (int(round(fwd * self.joy_speed)),
                   int(round(strafe * self.joy_speed)),
                   int(round(spin * self.joy_spin)))
            self._joy_send(vec, label)
        elif k and k.isdigit() and k != "0":
            self.joy_speed = int(k) * 10
            self._joy_rescale()
        elif k == "[":
            self.joy_speed = max(0, self.joy_speed - 5)
            self._joy_rescale()
        elif k == "]":
            self.joy_speed = min(100, self.joy_speed + 5)
            self._joy_rescale()
        elif k == "-":
            self.joy_spin = max(0, self.joy_spin - 5)
            self._joy_rescale()
        elif k == "=":
            self.joy_spin = min(100, self.joy_spin + 5)
            self._joy_rescale()
        elif k == "h":
            for line in JOY_HELP:
                self.log_msg(line, style="cyan")
        else:
            handled = False

        if handled:
            self.update_status()
            event.stop()
            event.prevent_default()

    def _joy_rescale(self):
        """A speed change while latched takes effect immediately, at the
        direction you are already going — otherwise you would have to stop and
        re-press to try a slower version of the same move, which is exactly
        the experiment you are usually in the middle of."""
        if self.joy_label in ("stop", None):
            return
        entry = None
        for _k, v in JOY_KEYS.items():
            if v[3] == self.joy_label:
                entry = v
                break
        if entry is None:
            return
        fwd, strafe, spin, label = entry
        self._joy_send((int(round(fwd * self.joy_speed)),
                        int(round(strafe * self.joy_speed)),
                        int(round(spin * self.joy_spin))), label)

    def compose(self) -> ComposeResult:
        yield Static("● disconnected", id="status")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder=PLACEHOLDER, id="input")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.clear()
        self.history_index = -1
        if not line:
            return
        self.cmd_history.append(line)

        if self.board_ws is None:
            self.log_msg("no board connected", style="yellow")
            return

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd in ("joy", "joystick"):
                await self._joy_enter()
                return

            elif cmd == "scan":
                code = format_recipe(RECIPES["scan"])
                self.log_msg("scan: who is on WHICH bus? want 0x38 (rover) "
                             "plus 0x29 (ToF) / 0x32 (thermal) wherever they "
                             "are plugged — and check the rover's own power "
                             "switch", style="cyan")

            elif cmd == "tof":
                code = format_recipe(RECIPES["tof"])
                self.log_msg("tof: streaming the beam. wave a hand — 0 means "
                             "NO ECHO, never 'far away'", style="cyan")

            elif cmd == "blob":
                period = clamp_ms(parts[1]) if len(parts) > 1 else 500
                code = format_recipe(RECIPES["blob"], period_ms=period)
                self.log_msg("blob: both senses at rest every {} ms. stand "
                             "at a known distance; BtnA on the stick cycles "
                             "the delta".format(period), style="cyan")

            elif cmd == "wall":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 30
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 1.5
                code = format_recipe(RECIPES["wall"], speed=speed, secs=secs)
                self.log_msg("wall speed={} secs={} — face it at a bare wall "
                             "600-1000 mm out. fwd/back legs, each bracketed "
                             "by the beam".format(speed, secs), style="cyan")

            elif cmd == "step":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 25
                ms = clamp_ms(parts[2]) if len(parts) > 2 else 150
                n = max(1, min(20, int(parts[3]))) if len(parts) > 3 else 8
                code = format_recipe(RECIPES["step"], speed=speed, ms=ms, n=n)
                self.log_msg("step speed={} ms={} n={} — the smallest move "
                             "this body can make, measured. wants ~{} mm of "
                             "run-up".format(speed, ms, n, 130 + n * 40),
                             style="cyan")

            elif cmd == "vfloor":
                start = clamp_speed(parts[1]) if len(parts) > 1 else 10
                step = clamp_step(parts[2]) if len(parts) > 2 else 3
                secs = clamp_secs(parts[3]) if len(parts) > 3 else 1.0
                code = format_recipe(RECIPES["vfloor"], start=start, step=step,
                                     secs=secs)
                self.log_msg("vfloor start={} step={} secs={} — the STRAIGHT "
                             "line's stiction floor, off the wall (the spin "
                             "floor was 21)".format(start, step, secs),
                             style="cyan")

            elif cmd == "hold":
                target = clamp_mm(parts[1]) if len(parts) > 1 else 300
                band = max(10, min(200, int(parts[2]))) if len(parts) > 2 else 30
                speed = clamp_speed(parts[3]) if len(parts) > 3 else 25
                code = format_recipe(RECIPES["hold"], target=target, band=band,
                                     speed=speed)
                self.log_msg("hold target={} band={} speed={} — keep the "
                             "distance to the wall. then walk a book toward "
                             "the beam and watch it back away".format(
                                 target, band, speed), style="cyan")

            elif cmd == "face":
                pace = clamp_speed(parts[1]) if len(parts) > 1 else 30
                pulse_ms = clamp_ms(parts[2]) if len(parts) > 2 else 200
                band_px = max(1, min(8, int(parts[3]))) if len(parts) > 3 else 2
                code = format_recipe(RECIPES["face"], pace=pace,
                                     pulse_ms=pulse_ms, band_px=band_px)
                self.log_msg("face pace={} pulse={}ms band={}px — turn to "
                             "hold the warm shape at centre. stand in view "
                             "and move sideways".format(pace, pulse_ms,
                                                        band_px), style="cyan")

            elif cmd == "motors":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 60
                if speed and speed < 20:
                    self.log_msg(
                        "note: speed {} is almost certainly under the stiction "
                        "floor — geared motors buzz and do not turn. try 40-60 "
                        "for this one".format(speed), style="yellow")
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 1.5
                code = format_recipe(RECIPES["motors"], speed=speed, secs=secs)
                self.log_msg(
                    "motors speed={} secs={} — rover ON A BOOK. note the "
                    "corner AND the direction for each index".format(speed, secs),
                    style="cyan")

            elif cmd == "raw":
                if len(parts) < 5:
                    self.log_msg("usage: raw <m0> <m1> <m2> <m3> [secs]",
                                 style="yellow")
                    return
                m = [clamp_signed(parts[i]) for i in range(1, 5)]
                secs = clamp_secs(parts[5]) if len(parts) > 5 else 1.5
                code = format_recipe(RECIPES["raw"], m0=m[0], m1=m[1], m2=m[2],
                                     m3=m[3], secs=secs)
                self.log_msg(
                    "raw {} {} {} {} for {}s — no mixer, no calibration gate. "
                    "this drives the body".format(m[0], m[1], m[2], m[3], secs),
                    style="cyan")

            elif cmd == "floor":
                step = clamp_step(parts[1]) if len(parts) > 1 else 5
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 1.2
                code = format_recipe(RECIPES["floor"], step=step, secs=secs)
                self.log_msg(
                    "floor step={} secs={} — on the FLOOR, not on a book. "
                    "first MOVED is SPEED_FLOOR".format(step, secs), style="cyan")

            elif cmd == "spin":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 50
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 3.0
                code = format_recipe(RECIPES["spin"], speed=speed, secs=secs)
                self.log_msg(
                    "spin speed={} secs={} — cw then ccw; want equal and "
                    "OPPOSITE dps".format(speed, secs), style="cyan")

            elif cmd == "straight":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 50
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 2.0
                code = format_recipe(RECIPES["straight"], speed=speed, secs=secs)
                self.log_msg(
                    "straight speed={} secs={} — `turned` is VEER here. give "
                    "it room".format(speed, secs), style="cyan")

            elif cmd == "slide":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 60
                secs = clamp_secs(parts[2]) if len(parts) > 2 else 2.0
                code = format_recipe(RECIPES["slide"], speed=speed, secs=secs)
                self.log_msg(
                    "slide speed={} secs={} — good = travels sideways, "
                    "`turned` near 0".format(speed, secs), style="cyan")

            elif cmd == "box":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 60
                side_s = clamp_secs(parts[2]) if len(parts) > 2 else 1.5
                code = format_recipe(RECIPES["box"], speed=speed, side_s=side_s)
                self.log_msg(
                    "box speed={} side={}s — no rotation anywhere. mark the "
                    "start and see if it comes home".format(speed, side_s),
                    style="cyan")

            elif cmd == "square":
                speed = clamp_speed(parts[1]) if len(parts) > 1 else 50
                side_s = clamp_secs(parts[2]) if len(parts) > 2 else 1.5
                code = format_recipe(RECIPES["square"], speed=speed, side_s=side_s)
                self.log_msg(
                    "square speed={} side={}s — four quarter-turns should sum "
                    "near 360".format(speed, side_s), style="cyan")

            elif cmd == "drive":
                if len(parts) < 4:
                    self.log_msg("usage: drive <fwd> <strafe> <spin> [secs] "
                                 "— e.g. drive 50 50 0", style="yellow")
                    return
                fwd = clamp_signed(parts[1])
                strafe = clamp_signed(parts[2])
                spin = clamp_signed(parts[3])
                secs = clamp_secs(parts[4]) if len(parts) > 4 else 2.0
                code = format_recipe(RECIPES["drive"], fwd=fwd, strafe=strafe,
                                     spin=spin, secs=secs)
                self.log_msg(
                    "drive fwd={} strafe={} spin={} for {}s (+ is forward, "
                    "+ is RIGHT, + is clockwise)".format(fwd, strafe, spin, secs),
                    style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg(
                    "imulog: motors idle. twist the rover clockwise by hand — "
                    "yaw should go POSITIVE", style="cyan")

            elif cmd == "vbat":
                code = format_recipe(RECIPES["vbat"])
                self.log_msg("vbat: watch it sag while driving", style="cyan")

            elif cmd in ("off", "stop"):
                code = format_recipe(RECIPES["off"])
                self.log_msg("off — motors stopped", style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    RoverCTuner().run()
