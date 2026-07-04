# lala_ears / 6_motion_organ

Arm 6: **Motion becomes an organ** — fusion state that no rewrite can reset.

The 5_flow runs proved the need twice over. Run 1: every hot-swap restarted
Madgwick from identity mid-dance, where it cannot converge; the gravity
residual pinned Flow's dominant axis and reversal detection went blind for
most of the run (147 reversals live vs 668 offline over the same reads) — and
the soul, seeing rev=0 through an honest report, rationally patched around
its own concussed sense without knowing the damage was self-inflicted. The
Mem quaternion warm-start fixed it (655/668, zero dead windows in run 2), but
it remains a seed idiom the soul must preserve. This arm makes it structural.

Deltas from `5_flow`:

1. **organs.py — the Motion sense.** `Imu` is transparently wrapped; every
   accel/gyro read the instinct makes feeds a session-lifetime Madgwick+Flow
   at module level. Orientation boots from the FIRST accel sample (tilt from
   gravity, verified against converged ground truth), so there is no
   cold-start rest assumption and no reset, ever. Exposed as a read-only
   sense: `Motion.up() / accel_world() / velocity() / reversal()`.
2. **seed_instinct.py** — no more `pose`/`flow` locals or `pose_q` Mem idiom;
   the seed consumes `Motion.*`. Musical mapping unchanged from 5_flow
   (turnaround-triggered lead, vertical-flow pitch contour, `rev=` report).
3. **system_prompt.md** — Motion documented as a sense beside Imu/Ear
   (including its honest limits: fed by your own reads, yaw drifts, velocity
   is short-horizon). Subtraction: `Calc.Madgwick` and `Calc.Flow` leave this
   creature's vocabulary — the body owns that fusion now.

On the real device, the equivalent lives in `main.py` (ideally a background
100 Hz sampling task, so the sense stays warm even if the instinct stops
reading) — this is the arm that carries directly to the midi_dancer.

Note on validation: the earlier Madgwick-vs-BVH ground-truth comparison was
run uninterrupted, which is why the reset failure mode stayed invisible; the
instrument was validated in steady state, not across its lifecycle. With the
organ, "uninterrupted" is structural, so the old validation applies again.

Questions: does behavior match 5_flow run 2 with the idiom now unforgettable?
Does the soul use the freed attention elsewhere? Does anything abuse the
always-on sense (e.g. reversal() read from two places, starving one)?
