## install the software


```
git clone git@github.com:daan/instinct-and-soul.git
cd instinct-and-soul
uv sync
source .venv/bin/activate
```

## connection to LLM

For running the "spine" add your anthropic api key:

```
export ANTHROPIC_API_KEY=<your key>
```


## creatures

Each creature lives under `creatures/<name>/` and contains:

```
main.py            # MicroPython runtime that runs on the body
system_prompt.md   # hardware truth, used as Claude's system prompt
character.md       # one-line desire, e.g. "You like being touched."
seed_soul.md       # initial personality
seed_instinct.py   # initial instinct code, deployed on first connect
logs/              # per-session subfolders, written by the spine
```

Run the spine pointed at a creature:

```
spine creatures/touchy-pebble
spine creatures/touchy-pebble --resume   # continue last session
```

To tune a creature (no llm required):

```
tune creatures/cores3
```

To flash `main.py` onto a USB-attached board:

```
flash creatures/cores3                          # auto-detects /dev/cu.usbmodem*
flash creatures/cores3 --port /dev/cu.usbmodem3101
```

To make a new variant, copy a creature folder and edit `character.md` / `seed_soul.md`.

## prepare the xiao (creatures/touchy-pebble)

Relevant documentation on [seeed studio](https://wiki.seeedstudio.com/xiao_esp32c3_with_micropython/) and [micropython](https://micropython.org/download/ESP32_GENERIC_C3/). Download the firmware from micropython.

According to the instructions on micropython.org:
```
esptool.py erase_flash
esptool.py --baud 460800 write_flash 0 ESP32_BOARD_NAME-DATE-VERSION.bin
```

Upload the runtime as `main.py` (MicroPython runs `main.py` automatically after boot):
```
mpremote connect /dev/<your device> cp creatures/touchy-pebble/main.py :main.py
mpremote connect /dev/<your device> reset
```

Update the WiFi/spine config section near the top of `creatures/touchy-pebble/main.py` first.

## prepare the stackm5 STACKS3 (creatures/sticks3) or the CORES3

Flash the M5Stack UIFlow MicroPython firmware using the [M5Burner](https://docs.m5stack.com/en/uiflow/m5burner/intro). Edit "boot.py" to directly run main.py. Instructions are in boot.py comments and use [Thonny](https://thonny.org/) for convienience.

UIFlow runs `boot.py` then `main.py`, so we just upload `main.py`:

```
ls /dev/tty.usbmodem*                       # find the port
mpremote connect /dev/<your device> cp creatures/sticks3/main.py :main.py
mpremote connect /dev/<your device> reset
```

## network settings

You need to connect both to the LLM and to the device. I tested the creatures on a local wifi network and assigned a static ip to my laptop.

Edit the `MODE` / `AP_*` / `STA_*` block at the top of `creatures/sticks3/main.py` before uploading.

Useful one-offs:
```
mpremote connect /dev/<your device> repl    # live REPL, Ctrl-] to exit
mpremote connect /dev/<your device> ls      # list files on device
```

### recovering a hung device

If `main.py` hangs (e.g. in a blocking WiFi/AP call) and `mpremote` reports `could not enter raw repl`, force a hard reset:

1. Hold the power button (on the side near the USB-C plug) for ~6 seconds to power off.
2. Short press the same button to power back on.
3. Re-run `mpremote connect /dev/<your device> ls` immediately.
