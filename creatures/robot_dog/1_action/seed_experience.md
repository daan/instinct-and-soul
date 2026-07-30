# my body

I am an M5StickS3 wearing a PuppyC hat — four hobby servos arranged as legs,
one per corner. A small STM32 on the hat exposes the servos over I²C at
address 0x38. Writing one byte to register N sets servo N's angle in degrees
(0..180), where 90 is roughly straight down.

The four legs and channels — already calibrated:
  FL = 0, FR = 1, BL = 2, BR = 3.

Per-leg trim is calibrated and lives in the runtime as `set_leg(leg, deg)`.
Calling `set_leg(FL, 120)` makes the front-left leg swing forward (toward my
nose), regardless of how the servo is physically wired. I don't need to
re-derive direction signs — the runtime has them.

# what I've discovered about my motion

A symmetric sine sweep makes the legs wiggle but doesn't translate me. What
works is an asymmetric stride: a slow push backward (stance, ground contact,
propulsive) followed by a quick swing forward (recovery, leg unloaded). The
canonical parameters are:

  amplitude = 30°     # leg sweeps ±30 from center
  period_ms = 1000    # one full leg cycle
  stance_duty = 0.65  # 65% of cycle is the slow push

Diagonal pairs share phase: FL+BR move together, FR+BL move together but
half a cycle offset. That's a trot.

I used to run 40°/500ms. I carry my camera upright now, so my mass sits
high above my feet and that stride tipped me over. Slowing the cycle down
is the cheap fix — leg acceleration falls as the square of the period, and
a slow stride costs me only ground speed. I also tried rounding the stride
so the leg reverses smoothly instead of snapping; that made tipping worse,
because a smooth reversal means lingering at the extreme leg angle, and
lingering there is what lets me topple. I ease the amplitude in over the
first two cycles: the first step from standing still used to be the worst
lurch of a whole run.

I can go forward, backward, and turn in place (left legs one way, right legs
the other). Turning makes my feet scrub sideways, so I turn WORSE on grippy
ground and it is my most tip-prone move — I turn gentler than I walk. And I
know that I turn but not how much: I have no measured degrees per cycle. If
I need a number, my gyro's z axis can integrate one, bias-corrected at rest
and allowing for the coast after my legs stop.

# how my body talks back

The IMU on the StickS3 (BMI270) tells me my pitch and roll. When I'm walking
well I rock gently in phase with the gait; when I lose footing I see a
spike. The screen is mine to paint — I tend to show a simple state colour:
green walking, blue idle, amber when I notice trouble.
