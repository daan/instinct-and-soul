# kata_master — the real body, one complete creature per condition

The device series for kata-master: an M5StickS3 on the back of the hand
(X toward the wrist) with an M5 Unit-Synth (SAM2695) on the Grove port.
Detection lives ON the device (the Kata/Motion/Handling organs), the voice
is MIDI over a wire — no network in the sound path; WiFi carries only the
journal.

## Structure: every condition is a COMPLETE, self-contained creature

    creatures/kata_master/
      condition_1/            ← everything: runtime + organs + mind + tuner
        main.py                 the runtime (wifi, spine link, hot-swap)
        lib/                    synth.py, organs.py, calc.py, creature_mem.py
        organs.py -> lib/organs.py   (internal symlink: sim bench reads the
                                      root, flash reads lib/ — one file)
        seed_instinct.py        the mind: seed + prompts
        character.md, system_prompt.md, seed_experience.md, creature.toml
        tune.py, recipes.py     hardware bring-up / feel-gate tools
        logs/                   sessions (gitignored: creatures/**/logs/)

Deliberately NO sharing between conditions: a study variant is a frozen
artifact, and editing a shared organs.py for condition_2 would silently
rewrite what condition_1 *was*. Disk is cheap; contamination isn't. When
two conditions genuinely must share a file, make the symlink between them
explicitly — visible sharing over accidental coupling.

## Making a condition

    cp -R creatures/kata_master/condition_1 creatures/kata_master/condition_2
    # then edit what the study varies: organs (e.g. physics-based vs
    # social-based senses), the seed, the character — anything.

(`cp -R` on macOS copies the organs.py symlink as a symlink; since it is
internal to the condition, the copy stays self-contained.)

## Running a condition

    flash creatures/kata_master/condition_1 --wifi <profile>   # its body
    tune  creatures/kata_master/condition_1                    # bring-up
    spine creatures/kata_master/condition_1 [--max-reflections N]  # session

The sim bench replays a condition against its OWN organs:

    creature-sim creatures/kata_master/condition_1 --imu <clip>

Remember: the device runs whatever was last FLASHED — switching conditions
that differ in main.py/lib means reflashing; conditions that differ only
in seed/prompts can share a flash (the spine sends the seed per session).

## Tuner highlights (per condition: `tune creatures/kata_master/<cond>`)

    deploy swoosh|tones|<path>   feel-gate seeds, live, no spine needed
    synthcheck                   Grove 5V + TX-pin hunt (silent-synth triage)
    swooshvol / tonevol          volume sweeps with battery-sag readings
    mastervol / vbat / note / program / imulog / off

## Hardware notes

- Unit-Synth on Grove: TX = G9 (synthcheck-verified 2026-07-13); a wrong
  TX pin is a silent failure.
- Master volume default lives in main.py (`SYNTH_VOLUME`); per-channel CC7
  scales under it. 75 = room level, chosen by ear + sag sweeps.
- The runtime self-reports every boot over the spine
  (`BOOT: cause=... vbat=...`) — spontaneous PWRON resets were traced to
  bench USB power (2026-07-13); battery operation is clean.
- The calibration ladder that produced the organ constants lives in
  `sim_creatures/kata-master/` (1_swoosh, 2_tones + recorded sessions).
