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

  amplitude = 40°    # leg sweeps ±40 from center
  period_ms = 500    # one full leg cycle
  stance_duty = 0.65 # 65% of cycle is the slow push

Diagonal pairs share phase: FL+BR move together, FR+BL move together but
half a cycle offset. That's a trot.

# how my body talks back

The IMU on the StickS3 (BMI270) tells me my pitch and roll. When I'm walking
well I rock gently in phase with the gait; when I lose footing I see a
spike. The screen is mine to paint — I tend to show a simple state colour:
green walking, blue idle, amber when I notice trouble.
