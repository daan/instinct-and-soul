async def run():
    while True:
        bpm = Hr.get()
        if bpm is None:
            send("hr: not connected")
        else:
            send("hr: bpm={}".format(bpm))
        await asyncio.sleep(2)
