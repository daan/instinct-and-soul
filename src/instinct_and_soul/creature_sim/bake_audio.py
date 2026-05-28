"""bake-audio — render captured audio_events.jsonl into a WAV file."""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf


SAMPLE_RATE = 44100   # Hz
HEADROOM = 0.3        # peak amplitude per tone (volume=255 → 0.3 of full scale)
FADE_MS = 5.0         # cosine attack/release per tone, to avoid edge clicks


def _render_tone(freq_hz: float, ms: float, volume: int) -> np.ndarray:
    n = max(1, int(SAMPLE_RATE * ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    amp = HEADROOM * (max(0, min(255, int(volume))) / 255.0)
    tone = amp * np.sin(2.0 * np.pi * float(freq_hz) * t)

    fade_n = max(1, int(SAMPLE_RATE * FADE_MS / 1000.0))
    fade_n = min(fade_n, n // 2)
    if fade_n > 0:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade_n, dtype=np.float32))
        tone[:fade_n] *= ramp
        tone[-fade_n:] *= ramp[::-1]
    return tone.astype(np.float32)


def bake(events_path: str, wav_path: str) -> dict:
    tones = []
    end_ms = 0.0
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("kind") != "tone":
                continue
            t  = float(ev["t"])
            fr = float(ev["freq"])
            ms = float(ev["ms"])
            vol = int(ev.get("volume", 128))
            tones.append((t, fr, ms, vol))
            end_ms = max(end_ms, t + ms)

    if not tones:
        # Empty WAV — 1s of silence so the file exists and is openable.
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")
        return {"tones": 0, "duration_s": 1.0, "wav": wav_path}

    n_total = int(SAMPLE_RATE * end_ms / 1000.0) + 1
    audio = np.zeros(n_total, dtype=np.float32)
    for t, fr, ms, vol in tones:
        start = int(SAMPLE_RATE * t / 1000.0)
        seg = _render_tone(fr, ms, vol)
        stop = min(start + len(seg), n_total)
        audio[start:stop] += seg[:stop - start]

    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:
        audio /= peak / 0.99

    sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")
    return {"tones": len(tones), "duration_s": end_ms / 1000.0, "wav": wav_path}


def main():
    p = argparse.ArgumentParser(description="Render audio_events.jsonl into a WAV.")
    p.add_argument("events_path", help="Path to audio_events.jsonl.")
    p.add_argument("-o", "--output", default=None,
                   help="Output WAV path. Defaults to audio.wav next to the events file.")
    args = p.parse_args()

    if args.output is None:
        out = os.path.join(os.path.dirname(args.events_path) or ".", "audio.wav")
    else:
        out = args.output

    summary = bake(args.events_path, out)
    print(f"baked {summary['tones']} tones over {summary['duration_s']:.2f}s → {summary['wav']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
