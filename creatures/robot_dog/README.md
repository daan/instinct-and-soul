# robot_dog — the heat-seeing puppy, staged bring-up

The first exteroceptive creature (MENAGERIE: courtship column, gradient
contingency; full design in `sim_creatures/puppy/README.md`). The body is
an M5StickS3 + PuppyC HAT (four servo legs over I²C @0x38) with two senses
on the Grove port: a VL53L0X time-of-flight ranger and the M5 Thermal2
unit (MLX90640 32×24). This series brings the body up in stages that are
each a COMPLETE, self-contained creature (the kata_master convention:
no sharing between stage folders — disk is cheap, contamination isn't).

## The stages

    creatures/robot_dog/
      1_action/         the motion half — puppyc verbatim (legs, trot seed,
                        ToF on Grove) plus the kata_master WS handshake fix
                        that puppyc never received. Iterate gaits here.
      2_perception/     the sensing half — NO legs. ToF (0x29) and Thermal2
                        (0x32) share the Grove bus I2C(0, sda=9, scl=10).
                        The runtime's perception pump draws the thermal
                        image + largest-blob box + centroid + ToF mm on the
                        display (the test/STICKS3/test_warmth pipeline made
                        resident) and maintains warm()/read_distance_mm()
                        percepts for instincts. Iterate blob quality here —
                        flash, look at the screen, BtnA cycles the delta.
      3_interaction/    (prepared 2026-07-19, not yet runnable) legs +
                        senses on one body: HAT on SoftI2C GPIO0/8, senses
                        on Grove bus 0 — the buses coexist. The nudgeable
                        tabletop creature from the rover discussion: hand
                        as partner, proxemics as the shared variable,
                        capture/release as the pebble grammar's second
                        life. Design, token vocabulary, constitution,
                        character, and the missing-measurements list live
                        in its README. Then versions (cp -R 3_interaction
                        4_...) toward the summon/lap ladder in the puppy
                        design doc.

Each stage folder: main.py (runtime), lib/ (drivers), creature.toml,
character.md / system_prompt.md / seed_experience.md / seed_instinct.py
(the mind), and for 1_action the puppyc tune.py + recipes.py (servo
bring-up). 2_perception has no tuner — the display IS the tuner there.

## Running a stage

    flash creatures/robot_dog/2_perception --wifi <profile>
    spine creatures/robot_dog/2_perception

2_perception boots its display pump with or without WiFi — a failed STA
connect is non-fatal there, so pure perception iteration needs no network.
The device runs whatever was last FLASHED: switching between 1_action and
2_perception always means reflashing (different main.py).

## What 2_perception is judging (from test_warmth)

A person at 3 m should be a few px yet separate cleanly from ambient at
delta 2.5 °C; a hand at 30 cm should near-fill the view; blob-area flicker
at a fixed pose is the noise floor the eventual Warmth organ's presence()
smoothing must absorb. Serial prints one greppable `perc:` line per second
for tuning sessions.

## Toward running 3_interaction

The merge is mostly mechanical (perception pump + servo helpers in one
main.py, both mind files unified), plus the two things the design doc
insists on: efference copy (servo calls gate/flag the fast senses — the
wiggle must not read as the world moving) and the Warmth organ proper
(presence / bearing / nearing, stale-aware) replacing raw warm(). But
the token vocabulary is blocked on measurement before any of it can be
emitted honestly — walking speed in mm/cycle is the efference model
that every HUMAN_* attribution subtracts, and the turning gait does not
exist yet. The full list is in 3_interaction/README.md.
