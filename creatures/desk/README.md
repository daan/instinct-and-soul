# desk — a sit-stand desk with a will of its own

An M5Stack CoreS3 on the surface of a Linak (IKEA Idasen) sit-stand desk.
Character (set 2026-09-17): *a desk that loves to move, and loves it best
when its moving gives its person a day with a rhythm in it — sitting,
standing, sitting again.* It cannot make anyone stand. It can only be a
different height when they come back, and notice what they do about it.
The perch idea from MENAGERIE.md turned into furniture: awareness by
indirection, never a nag, at the timescale of days and weeks.

## The body

    Imu      the BMI270, read by the INSTINCT: surface vibration is what
             typing and mousing look like from here (tilt condition_4's
             pattern — the sense lives in the seed, retunable by a push)
    Range    M5 Unit Ultrasonic I2C (RCWL-9620 @0x57) on Grove Port A,
             pointed at where the person's body is. Rides on the desk, so
             the geometry is the same sitting or standing. Owned by a pump
             (the 120 ms trigger→read wait); the instinct reads mm()
    Desk     the Linak DPG over BLE (lib/idasen.py) — or a VIRTUAL desk of
             the same shape until DESK_MAC is set in main.py. height_mm(),
             moving(), commanded(), move_to(), stop(), result()
    Touch    the screen, latched by the runtime — the explicit channel
             (the CoreS3 has no physical BtnA)

**Their hand is not a separate sensor.** The desk reports its height
whether we moved it or they did; `Desk.commanded()` is the bit that tells
the two apart. Height changing with `commanded()` False is the paddle —
the person speaking. A paddle press also stops a move of ours (the frame
does that itself) and `result()` then reads `interrupted`.

**The body rule** (`MOVE_WHILE_PRESENT = False`, main.py): `move_to()` is
refused while Range reads someone within `SAFE_MM` (1 m), and a move in
progress is stopped the moment someone appears; both are journalled. A
desk rising into a lap is the one thing this creature must not be able
to do by accident. It is one policy line, flippable for the nudge
experiments the experience file sketches — knowingly.

## The mind

The seed (`seed_instinct.py`) writes what happened and does the one thing
a reflex can: it moves the desk to the *other* height while the person is
away, and watches what they do about it when they return.

    09:02 arrived — 14h away | desk 72cm (sitting) | range 61cm
    09:52 left — sat 50m at 72cm | active 41m of it
    09:55 moving the desk 72cm → 110cm — they sat 50m and have been
          away 3m (invite standing; move 1 of 4 today)
    09:56 I raised the desk 72cm → 110cm (arrived, 12s; my sense felt
          6.2mg of it)
    10:04 back after 12m — desk at 110cm (I put it there; was 72cm)
    10:14 they kept my height — standing at 110cm for 10m
    11:31 they moved the desk 110cm → 73cm while here, after standing 87m
    11:00 hour: present 52m (sit 0m, stand 52m), active 44m | desk 110cm
    22:00 day 2026-09-17 closed: present 7h10m over 6 visit(s), first
          09:02, last left 18:41 | sat 4h50m (longest 89m), stood 2h20m
          (longest 87m), active 5h30m | my moves 3: kept 2, undone 1, cut
          short 0 | their moves 4, stood up on their own 1 | taps 0 |
          heights learned: sit 72cm (5 holds), stand 110cm (3 holds)
    REFLECTION: day closed (day 3 of my life here) ...

Every move of ours is an invitation with an outcome — **kept** (they
worked at it for 10 min), **undone** (they moved it back within 5 min of
returning: a no, which buys quiet, doubling with each no in a row), or
**cut short**. Three nos in a row summon a reflection; otherwise the
creature thinks **once a day, at 22:00**, with the day's summary as the
reason. The spine runs all day on the host; `--resume` carries the
experience from night to night.

What it learns, starting day one: where THIS person sits and stands (the
mean of heights held ≥10 min, replacing the seed's 72/110 defaults once
two holds agree), their attendance (first arrival, last leaving, visits,
bout lengths — in every day line, for the soul to accumulate across days
in the experience), and which invitations this person answers. The
`seed_experience.md` marks every constant GUESSED and says what would
measure it; the ideas shelf there (the nudge, the half-way height, the
morning height, timing moves to a break that always happens) is where
the soul's first weeks are expected to go.

## Structure

    creatures/desk/
      main.py              the runtime (live, always on: journal replay,
                           IV/TIME handshake, mem, the range pump, the
                           desk task, the body rule, touch latch)
      lib/
        calc.py            Calc (Gate / Running / Ema / Ring / ...)
        ultrasonic.py      the RCWL-9620 driver (pump only)
        idasen.py          BleDesk / VirtualDesk, one interface
      seed_instinct.py     the mind
      character.md, embodiment.md, seed_experience.md, creature.toml
      tune.py, recipes.py  bring-up tools
      smoke_desk.py        the seed against a stubbed body, CPython,
                           a compressed day — run it after every seed edit
      logs/                sessions (gitignored)

## Bring-up

    flash creatures/desk --wifi <profile>
    tune  creatures/desk

1. `scan` — the ultrasonic unit should answer at 0x57 on Port A. The
   runtime tries both pin orders (the CoreS3 docs disagree about which
   of G1/G2 is SCL) and the BOOT line says `range=ok`.
2. `range` — sit, lean back, reach into a drawer, stand, walk away, come
   back. The empty chair should read over a metre or `echo-`; a person
   a few hundred mm. Move the seed's `PRESENT_MM` / `ABSENT_MM` to fit.
3. `activity` — hands off, then type, then mouse. `ACT_MG` goes between
   hands-off and typing with room on both sides.
4. `desk` with the virtual desk, then `goto 110`, `hand 72` (the pretend
   paddle: a `DESK:<mm>` message, so the running instinct sees it as
   THEIR move and `goto` while sitting there gets refused by the body
   rule). Then `deploy baseline` and play a day through by hand.
5. The real desk: `blescan` lists advertisers — the DPG shows up as
   "Desk NNNN" or similar. Put its MAC in `DESK_MAC`, reflash, `desk`
   again: press the paddle and watch height change with `THEIRS`.

Then: `spine creatures/desk` for the first day, `spine creatures/desk
--resume` every day after.

    python creatures/desk/smoke_desk.py     # the seed's logic, no hardware

## Not yet verified on hardware (2026-09-17)

- **The Linak BLE protocol** in `lib/idasen.py` is the one
  idasen-controller / linak-dpg-bt document (service `99fa0001-…`,
  control `…0002`, height notify `…0021` as `<Hh` in 0.1 mm / 0.01 mm/s,
  reference input `…0031` refreshed every 200 ms as the deadman). It has
  not been driven against a real desk from this board. The first bench
  session with the desk is where `BleDesk` gets confirmed or fixed; the
  facade the instinct sees does not change either way.
- **Port A pin order** (G1/G2 SCL/SDA) — the runtime scans both; the
  boot log says which it kept.
- **Ultrasonic sentinel behaviour** — what the RCWL-9620 returns with
  nothing in range (0? 4500+?) is collapsed to 0 either way; the `range`
  recipe shows what actually comes back.
- **`ACT_MG`, `PRESENT_MM`, `ABSENT_MM`** — guessed; the tuner recipes
  above are how they get measured.
