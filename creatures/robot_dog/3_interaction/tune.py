"""
tune.py — gait and behaviour tuner for robot_dog 3_interaction
(M5StickS3 + PuppyC hat + thermal camera + ToF).

Run:
    tune creatures/robot_dog/3_interaction

The gait commands drive the legs directly through set_leg/set_all, exactly as
in 1_action. The BEHAVIOUR commands (perc / find / face / hand / keep) go through the Legs
organ and the Thermal / ToF organs instead — the same surface a creature
writes against — so what you tune here is what the creature will inherit.

Commands:
  center                              — all legs to 90
  stand | sit | rest                  — preset poses
  pose <fl> <fr> <bl> <br>            — set every leg
  wiggle <leg> [amp]                  — sine-wiggle one leg (leg 0..3)
  calibrate [amp]                     — sweep each leg forward and back.
                                        `amp` = degrees forward of trimmed
                                        centre, one leg at a time. A travel
                                        and trim check, not a gait.
  trot [amp] [period_ms] [duty%]      — diagonal trot
  walk [amp] [period_ms] [duty%]      — four-phase walk
  pronk [amp] [period_ms] [duty%]     — all four legs in phase
  turn <cw|ccw> [amp] [ms]            — turn in place until `stop`. The third
                                        member of the trot/back family, and the
                                        primitive this body actually has: it
                                        turns; how much is not yet measurable.
  rotate <cw|ccw> [s] [amp] [ms]      — turn for N SECONDS, then centre
  turnto <cw|ccw> [deg] [amp] [ms]    — turn N DEGREES and stop (closed loop on
                                        gyro-z; `rotate180` is the old name).
                                        Ramps in over one cycle, tapers over
                                        the last min(20, deg/2) so it arrives
                                        instead of slamming, then keeps
                                        integrating for 600 ms and reports the
                                        coast and the error. Relative yaw only
                                        — chained turns drift.
  stop                                — centre the legs and hold

  # behaviours (blob + ToF, closed loop). All of them move-then-look: a
  # reading taken mid-stride is not news about the world.
  perc [period_ms]                    — both senses on one line, AT REST, no
                                        motion. The instrument for the
                                        unmeasured zone thresholds and the
                                        blob-area-vs-distance curve.
  find [max_mm] [pace%] [deg] [cw|ccw]
                                      — sweep in place until a warm shape is
                                        both visible AND within max_mm
                                        (default 500). Turns in short phrases
                                        and looks between them; integrates
                                        gyro-z so it gives up after deg
                                        instead of spinning forever.
  face [band_px] [pace%] [cw|ccw]     — TURNS ONLY, no translation: rotate in
                                        place to hold the shape within band_px
                                        of frame centre. The bearing half of
                                        `keep` on its own, so a bearing failure
                                        is visible separately from a range
                                        failure. Works out its own camera
                                        handedness (turns, checks whether the
                                        error shrank, flips and says so if it
                                        grew) and reports px-per-degree from
                                        the pixels removed vs the gyro yaw —
                                        which is the camera's angular scale AND
                                        deg/cycle, neither measured before.
  hand [target_mm] [band] [pace%]     — fore/aft only, on the NOSE BEAM: back
                                        off when the hand comes closer than
                                        target (default 100mm), follow when it
                                        goes away, hold in between. ToF-only on
                                        purpose — at hand distance the warm
                                        shape saturates the frame, so its
                                        centroid cannot say "which way" and a
                                        facing step would just spin. The camera
                                        is used only to tell "nothing there"
                                        from "pressed against my nose" when the
                                        beam returns no echo.
  keep [target_mm] [band] [pace%]     — hold a distance from the warm shape:
                                        face it, close if beyond target+band,
                                        open if inside target-band. Every
                                        phrase logs cycles beside range
                                        before/after — those pairs are the
                                        mm/cycle measurement.
  smooth [on|off]                     — gait waveform. OFF (default): the
                                        triangle wave. ON: cosine stance and
                                        swing, zero velocity at the reversals.
                                        The soft start applies to both.
  wave [leg]                          — one-paw hello
  imulog                              — stream IMU values

# gentleness on a TALL body — measured 2026-07-30

This chassis carries the camera upright, so it is a meaningfully tall
inverted pendulum, and that decides which lever works.

PERIOD is the lever. Peak leg speed scales as 1/period and peak
acceleration as 1/period^2, with NO cost in stance geometry. Amplitude is
the second lever: it sets the angle the leg dwells at while loaded, which
is what actually produces a tipping moment.

Waveform is NOT a lever here, and the cosine is a trap. Zero velocity at a
reversal is the same thing as dwelling at the extreme leg angle: measured
over a cycle at the 20 ms tick, the cosine sits beyond 80% of amplitude for
46% of the cycle versus the triangle's 23%. For a CoM 90-120 mm above the
feet the pendulum time constant tau = sqrt(h/g) is 95-110 ms, so 2*tau is
~200 ms — and at period 500 the cosine's dwell is ~230 ms, long enough for
the mass to actually go over, while the triangle's ~115 ms is not. Smoothing
the reversal and minimising extreme-dwell are in direct tension; you cannot
get both from the waveform.

Peak values over one cycle at the 20 ms command tick, duty 65:

    amp 40  500ms  triangle     457 deg/s   26374 deg/s^2   dwell 23%
    amp 40  500ms  cosine       714 deg/s   12008 deg/s^2   dwell 46%
    amp 30  700ms  cosine       382 deg/s    4745 deg/s^2   dwell 42%
    amp 30 1000ms  triangle     171 deg/s    6593 deg/s^2   dwell 22%
    amp 25 1000ms  triangle     143 deg/s    5495 deg/s^2   dwell 22%

The last two dominate the cosine rows on speed AND dwell at comparable
acceleration — which is why the default went back to the triangle.

Above all this is mechanical: the tip threshold is tan(theta) =
half_track / h, so lowering the camera or widening the foot stance buys
more than any gait tuning. At half_track 50 mm, going from h 120 to 60 mm
moves the threshold from 23 deg (0.42 g lateral) to 40 deg (0.83 g).
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "stop | center | stand | sit | rest | pose <fl> <fr> <bl> <br> | "
    "wiggle <leg> [amp] | calibrate [amp] | trot [amp] [ms] [duty%] | "
    "back [amp] [ms] [duty%] | rotate <cw|ccw> [s] [amp] [ms] | "
    "turn <cw|ccw> [amp] [ms] | turnto <cw|ccw> [degrees] [amp] [ms] | "
    "circle <cw|ccw> [amp] [ms] | "
    "perc [ms] | find [max_mm] [pace] [deg] [cw|ccw] | "
    "face [band_px] [pace] [cw|ccw] | "
    "hand [target_mm] [band] [pace] | keep [target_mm] [band] [pace] | "
    "smooth [on|off] | "
    "walk [amp] [ms] [duty%] | pronk [amp] [ms] [duty%] | wave [leg] | "
    "tone [freq] [ms] | toflog | theremin [min_mm] [max_mm] | imulog | miclog | "
    "autotrim | trimdump"
)


def turn_sign(word):
    """Map the word a human types to the SIGN the gait recipes expect.

    Determined empirically on the hardware, 2026-07-30: SIGN=+1 drives the LEFT
    legs propulsively forward and the RIGHT legs backward, which tank-steers the
    body to its right — i.e. CLOCKWISE seen from above. The code originally
    labelled that +1 as "ccw", so every turn command was mirrored: asking for cw
    turned ccw and vice versa.

    Keep this the ONLY place the word becomes a sign. If the physical convention
    ever needs flipping again (a rewired hat, a mirrored leg), flip it here and
    every turn command follows.
    """
    return -1 if str(word).lower() == "ccw" else 1


def clamp_angle(v):
    return max(0, min(180, int(v)))


def clamp_amp(v):
    return max(0, min(60, int(v)))


def clamp_leg(v):
    return max(0, min(3, int(v)))


def clamp_period(v):
    return max(100, min(3000, int(v)))


def clamp_duty(v):
    return max(10, min(90, int(v)))


class PuppyCTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "3_interaction"

    # Session default for every gait recipe. OFF (triangle) — see the note in
    # the module docstring: zero velocity at a reversal necessarily means
    # DWELLING at the extreme leg angle, and with the camera upright this body
    # is a tall enough inverted pendulum that the dwell tips it. The cosine is
    # kept for comparison, but period is the gentleness lever on this rig.
    smooth = 0

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
            if cmd == "center":
                code = format_recipe(RECIPES["center"])
                self.log_msg("center", style="cyan")

            elif cmd == "stand":
                code = format_recipe(RECIPES["stand"])
                self.log_msg("stand", style="cyan")

            elif cmd == "sit":
                code = format_recipe(RECIPES["sit"])
                self.log_msg("sit", style="cyan")

            elif cmd == "rest":
                code = format_recipe(RECIPES["rest"])
                self.log_msg("rest", style="cyan")

            elif cmd == "pose":
                if len(parts) < 5:
                    self.log_msg("usage: pose <fl> <fr> <bl> <br>", style="yellow")
                    return
                fl, fr, bl, br = (clamp_angle(parts[i]) for i in range(1, 5))
                code = format_recipe(RECIPES["pose"], fl=fl, fr=fr, bl=bl, br=br)
                self.log_msg("pose fl={} fr={} bl={} br={}".format(fl, fr, bl, br), style="cyan")

            elif cmd == "wiggle":
                leg = clamp_leg(parts[1]) if len(parts) > 1 else 0
                amp = clamp_amp(parts[2]) if len(parts) > 2 else 30
                code = format_recipe(RECIPES["wiggle"], leg=leg, amp=amp)
                self.log_msg("wiggle leg={} amp={}".format(leg, amp), style="cyan")

            elif cmd == "calibrate":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 40
                code = format_recipe(RECIPES["calibrate"], amp=amp)
                self.log_msg("calibrate amp={}".format(amp), style="cyan")

            elif cmd == "trot":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 30
                period = clamp_period(parts[2]) if len(parts) > 2 else 1000
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 65
                code = format_recipe(RECIPES["trot"], amp=amp, period=period,
                                     duty=duty, smooth=self.smooth)
                self.log_msg("trot amp={} period={}ms duty={}% smooth={}".format(
                    amp, period, duty, self.smooth), style="cyan")

            elif cmd == "walk":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 35
                period = clamp_period(parts[2]) if len(parts) > 2 else 800
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 75
                code = format_recipe(RECIPES["walk"], amp=amp, period=period,
                                     duty=duty, smooth=self.smooth)
                self.log_msg("walk amp={} period={}ms duty={}% smooth={}".format(
                    amp, period, duty, self.smooth), style="cyan")

            elif cmd == "pronk":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 35
                period = clamp_period(parts[2]) if len(parts) > 2 else 450
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 60
                code = format_recipe(RECIPES["pronk"], amp=amp, period=period,
                                     duty=duty, smooth=self.smooth)
                self.log_msg("pronk amp={} period={}ms duty={}% smooth={}".format(
                    amp, period, duty, self.smooth), style="cyan")

            elif cmd == "wave":
                leg = clamp_leg(parts[1]) if len(parts) > 1 else 0
                code = format_recipe(RECIPES["wave"], leg=leg)
                self.log_msg("wave leg={}".format(leg), style="cyan")

            elif cmd == "tone":
                freq = max(50, min(8000, int(parts[1]))) if len(parts) > 1 else 440
                ms = max(50, min(5000, int(parts[2]))) if len(parts) > 2 else 500
                code = format_recipe(RECIPES["tone"], freq=freq, ms=ms)
                self.log_msg("tone {}Hz {}ms".format(freq, ms), style="cyan")

            elif cmd == "toflog":
                code = format_recipe(RECIPES["toflog"])
                self.log_msg("toflog: streaming distance", style="cyan")

            elif cmd == "theremin":
                min_mm = max(10, min(2000, int(parts[1]))) if len(parts) > 1 else 30
                max_mm = max(min_mm + 10, min(2000, int(parts[2]))) if len(parts) > 2 else 600
                code = format_recipe(RECIPES["theremin"], min_mm=min_mm, max_mm=max_mm)
                self.log_msg("theremin {}..{} mm".format(min_mm, max_mm), style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("imulog: streaming IMU", style="cyan")

            elif cmd == "autotrim":
                code = format_recipe(RECIPES["autotrim"])
                self.log_msg("autotrim: per-leg touch-point search (~40s)", style="cyan")

            elif cmd == "trimdump":
                code = format_recipe(RECIPES["trimdump"])
                self.log_msg("trimdump: show TRIM and stand-time servo angles", style="cyan")

            elif cmd == "miclog":
                rate = max(8000, min(48000, int(parts[1]))) if len(parts) > 1 else 16000
                window_ms = max(10, min(500, int(parts[2]))) if len(parts) > 2 else 50
                code = format_recipe(RECIPES["miclog"], rate=rate, window_ms=window_ms)
                self.log_msg("miclog rate={}Hz window={}ms".format(rate, window_ms), style="cyan")

            elif cmd == "stop":
                code = format_recipe(RECIPES["stop"])
                self.log_msg("stop", style="cyan")

            elif cmd == "back":
                amp = clamp_amp(parts[1]) if len(parts) > 1 else 30
                period = clamp_period(parts[2]) if len(parts) > 2 else 1000
                duty = clamp_duty(parts[3]) if len(parts) > 3 else 65
                code = format_recipe(RECIPES["back"], amp=amp, period=period,
                                     duty=duty, smooth=self.smooth)
                self.log_msg("back amp={} period={}ms duty={}% smooth={}".format(
                    amp, period, duty, self.smooth), style="cyan")

            elif cmd == "rotate":
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: rotate <cw|ccw> [seconds] [amp] [ms]",
                                 style="yellow")
                    return
                sign = turn_sign(parts[1])
                seconds = max(1, min(30, int(parts[2]))) if len(parts) > 2 else 4
                # amp/period used to be hardcoded at the trot's 40/500, so the
                # single most violent move on this body was also the only one
                # you could not soften from here. Gentler defaults, tunable.
                amp = clamp_amp(parts[3]) if len(parts) > 3 else 30
                period = clamp_period(parts[4]) if len(parts) > 4 else 1000
                code = format_recipe(RECIPES["rotate"], sign=sign, seconds=seconds,
                                     amp=amp, period=period, duty=65,
                                     smooth=self.smooth)
                self.log_msg("rotate {} for {}s amp={} period={}ms smooth={}".format(
                    parts[1].lower(), seconds, amp, period, self.smooth), style="cyan")

            elif cmd == "circle":
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: circle <cw|ccw> [amp] [ms]", style="yellow")
                    return
                sign = 1 if parts[1].lower() == "cw" else -1
                amp = clamp_amp(parts[2]) if len(parts) > 2 else 25
                period = clamp_period(parts[3]) if len(parts) > 3 else 2000
                code = format_recipe(RECIPES["circle"], sign=sign, amp=amp, period=period)
                self.log_msg("circle {} amp={} period={}ms".format(parts[1].lower(), amp, period), style="cyan")

            elif cmd == "turn":
                # The third member of the trot/back family: continuous, runs
                # until `stop`. This is the primitive the body actually has —
                # it turns; how much is not yet measurable.
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: turn <cw|ccw> [amp] [ms]", style="yellow")
                    return
                sign = turn_sign(parts[1])
                amp = clamp_amp(parts[2]) if len(parts) > 2 else 30
                period = clamp_period(parts[3]) if len(parts) > 3 else 1000
                code = format_recipe(RECIPES["turn"], sign=sign, amp=amp,
                                     period=period, duty=65, smooth=self.smooth)
                self.log_msg("turn {} amp={} period={}ms smooth={} — `stop` to end".format(
                    parts[1].lower(), amp, period, self.smooth), style="cyan")

            elif cmd in ("rotate180", "turnto"):
                # Closed loop on an angle. Kept for when you need a repeatable
                # heading change; `rotate180` is the old name.
                if len(parts) < 2 or parts[1].lower() not in ("cw", "ccw"):
                    self.log_msg("usage: turnto <cw|ccw> [degrees] [amp] [ms]",
                                 style="yellow")
                    return
                sign = turn_sign(parts[1])
                target_deg = max(10, min(720, int(parts[2]))) if len(parts) > 2 else 180
                amp = clamp_amp(parts[3]) if len(parts) > 3 else 30
                period = clamp_period(parts[4]) if len(parts) > 4 else 1000
                # Scale the safety net to the job. A fixed 12 s was tuned for a
                # fast 180; at the gentle defaults a big turn needs longer,
                # while a 20 deg turn should give up quickly if it cannot move.
                timeout_s = max(8, target_deg // 8)
                code = format_recipe(RECIPES["rotate180"], sign=sign, target_deg=target_deg,
                                     amp=amp, period=period, duty=65,
                                     timeout_s=timeout_s, smooth=self.smooth)
                # This is the honest test of a gentled turn: it integrates
                # gyro-z and reports either the yaw it reached or TIMEOUT, so
                # "does it still actually turn on the mat" is measured, not felt.
                self.log_msg("turnto {} target={}° amp={} period={}ms smooth={} timeout={}s".format(
                    parts[1].lower(), target_deg, amp, period, self.smooth,
                    timeout_s), style="cyan")

            elif cmd == "perc":
                period = max(100, min(5000, int(parts[1]))) if len(parts) > 1 else 500
                code = format_recipe(RECIPES["perc"], period_ms=period)
                self.log_msg("perc: blob + tof at rest every {}ms — no motion"
                             .format(period), style="cyan")

            elif cmd == "find":
                max_mm = max(50, min(2000, int(parts[1]))) if len(parts) > 1 else 500
                pace = max(35, min(100, int(parts[2]))) if len(parts) > 2 else 60
                sweep = max(30, min(1080, int(parts[3]))) if len(parts) > 3 else 360
                direction = 1
                if len(parts) > 4 and parts[4].lower() in ("cw", "ccw"):
                    direction = 1 if parts[4].lower() == "ccw" else -1
                # find/face hand a WORD to Legs.turn(), and the organ owns that
                # word's meaning — so no sign flip here; see turn_sign() and
                # the organ's own note.
                code = format_recipe(RECIPES["find"], max_mm=max_mm, pace=pace,
                                     sweep_deg=sweep, dir=direction)
                self.log_msg("find: sweep {} for a warm shape within {}mm "
                             "(pace {}%, give up after {}°)".format(
                                 "ccw" if direction > 0 else "cw", max_mm,
                                 pace, sweep), style="cyan")

            elif cmd == "face":
                band = max(1, min(16, int(parts[1]))) if len(parts) > 1 else 3
                pace = max(35, min(100, int(parts[2]))) if len(parts) > 2 else 60
                direction = 1
                if len(parts) > 3 and parts[3].lower() in ("cw", "ccw"):
                    direction = 1 if parts[3].lower() == "ccw" else -1
                code = format_recipe(RECIPES["face"], band_px=band, pace=pace,
                                     dir=direction)
                self.log_msg("face: hold the shape within +/-{}px of centre, "
                             "pace {}% — turns only, and works out its own "
                             "camera handedness".format(band, pace), style="cyan")

            elif cmd == "hand":
                target = max(40, min(1500, int(parts[1]))) if len(parts) > 1 else 100
                band = max(5, min(400, int(parts[2]))) if len(parts) > 2 else 20
                pace = max(35, min(100, int(parts[3]))) if len(parts) > 3 else 60
                code = format_recipe(RECIPES["hand"], target_mm=target,
                                     band_mm=band, pace=pace)
                self.log_msg("hand: follow/retreat to hold {}mm +/-{}mm at pace "
                             "{}% (nose beam only)".format(target, band, pace),
                             style="cyan")

            elif cmd == "keep":
                target = max(60, min(1500, int(parts[1]))) if len(parts) > 1 else 350
                band = max(10, min(400, int(parts[2]))) if len(parts) > 2 else 60
                pace = max(35, min(100, int(parts[3]))) if len(parts) > 3 else 70
                code = format_recipe(RECIPES["keep"], target_mm=target,
                                     band_mm=band, pace=pace)
                self.log_msg("keep: hold {}mm +/-{}mm at pace {}% — every phrase "
                             "logs an mm/cycle pair".format(target, band, pace),
                             style="cyan")

            elif cmd == "smooth":
                # A session-level knob, not a per-command argument: you want to
                # A/B the waveform with everything else held fixed.
                if len(parts) > 1 and parts[1].lower() in ("off", "0", "hard"):
                    PuppyCTuner.smooth = 0
                elif len(parts) > 1 and parts[1].lower() in ("on", "1"):
                    PuppyCTuner.smooth = 1
                else:
                    PuppyCTuner.smooth = 0 if self.smooth else 1
                self.log_msg(
                    "smooth {} — {}".format(
                        "ON" if self.smooth else "OFF",
                        "cosine stance/swing, soft start" if self.smooth
                        else "original triangle wave (hard reversals)"),
                    style="cyan")
                return

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        await self.board_ws.send(code)


if __name__ == "__main__":
    PuppyCTuner().run()
