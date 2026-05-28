"""creature_sim — run instinct.py in CPython with fake M5 hardware.

Designed for M5-style creatures (M5StickS3, M5CoreS3). Feeds IMU data from
an .npz, captures Speaker / Display calls to JSONL, and lets a separate
bake-audio step turn the captured audio events into a WAV.
"""
from .clock import Clock

__all__ = ["Clock"]
