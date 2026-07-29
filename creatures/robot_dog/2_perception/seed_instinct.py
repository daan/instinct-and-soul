"""Seed instinct for robot_dog 2_perception: journal what the senses see.

No actuators in this stage — the work is watching. Report the warm-shape
percept and the nose-beam distance at a steady cadence, plus an event line
when presence flips, so the soul can judge sense quality from the journal
alone. Soul can rewrite this on reflection.

send() only writes to the record — it does not summon the soul. reflect()
does, and costs a reflection, so it is called when presence FLIPS (the one
moment the world actually changed) rather than on the steady cadence."""


async def run():
    last_present = None
    tick = 0
    while True:
        w = warm()
        mm = read_distance_mm()

        if w["present"] != last_present:
            send("EVENT warm {} area={} exc={:.1f}C tof={}".format(
                "appeared" if w["present"] else "gone", w["area"], w["excess_c"], mm))
            # The world changed. Everything between flips is just watching.
            if last_present is not None:
                reflect("someone {} — warm area={} exc={:.1f}C, nose {}mm".format(
                    "appeared" if w["present"] else "left",
                    w["area"], w["excess_c"], mm))
            last_present = w["present"]

        if tick % 4 == 0:
            if w["present"]:
                send("warm area={} exc={:.1f}C at=({:.1f},{:.1f}) amb={:.1f}C age={}ms tof={}".format(
                    w["area"], w["excess_c"], w["cx"], w["cy"],
                    w["ambient_c"], w["age_ms"], mm))
            else:
                send("no-warm amb={:.1f}C tof={}".format(w["ambient_c"], mm))

        tick += 1
        await asyncio.sleep_ms(500)
