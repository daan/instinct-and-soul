"""
tune.py — interactive tuner for the kata_master creature.

This body senses with the IMU and speaks through the Grove SAM2695 GM synth.
The tuner's first job on real hardware: find the VOICE (the pan-flute gust,
the six pose tones — the SAM's ROM patches differ from FluidR3, so everything
tuned in the sim gets re-auditioned here) and find the VOLUME the battery can
afford — every sound recipe reports battery-voltage sag while playing.

Run:
    tune creatures/kata_master/condition_1

Recording, for tuning offline (nothing crosses the radio during a take):
    record [label] [secs]           arm the recorder. BtnA on the board takes
                                    one: three count-in ticks, then a CLICK +
                                    white screen FLASH that is t=0 in the file
                                    (sync your video on either), the take, then
                                    two clicks to close it. Saved to flash as
                                    rec_NNN.bin; press BtnA again for the next.
                                    Label each take for what it IS — `record
                                    still 20`, `record katas 20`, `record
                                    noise 30` — the label rides in the header.
                                    RAM bounds a take; the board reports how
                                    many seconds it can hold when you arm it.
    then, over USB:
      uv run creatures/kata_master/condition_1/pull_recordings.py
                                    copies every take off, converts to .jsonl
                                    the sim/replay tools already read, and
                                    reports whether the sampling was clean

Deploy (no spine session needed):
    deploy kata                     the condition_1 kata seed, live
    deploy <path>                   any seed file

The feel gate — hand-tuning what a kata IS:
    feel [knob=value ...]           the rest-tone gate: rest and hold, and
                                    the face you are resting on sounds.
                                    KataSense is the mechanism; every number
                                    it judges by is a knob here. Knobs PERSIST
                                    across commands, so you move one, listen,
                                    move the next. Each deploy echoes the full
                                    knob line, and the board reports the
                                    speed01 distribution the thresholds sit in
                                    — set them against that, not against a
                                    guess. What you settle on gets typed into
                                    seed_instinct.py's SENSE dict.
    feel show                       the current knob line
    feel reset                      back to the seed's numbers
      the ladder     quiet spent rearm launch        (on speed01, 0..1)
      the arc        dwell land_hold refract max_flight linger   (seconds)
      full scale     rot_fs acc_fs      (SCALES the ladder — move first)
      smoothing      speed_tau grav_tau act_tau      (seconds)
      this gate      cone hold gap report vol
    e.g.  feel quiet=0.15 dwell=0.25   rest sooner, on a quieter hand

Live bench (run `stetho` in a second terminal for the dashboard):
    stetho [ip] | stetho off        arm/detach the organ stream (UDP-OSC
                                    :9001) without killing the running
                                    deploy — an overlay, not a replacement

Volume / energy:
    swooshvol                       one gust at CC7 25/50/75/100/127 + vbat sag
    tonevol                         six tones at CC7 25/50/75/100/127 + vbat sag
    swoosh [vol] [reps]             gusts at one volume (default 90, 3x)
    tones [vol]                     the six pose tones at one volume
    mastervol [v]                   GM master volume (SysEx, scales everything)
    vbat                            live battery voltage/level/charging

Voice:
    note [ch] [note] [ms] [vel]     play one note (default ch0 C4 500ms vel90)
    program [ch] [prog]             set GM instrument, play a test note
    off                             all notes off (silence the synth)

IMU:
    imulog                          live accel/gyro means (which axis is which)
"""

from textual.app import ComposeResult
from textual.widgets import Input, RichLog, Static

from instinct_and_soul.harness import TuneAppBase, format_recipe
from recipes import RECIPES, INSTINCT_IDLE


PLACEHOLDER = (
    "record [label] [secs] | feel [knob=v ...] | feel show|reset "
    "| deploy kata|<path> "
    "| stetho [ip|off] | synthcheck "
    "| swooshvol | tonevol | swoosh [vol] [reps] | tones [vol] "
    "| mastervol [v] | vbat | note [ch] [n] [ms] [vel] "
    "| program [ch] [prog] | imulog | off"
)

# Seeds the tuner can deploy directly, no spine session needed.
#
# A sim seed is NOT deployable here. It reads the sim's organ layer
# (Kata/Motion/Handling, attached by organs.py); this runtime has no organ
# layer — sensing lives with the instinct — so the board crashes the instant
# the seed leaves its hello notes: `CRASH:name 'Kata' isn't defined`. The
# sim series stays canonical for the OFFLINE bench only.
DEPLOY_SHORTCUTS = {
    "kata": "creatures/kata_master/condition_1/seed_instinct.py",
}

# `deploy <name>` for a gate that is now a live-knob command, not a file.
DEPLOY_MOVED = {
    "tones": "the rest-tone gate is `feel` now — every KataSense number is "
             "a knob on the line. try `feel` or `feel show`",
    "swoosh": "the gust gate is still sim-only (needs Motion.fluency, which "
              "KataSense has no equivalent for) — no board port yet",
}

# ── The knobs: what a kata IS, on the tuner line ────────────────────────────
#
# KataSense holds the mechanism and deliberately holds NO numbers of its own
# (lib/kata_sense.py) — every threshold, dwell and timescale is a constructor
# argument. That is precisely the surface a tuner exists to turn, so it lives
# here: name -> (default, lo, hi). Defaults are seed_instinct.py's SENSE dict
# plus the gate's own three; what you settle on gets typed back into the seed.
#
#   quiet/spent/rearm/launch  the ladder, on speed01 (the louder of rotation
#                             and raw shove, each over its full scale)
#   dwell/land_hold/refract/max_flight/linger    the times that turn crossings
#                             into a still -> swift -> still ARC
#   rot_fs/acc_fs             what counts as full speed: these SCALE the whole
#                             ladder — move them before the thresholds, never
#                             after, or every threshold has to be redone
#   speed_tau/grav_tau/act_tau   smoothing: reaction lag vs jitter
#   cone/hold/gap             this gate's own judgment (pose truth, patience)
KNOBS = {
    "quiet": (0.20, 0.01, 1.0),
    "spent": (0.30, 0.01, 1.0),
    "rearm": (0.55, 0.01, 1.0),
    "launch": (0.75, 0.01, 1.0),
    "dwell": (0.35, 0.0, 3.0),
    "land_hold": (0.22, 0.0, 2.0),
    "refract": (0.20, 0.0, 2.0),
    "max_flight": (1.2, 0.1, 10.0),
    "linger": (0.25, 0.0, 2.0),
    "rot_fs": (600.0, 50.0, 4000.0),
    "acc_fs": (25.0, 1.0, 200.0),
    "speed_tau": (0.04, 0.001, 1.0),
    "grav_tau": (0.12, 0.001, 2.0),
    "act_tau": (2.0, 0.05, 30.0),
    "cone": (25.0, 1.0, 90.0),
    "hold": (0.30, 0.0, 3.0),
    "gap": (0.5, 0.0, 5.0),
    "report": (10.0, 2.0, 120.0),
    "vol": (100, 1, 127),
}


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class KataMasterTuner(TuneAppBase):
    INITIAL_INSTINCT = INSTINCT_IDLE
    STATUS_LABEL = "kata_master"

    def __init__(self):
        super().__init__()
        # The most recent deploy/recipe: overlay commands (stetho) prepend
        # their few lines to it, so arming the stethoscope doesn't kill the
        # seed you're watching.
        self._stream_code = INSTINCT_IDLE
        # The knobs PERSIST across commands — that is what makes this hand
        # tuning rather than re-typing: `feel quiet=0.15`, listen, `feel
        # dwell=0.25`, listen, one number at a time, everything else held.
        self.knobs = {k: v[0] for k, v in KNOBS.items()}

    def knob_line(self):
        """Every knob, changed ones starred. Long on purpose: this line is
        the record of what you were hearing when you heard it."""
        out = []
        for name, (default, _lo, _hi) in KNOBS.items():
            v = self.knobs[name]
            out.append("{}{}={:g}".format("*" if v != default else "", name, v))
        return " ".join(out)

    def set_knobs(self, tokens):
        """Apply `name=value` tokens, ALL of them or none: a typo in the
        third knob must not leave the first two live on the board without
        you knowing which state you are listening to. Returns True if
        applied."""
        staged = {}
        for tok in tokens:
            name, sep, raw = tok.partition("=")
            name = name.lower()
            if not sep:
                self.log_msg("knobs are name=value — got {!r}".format(tok),
                             style="yellow")
                return False
            if name not in KNOBS:
                self.log_msg("no knob {!r}. knobs: {}".format(
                    name, " ".join(KNOBS)), style="yellow")
                return False
            try:
                v = float(raw)
            except ValueError:
                self.log_msg("{}: not a number: {!r}".format(name, raw),
                             style="yellow")
                return False
            default, lo, hi = KNOBS[name]
            cl = max(lo, min(hi, v))
            if cl != v:
                self.log_msg("{} clamped to [{:g}, {:g}]".format(name, lo, hi),
                             style="yellow")
            staged[name] = int(cl) if isinstance(default, int) else cl
        self.knobs.update(staged)
        return True

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

        def arg(i, lo, hi, default):
            return clamp(parts[i], lo, hi) if len(parts) > i else default

        # overlay commands run a few lines, then fall through into the
        # last deploy so the seed keeps running
        overlay = cmd in ("stetho",)

        try:
            if cmd == "deploy":
                if len(parts) < 2:
                    self.log_msg("deploy what? kata | <path to seed>", style="yellow")
                    return
                if parts[1] in DEPLOY_MOVED:
                    self.log_msg(DEPLOY_MOVED[parts[1]], style="yellow")
                    return
                path = DEPLOY_SHORTCUTS.get(parts[1], parts[1])
                try:
                    with open(path) as f:
                        code = f.read()
                    compile(code, path, "exec")
                except OSError:
                    self.log_msg("no such seed: {}".format(path), style="yellow")
                    return
                except SyntaxError as e:
                    self.log_msg("seed has a syntax error: {}".format(e), style="yellow")
                    return
                self.log_msg("deploying {} ({} bytes)".format(path, len(code)), style="cyan")

            elif cmd == "stetho":
                if len(parts) > 1 and parts[1].lower() == "off":
                    code = ("import stethoscope\n"
                            "stethoscope.detach()\n"
                            "send('stethoscope off')\n") + self._stream_code
                    self.log_msg("stethoscope off", style="cyan")
                else:
                    ip = None
                    if len(parts) > 1 and parts[1].lower() != "on":
                        ip = parts[1]
                    else:
                        try:
                            ip = self.board_ws.local_address[0]
                        except Exception:
                            pass
                    if not ip or ip == "0.0.0.0":
                        self.log_msg("can't detect my ip — use: stetho <ip>", style="yellow")
                        return
                    code = ("import stethoscope\n"
                            "stethoscope.attach(\"{ip}\", 9001)\n"
                            "send('stethoscope -> {ip}:9001')\n").format(ip=ip) \
                           + self._stream_code
                    self.log_msg("organ stream -> {}:9001 — run `stetho` in "
                                 "another terminal".format(ip), style="cyan")

            elif cmd == "record":
                label = "take"
                secs = 30.0
                for tok in parts[1:]:
                    try:
                        secs = max(1.0, min(600.0, float(tok)))
                    except ValueError:
                        # a label, not a duration. It is written into the
                        # file header and into generated source, so it is
                        # kept to characters that can be neither.
                        label = "".join(c for c in tok
                                        if c.isalnum() or c in "_-")[:15]
                        if not label:
                            self.log_msg("label must have letters or digits",
                                         style="yellow")
                            return
                code = format_recipe(RECIPES["record"], label=label,
                                     secs=secs, hz=200)
                self.log_msg("recorder armed — label '{}', {:.0f}s takes at "
                             "200 Hz. BtnA on the board starts a take; three "
                             "ticks count you in, then CLICK+FLASH is t=0. "
                             "Pull them with: uv run creatures/kata_master/"
                             "condition_1/pull_recordings.py".format(
                                 label, secs), style="cyan")

            elif cmd == "feel":
                rest = parts[1:]
                if rest and rest[0].lower() in ("show", "?"):
                    self.log_msg(self.knob_line(), style="cyan")
                    return
                if rest and rest[0].lower() == "reset":
                    self.knobs = {k: v[0] for k, v in KNOBS.items()}
                    rest = rest[1:]
                if not self.set_knobs(rest):
                    return          # a bad knob changes NOTHING and deploys
                code = format_recipe(RECIPES["feel"], **self.knobs)
                self.log_msg("feel: " + self.knob_line(), style="cyan")

            elif cmd == "synthcheck":
                code = format_recipe(RECIPES["synthcheck"])
                self.log_msg("probing Grove 5V + candidate TX pins — listen", style="cyan")

            elif cmd == "off":
                code = format_recipe(RECIPES["off"])
                self.log_msg("synth silenced", style="cyan")

            elif cmd == "vbat":
                code = format_recipe(RECIPES["vbat"])
                self.log_msg("live battery stream", style="cyan")

            elif cmd == "imulog":
                code = format_recipe(RECIPES["imulog"])
                self.log_msg("live IMU stream", style="cyan")

            elif cmd == "swoosh":
                vol = arg(1, 1, 127, 90)
                reps = arg(2, 1, 20, 3)
                code = format_recipe(RECIPES["swoosh"], vol=vol, reps=reps)
                self.log_msg("swoosh vol={} x{}".format(vol, reps), style="cyan")

            elif cmd == "tones":
                vol = arg(1, 1, 127, 90)
                code = format_recipe(RECIPES["tones"], vol=vol)
                self.log_msg("six pose tones at vol={}".format(vol), style="cyan")

            elif cmd == "swooshvol":
                code = format_recipe(RECIPES["swooshvol"])
                self.log_msg("gust volume sweep 25..127 + vbat sag", style="cyan")

            elif cmd == "tonevol":
                code = format_recipe(RECIPES["tonevol"])
                self.log_msg("tone volume sweep 25..127 + vbat sag", style="cyan")

            elif cmd == "mastervol":
                v = arg(1, 0, 127, 100)
                code = format_recipe(RECIPES["mastervol"], v=v)
                self.log_msg("master volume -> {}".format(v), style="cyan")

            elif cmd == "note":
                ch = arg(1, 0, 15, 0)
                note = arg(2, 0, 127, 60)
                ms = arg(3, 10, 8000, 500)
                vel = arg(4, 1, 127, 90)
                code = format_recipe(RECIPES["note"], ch=ch, note=note, ms=ms, vel=vel)
                self.log_msg("note ch={} n={} {}ms vel={}".format(ch, note, ms, vel), style="cyan")

            elif cmd == "program":
                ch = arg(1, 0, 15, 0)
                prog = arg(2, 0, 127, 75)
                code = format_recipe(RECIPES["program"], ch=ch, prog=prog)
                self.log_msg("program ch={} -> GM {}".format(ch, prog), style="cyan")

            else:
                self.log_msg("unknown command: {}".format(cmd), style="yellow")
                return

        except Exception as e:
            self.log_msg("error: {}".format(e), style="yellow")
            return

        if not overlay:
            self._stream_code = code
        await self.board_ws.send(code)


if __name__ == "__main__":
    KataMasterTuner().run()
