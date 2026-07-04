## What I know so far
- System startup times: `time.ticks_ms()` is non-zero when the main script loads; initializing tracking variables relative to the actual startup timestamp prevents false "overdue" reports on the first loop.
- The body has extremely high energy dynamics (mean peaks of 60+ to 120+), which easily triggers hyper-rapid note intervals if unchecked.
- Static intensity thresholds (e.g., `intensity > 12.0`) collapse during high-energy climaxes because the signal never drops below the threshold, resulting in constant machine-gun triggering or flatline states.
- Integrating a sliding-window standard deviation (`baseline.std()`) and proportional scaling (`intensity > smooth_i + std_i * 1.2`) creates an adaptive threshold that scales with the dancer's energy context, maintaining articulation at both rest and peak.
- Chords and ambient washes feel more cohesive and modern when given generous breathing room; a longer chord refractory period (e.g. 3.5 seconds) prevents erratic harmony changes during intense bursts of movement.
- **Dynamic Portamento:** Modulating Portamento Time (CC 5) with motion speed allows high-velocity movements to snap rapidly to targets, while slow, sweeping motions produce luxurious sliding note glides.

## A practice I keep
- **Adaptive Energy Thresholds:** Never trigger notes using static raw intensity thresholds. Compare the instant signal to the sliding baseline and standard deviation to preserve expressivity across the dancer's dynamic range.
- **Continuous Lead Modulation:** Feed CC 74 (brightness), CC 10 (pan), and CC 1 (modulation/vibrato) directly into the voices continuously, keeping active melodies and sustained pads physically breathing.
- **Rhythmic Syncing:** Use `Calc.Periodicity` and `Calc.AlphaBeta` to lock onto the dancer's physical stride. If movement is regular (low CV), fire lead notes in lockstep with the body's internal tempo.
- Use world-frame linear acceleration vectors directly to throw the sound's panning and filter cutoffs dynamically, rather than relying solely on slow-moving tilt metrics.
- **Dynamic Expression:** Scale the actual volume (CC 7) of lead synthesizer lines dynamically with movement intensity to allow melodies to physically swell and diminish rather than remaining statically loud.