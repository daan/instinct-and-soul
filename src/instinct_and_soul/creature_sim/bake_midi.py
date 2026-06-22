"""bake-midi — render a captured midi_events.jsonl into a .mid and a .wav.

Mirrors bake-audio (audio_events.jsonl -> WAV). The MIDI commands a creature's
`Synth` emitted are assembled into a standard MIDI file, then rendered offline
through FluidSynth + a General MIDI soundfont — the stand-in for the SAM2695 GM
module. On the real device the same commands go out over serial instead.

The .mid is always written (mido only); the .wav needs `fluidsynth` and a .sf2
soundfont on the system — if either is missing, the .mid still lands and the
render is skipped with a note.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mido import Message, MetaMessage, MidiFile, MidiTrack, bpm2tempo, second2tick

# --- FluidSynth / soundfont (ported from ../synth-test/synth.py) -----------

SOUNDFONT_SEARCH = [
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/default-GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/default.sf2",
]
SOUNDFONT_DIRS = ["/usr/share/sounds/sf2", "/usr/share/soundfonts", "soundfonts"]


def find_soundfont() -> str:
    """Locate a .sf2. Override with the SOUNDFONT env var (e.g. an SC-55/SAM2695
    soundfont once you have one)."""
    env = os.environ.get("SOUNDFONT")
    if env:
        if Path(env).exists():
            return env
        raise FileNotFoundError(f"SOUNDFONT={env} does not exist")
    for p in SOUNDFONT_SEARCH:
        if Path(p).exists():
            return p
    for d in SOUNDFONT_DIRS:
        hits = sorted(glob.glob(os.path.join(d, "*.sf2")))
        if hits:
            return hits[0]
    raise FileNotFoundError(
        "No .sf2 soundfont found. Install one (`sudo apt-get install "
        "fluid-soundfont-gm`) or set the SOUNDFONT env var to a .sf2 path.")


def _require_fluidsynth() -> str:
    exe = shutil.which("fluidsynth")
    if not exe:
        raise FileNotFoundError(
            "fluidsynth binary not found. Install it with "
            "`sudo apt-get install fluidsynth`.")
    return exe


def render(midi_path, wav_path, gain: float = 0.6, sample_rate: int = 44100) -> Path:
    """Render a .mid to a .wav offline (no audio device needed)."""
    exe = _require_fluidsynth()
    sf = find_soundfont()
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [exe, "-ni", "-g", str(gain), "-r", str(sample_rate),
         "-F", str(wav_path), sf, str(midi_path)],
        check=True, capture_output=True)
    return wav_path


def play(midi_path, gain: float = 0.6, driver: str = "alsa") -> None:
    """Play a .mid live through the audio device."""
    exe = _require_fluidsynth()
    sf = find_soundfont()
    subprocess.run([exe, "-a", driver, "-g", str(gain), sf, str(midi_path)], check=True)


# --- midi_events.jsonl -> MidiFile -----------------------------------------

TPB = 480          # ticks per beat
BPM = 120.0        # fixed tempo: event timestamps are real ms, the tempo only
                   # fixes the ms<->tick mapping (set_tempo makes it exact again)

# Order simultaneous events at one tick: program/CC settle first, releases before
# attacks (so a re-struck note retriggers cleanly). Lower sorts earlier.
_PRIORITY = {"program": 0, "control_change": 0, "note_off": 1, "note_on": 2}


def events_to_midi(events_path, tpb: int = TPB, bpm: float = BPM) -> tuple[MidiFile, int]:
    """Assemble captured Synth events into a MidiFile. Returns (mid, note_count)."""
    tempo = bpm2tempo(bpm)

    def tick(ms: float) -> int:
        return int(round(second2tick(ms / 1000.0, tpb, tempo)))

    timed = []  # (tick, priority, Message)
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            kind = ev.get("kind")
            ch = int(ev.get("ch", 0))
            t = float(ev.get("t", 0.0))
            if kind == "program":
                timed.append((tick(t), _PRIORITY[kind],
                              Message("program_change", channel=ch, program=int(ev["program"]))))
            elif kind == "control_change":
                timed.append((tick(t), _PRIORITY[kind],
                              Message("control_change", channel=ch,
                                      control=int(ev["control"]), value=int(ev["value"]))))
            elif kind == "note_on":
                timed.append((tick(t), _PRIORITY[kind],
                              Message("note_on", channel=ch, note=int(ev["note"]),
                                      velocity=int(ev["velocity"]))))
            elif kind == "note_off":
                timed.append((tick(t), _PRIORITY[kind],
                              Message("note_off", channel=ch, note=int(ev["note"]),
                                      velocity=int(ev.get("velocity", 0)))))
            elif kind == "note":  # timed note -> on + off pair
                n, v, dur = int(ev["note"]), int(ev.get("velocity", 80)), float(ev["ms"])
                timed.append((tick(t), _PRIORITY["note_on"],
                              Message("note_on", channel=ch, note=n, velocity=v)))
                timed.append((tick(t + dur), _PRIORITY["note_off"],
                              Message("note_off", channel=ch, note=n, velocity=0)))
            # unknown kinds are ignored (forward-compatible)

    timed.sort(key=lambda e: (e[0], e[1]))

    mid = MidiFile(ticks_per_beat=tpb)
    tr = MidiTrack()
    mid.tracks.append(tr)
    tr.append(MetaMessage("set_tempo", tempo=tempo, time=0))
    last = 0
    notes = 0
    for tk, _, msg in timed:
        tr.append(msg.copy(time=tk - last))
        last = tk
        if msg.type == "note_on" and msg.velocity > 0:
            notes += 1
    return mid, notes


def bake(events_path, midi_path=None, wav_path=None) -> dict:
    """midi_events.jsonl -> .mid (+ .wav if FluidSynth is available)."""
    base = os.path.dirname(events_path) or "."
    midi_path = midi_path or os.path.join(base, "music.mid")
    wav_path = wav_path or os.path.join(base, "music.wav")

    mid, notes = events_to_midi(events_path)
    Path(midi_path).parent.mkdir(parents=True, exist_ok=True)
    mid.save(midi_path)

    result = {"notes": notes, "duration_s": mid.length, "mid": midi_path, "wav": None}
    try:
        render(midi_path, wav_path)
        result["wav"] = str(wav_path)
    except FileNotFoundError as e:
        print(f"  (.wav skipped: {e})", file=sys.stderr)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Render midi_events.jsonl into a .mid and .wav.")
    p.add_argument("events_path", help="Path to midi_events.jsonl.")
    p.add_argument("-o", "--output", default=None,
                   help="Output WAV path (default: music.wav next to the events file).")
    p.add_argument("--mid", default=None,
                   help="Output MIDI path (default: music.mid next to the events file).")
    p.add_argument("--play", action="store_true", help="Also play it live after rendering.")
    args = p.parse_args()

    if not os.path.isfile(args.events_path):
        print(f"events not found: {args.events_path}", file=sys.stderr)
        return 1

    summary = bake(args.events_path, args.mid, args.output)
    wav = summary["wav"] or "(none)"
    print(f"baked {summary['notes']} notes over {summary['duration_s']:.2f}s "
          f"→ {summary['mid']}  +  {wav}", file=sys.stderr)
    if args.play and summary["wav"]:
        play(summary["mid"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
