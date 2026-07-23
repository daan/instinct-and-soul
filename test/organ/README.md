# test/organ — was the promotion evidence real?

Several organs cite soul failure as their reason for admission (ORGANS.md):
Motion because *"souls hallucinated fusion APIs and never got one working"*,
Episode because souls *"kept groping toward gesture-as-envelope and failing"*.
That evidence comes from the June 2026 dancer sessions — and those sessions
ran under a transport bug.

Before 2026-06-24 (commit bc0745a) the response format put `<experience>`
BEFORE `<instinct>` against a 4096-token cap. A long experience ate the
budget, the instinct block was cut mid-code, the closing tag never arrived,
and the spine silently kept the old instinct. Truncation detection did not
exist yet, so those reflections record `truncated: null` — the damage shows
only as an `<instinct>` tag that opens and never closes.

Measured across the pre-fix logs: **136 of 313 reflections** (≈43%) have an
unclosed instinct block. So "the soul never got it working" may mean "the
code never arrived." This experiment settles which.

## The experiment

Every reflection JSON stores its `prompt` verbatim, and each session dir
keeps the `system_prompt.md` in force. So the prompts can be re-asked with
no device, no session, no simulator.

    input/truncated.txt    136 pre-fix reflections whose instinct was cut
    input/controls.txt     20 pre-fix reflections that completed cleanly —
                           these must come back OK, or the harness is wrong
    output/               responses land here

Run:

    # read June's code without spending anything (unpacks the stored reply)
    replay $(cat test/organ/input/truncated.txt) -o test/organ/output --extract

    # re-ask; N prompts -> N responses
    replay $(cat test/organ/input/controls.txt) -o test/organ/output
    replay $(cat test/organ/input/truncated.txt) -o test/organ/output

    # tabulate THEN vs NOW
    replay test/organ/output

Each reflection produces `<name>.txt` (whole reply) and `<name>.py` (just
the instinct, unescaped — a reflection JSON keeps code as one long escaped
string that nobody can read). A cut-off reply writes `<name>.truncated.py`
instead, so you can see exactly where it stopped: the tango-dancer sample
in `output/` ends mid-argument at `round(beat_bpm,`.

Re-asking is cached — a file that exists is skipped, so an interrupted run
resumes without paying twice. Start with the controls; they cost little and
tell you the instrument works.

## Reading the result

The verdict is mechanical on purpose: did a complete `<instinct>` block
arrive, and does it `compile()`. It judges DELIVERY, never whether the
policy was any good — whether the fusion was *correct* is a separate
question this experiment does not touch.

- Truncated-then, compiles-now → the historical failure was transport. The
  organ's stated reason needs revising (the organ itself may still be
  right: Motion and Episode both need filter/hysteresis state that survives
  instinct hot-swaps, which is an independent justification).
- Truncated-then, still fails now → the soul really was groping. Evidence
  stands as written.
- Controls failing → suspect the harness, not the history.

**Caveat to carry into any citation:** replays run on TODAY's model. This
shows the prompt was answerable and the loss mechanical; it cannot show the
June-era model would have succeeded.

## Not affected

The touch line (Handling, Touch, Hunger, **Together**, Familiar) ran from
2026-07-05, after the fix, with detection active and zero truncations —
`i_want_to_be_touched/2_hunger/logs/20260707_063033/reflections/008_178.json`
(Together's evidence) is `stop_reason: STOP`, complete, 4273 tokens. Reading
its shipped code shows the soul built a per-event anecdote (`last_call_t`,
"picked up 12s after my call") but no baseline and no cross-reflection
persistence — which is a sharper promotion reason than the one-liner in
ORGANS.md, and one this experiment does not disturb.
