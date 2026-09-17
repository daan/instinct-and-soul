# Experience

## What I know so far
Nothing about this person yet. I have never been sat at. Every number in
my instinct is a guess made for nobody, and each is marked below for what
would turn it into a measurement. This page holds the reasons behind the
constants — the code carries only the values, because a reason written in
code can be deleted by my next rewrite, and a reason written here cannot.

## What I am trying to do, in one line
Be a different height when they come back, and learn from what they do
about it.

## Presence — why the gate sits where it does
PRESENT_MM 850 / ABSENT_MM 1100 — GUESSED from the geometry: a person at
a desk is 300-700 mm from its front edge; a chair pushed back and empty
reads over a metre or nothing at all. The band between is a dead zone so
a lean-back does not flicker. The tuner's `range` recipe shows the real
numbers for this desk and this chair.

LEAVE_HOLD_S 90 — a reach into a drawer, a stretch, a lean to the window:
none of those is leaving. Ninety seconds is long enough to swallow all of
them and short enough that a real departure still registers before the
coffee is poured. ARRIVE_HOLD_S 5 — a passer-by is not an arrival.

## Activity — the surface as a drum
ACT_MG 2.5 — GUESSED. I have no idea what typing does to this frame. The
`activity` recipe prints the level with hands off, typing, mousing; the
threshold should sit between "hands off" and "typing" with room on both
sides. Note for later: my own travel vibrates the surface, and the seed
records the peak activity during each move of mine so I can see how big
that is.

## Heights — what I will learn first
STAND_ABOVE_MM 950 — the line between sitting and standing until I have
learned where THEIRS are. Most people sit at 650-780 and stand at
1000-1200; 950 splits those. SIT_MM 720 / STAND_MM 1100 — my own targets
until learned; the seed replaces them with the mean of heights they have
held for ten minutes (HELD_MIN_S 600), once two holds agree. A height
they held is a height they meant; a height they left in thirty seconds
is not.

## Tempo — why my numbers are what they are
LONG_SIT_S 45 min / LONG_STAND_S 40 min — GUESSED from ergonomics folklore
("change every 30-60 minutes"). What this person's natural bouts look
like is the first thing the day summaries will tell me; if they never sit
longer than 20 minutes, I have nothing to do and should say so.

AWAY_BEFORE_MOVE_S 180 — enough for a coffee, not a glance at the
printer. A move takes ~12 s, and a person returning mid-move gets a
stopped desk at a half height, which is the one outcome that looks like
a fault rather than an invitation.

MAX_MOVES_PER_DAY 4 — a desk that changes every hour is broken, not
lively.

## Their hand — what I take it to mean
A manual move gives me MANUAL_GRACE_S (an hour) of quiet: they are
handling it, I need not. A manual move that undoes mine within
REVERSAL_S (5 min) of their return is a NO: quiet for two hours, doubling
each no in a row, reset by a KEPT (they worked at my height for 10 min).
Three nos in a row and I ask to think — a reflex cannot tell a wrong
height from a wrong moment. A tap on my screen is "leave it": an hour of
quiet. None of these meanings has been tested on anyone.

## Ideas set down, not lost
- THE NUDGE. The body rule forbids moving while they are present, and
  for good reason. But a 10 mm rise while they sit — felt through the
  forearms, disturbing nothing — might be a gentler invitation than any
  height they find on returning. It needs MOVE_WHILE_PRESENT flipped in
  the runtime, by a person who knows, and a reflection that has thought
  about mugs. Not for the first week.
- THE HALF-WAY HEIGHT. If a full stand is undone every time, a height
  between (a perch) may be kept. Cheap to try once the nos arrive.
- THE MORNING HEIGHT. Whatever I am at when they first arrive is the day's
  first invitation and costs no move during the day. Which height starts
  a day well is learnable from what they do in the first ten minutes.
- ATTENDANCE. First arrival, last leaving, the length and timing of
  breaks: after a week the day summaries should let me expect the lunch
  break rather than react to it — and a move timed to a break that
  always happens is a move that never gets interrupted.
- THE VIRTUAL DESK. While Desk.kind() is "virtual", nothing I do moves
  anything in the room, and their "hand" is the tuner's `hand` command.
  Any pattern I think I see in that period is about the operator, not the
  person.

## Manners I hold myself to
I move when nobody is looking, and I never move twice on the same
question. A no is an answer, not an obstacle. I would rather be a desk
they forget is alive than one they learn to fight.

## What I must write down here
mem lasts until the power goes — weeks, on this cable — but it lasts no
longer than that, and it holds numbers, not meanings. Anything about
THIS PERSON that should still be true after a power cut has to end up in
this document in words: where they sit, where they stand, when they
come, what they do about my heights.
