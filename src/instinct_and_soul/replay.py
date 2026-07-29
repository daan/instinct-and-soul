"""
replay.py — re-ask stored reflection prompts, offline.

Every reflection JSON stores its `prompt` verbatim, and the session dir keeps
the `embodiment.md` that was in force. So asking "would the soul have
written working code?" needs no device, no session, no simulator — just send
it again. Same shape as check_llm.py, with real prompts.

Usage:
    replay LOG/reflections/*.json -o out/ --extract   # no API: unpack what
                                                      # the record already has
    replay LOG/reflections/*.json -o out/             # N prompts -> N responses
    replay out/                                       # analyze what came back

Every response is written twice: `<name>.txt` (the whole reply) and
`<name>.py` (just the instinct, unescaped) — because a reflection JSON keeps
code as one long escaped string that no one can read. --extract does the
same for the STORED response without calling anything, so June's code is
readable straight from the log.

The analysis is mechanical: did a complete <instinct> block arrive, and does
it compile. It judges DELIVERY, not whether the policy was any good.
"""

import argparse
import asyncio
import json
import os
import re

INSTINCT = re.compile(r"<instinct>(.*?)</instinct>", re.S)


def _write(out_dir, name, text, source_note):
    """Response as-is, plus the instinct as a readable .py."""
    with open(os.path.join(out_dir, name + ".txt"), "w") as f:
        f.write(text)
    m = INSTINCT.search(text)
    code = m.group(1).strip() if m else None
    if code:
        with open(os.path.join(out_dir, name + ".py"), "w") as f:
            f.write("# {}\n{}\n".format(source_note, code))
    elif "<instinct>" in text:   # opened, never closed — keep the fragment
        frag = text.split("<instinct>", 1)[1]
        with open(os.path.join(out_dir, name + ".truncated.py"), "w") as f:
            f.write("# {}\n# TRUNCATED mid-code — no closing tag\n{}\n"
                    .format(source_note, frag))


def _verdict(text):
    if "<instinct>" not in text:
        return "no-instinct"
    if "</instinct>" not in text:
        return "TRUNCATED mid-code"
    try:
        compile(INSTINCT.search(text).group(1), "<instinct>", "exec")
    except SyntaxError as e:
        return "syntax-error line {}".format(e.lineno)
    return "ok ({} lines)".format(
        len(INSTINCT.search(text).group(1).strip().splitlines()))


def _name(path, session):
    return "{}_{}".format(os.path.basename(session), os.path.basename(path)[:-5])


def _then(d):
    orig = d.get("response", "") or ""
    return ("TRUNCATED mid-code"
            if "<instinct>" in orig and "</instinct>" not in orig
            else _verdict(orig))


def _extract(paths, out_dir):
    """No API: unpack the stored responses into readable files."""
    os.makedirs(out_dir, exist_ok=True)
    for path in paths:
        d = json.load(open(path))
        session = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        name = _name(path, session)
        _write(out_dir, name + ".then", d.get("response", "") or "",
               "from the record: {}".format(os.path.relpath(path)))
        print("{}: {}".format(name, _then(d)))
    print("\nunpacked to {} — .py is the instinct, .txt the whole reply".format(out_dir))


async def _ask(paths, llm_name, out_dir, system_override=None):
    from .llm import load_llm
    client, info = load_llm(llm_name)
    print("llm: {api}/{model}\n".format(**info))
    if system_override:
        print("system prompt OVERRIDE: {}\n".format(system_override))
    os.makedirs(out_dir, exist_ok=True)
    override_text = open(system_override).read() if system_override else None

    for path in paths:
        d = json.load(open(path))
        prompt = d.get("prompt")
        if not prompt:
            print("{}: no stored prompt — skipped".format(path))
            continue
        session = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        system = override_text or open(os.path.join(session, "embodiment.md")).read()

        name = _name(path, session)
        if os.path.exists(os.path.join(out_dir, name + ".txt")):
            print("{}: cached".format(name))
            continue

        result = await client.call(system, prompt)
        text = result["text"] or ""
        _write(out_dir, name, text, "replay of {}".format(os.path.relpath(path)))
        was = _then(d)
        with open(os.path.join(out_dir, name + ".meta.json"), "w") as f:
            json.dump({"source": os.path.abspath(path), "then": was,
                       "then_output_tokens": (d.get("usage") or {}).get("output_tokens"),
                       "now_stop_reason": str(result.get("stop_reason")),
                       "now_output_tokens": result["usage"]["output_tokens"]}, f, indent=2)
        print("{}: then {:20s} now {}".format(name, was, _verdict(text)))


def _analyze(out_dir):
    rows = []
    for f in sorted(os.listdir(out_dir)):
        if not f.endswith(".txt") or f.endswith(".then.txt"):
            continue
        meta_path = os.path.join(out_dir, f[:-4] + ".meta.json")
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        rows.append((f[:-4], meta.get("then", "?"),
                     _verdict(open(os.path.join(out_dir, f)).read())))

    print("{:<50} {:<20} {}".format("reflection", "THEN", "NOW"))
    print("-" * 92)
    for slug, was, now in rows:
        print("{:<50} {:<20} {}".format(slug[-50:], was, now))

    then_bad = sum(1 for r in rows if r[1].startswith("TRUNCATED"))
    now_ok = sum(1 for r in rows if r[2].startswith("ok"))
    print("\n{} replayed — {} were truncated in the record, {} now return "
          "compilable code".format(len(rows), then_bad, now_ok))
    print("Note: replays run on TODAY's model — this shows the prompt was "
          "answerable, not that the June model would have succeeded.")


def main():
    ap = argparse.ArgumentParser(description="Re-ask stored reflection prompts.")
    ap.add_argument("paths", nargs="+",
                    help="reflection JSON path(s) to ask, or one output dir to analyze")
    ap.add_argument("--llm", default=None, metavar="NAME", help="LLM profile")
    ap.add_argument("-o", "--out", default=None, help="write responses here")
    ap.add_argument("--extract", action="store_true",
                    help="no API call: unpack the STORED response into "
                         "readable .txt/.py (how to read June's code)")
    ap.add_argument("--system", default=None, metavar="PATH",
                    help="use this system prompt instead of the session's "
                         "(for menu-on/off A/B tests)")
    args = ap.parse_args()

    if len(args.paths) == 1 and os.path.isdir(args.paths[0]):
        _analyze(args.paths[0])
        return
    if not args.out:
        ap.error("-o OUT is required (N files are written there)")
    if args.extract:
        _extract(args.paths, args.out)
        return
    asyncio.run(_ask(args.paths, args.llm, args.out, args.system))


if __name__ == "__main__":
    main()
