"""Device registry — the creature's *body*.

A creature declares its body once, structurally, in `creature.toml`:

    device = "sticks3"

The simulator builds fake hardware (screen size, channels) from the table below
rather than parsing the prose system_prompt. The system_prompt stays the LLM's
description of the same body — both derive from the one `device` id, so they can't
drift. Real-device specs: test/CORES3/API.md, test/STICKS3/API.md.
"""
import os
import tomllib

DEFAULT_DEVICE = "sticks3"

# screen is (width, height) in pixels, matching M5.Display.width()/height().
DEVICES = {
    "sticks3": {
        "name": "M5StickS3",
        "screen": (135, 240),   # portrait color LCD
        "speaker": True,
        "display": True,
        "imu": "BMI270",
        "mag": False,
        "motor": False,
    },
    "cores3": {
        "name": "M5Stack CoreS3",
        "screen": (320, 240),
        "speaker": True,
        "display": True,
        "imu": "BMI270",
        "mag": True,
        "motor": True,
    },
}


def resolve(device_id: str) -> dict:
    """Hardware facts for a device id. Exits with the known ids if unknown."""
    if device_id not in DEVICES:
        known = ", ".join(sorted(DEVICES))
        raise SystemExit(f"unknown device {device_id!r}; known devices: {known}")
    return DEVICES[device_id]


def read_device(creature_dir: str) -> str:
    """The device id from <creature_dir>/creature.toml, or the default."""
    p = os.path.join(creature_dir, "creature.toml")
    if os.path.isfile(p):
        with open(p, "rb") as f:
            cfg = tomllib.load(f)
        return cfg.get("device", DEFAULT_DEVICE)
    return DEFAULT_DEVICE
