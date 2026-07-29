"""
check_llm.py — verify an LLM profile works for spine.

Usage:
    check-llm                          # ping the default LLM from .config/config.toml
    check-llm --llm openrouter         # ping a specific profile in .config/llm/
    check-llm creatures/sticks3        # full reflection-shaped test using
                                       # the creature's embodiment.md
    check-llm creatures/sticks3 --llm openrouter

The simple ping verifies api/model/key/base_url are valid.
The creature mode sends a reflection-shaped prompt and checks that the
response contains <intent>...</intent>. If a model can't produce that
tag, spine silently drops its reflections.
"""

import argparse
import asyncio
import os
import re
import sys
import time

from .llm import load_llm, compute_cost


_SIMPLE_SYS = "You are a tiny test bot. Reply with a one-sentence acknowledgement."
_SIMPLE_USR = "Say hello."

_REFLECTION_USR = (
    "<character>You are a brick that likes being touched.</character>\n"
    "<experience>I am resting on a table. light=80 prox=9.</experience>\n"
    "<instinct>async def run():\n"
    "    while True:\n"
    "        await asyncio.sleep_ms(33)\n"
    "</instinct>\n"
    "<crashed>false</crashed>\n"
    "<messages>\n"
    "  [00:00:01] accel x=0.00 y=0.00 z=1.00 var=0.000012 light=80 prox=9\n"
    "</messages>"
)


async def _run(creature_path, llm_name):
    client, info = load_llm(llm_name)
    print("llm:     {api}/{model}".format(**info))
    if info.get("llm"):
        print("profile: {}".format(info["llm"]))
    elif llm_name is None:
        print("profile: (from .config/config.toml or fallback)")

    if creature_path:
        sp = os.path.join(creature_path, "embodiment.md")
        if not os.path.isfile(sp):
            raise SystemExit("check-llm: no embodiment.md in {}".format(creature_path))
        with open(sp) as f:
            system_prompt = f.read()
        user_message = _REFLECTION_USR
        mode = "reflection (creature={})".format(os.path.basename(os.path.normpath(creature_path)))
    else:
        system_prompt = _SIMPLE_SYS
        user_message = _SIMPLE_USR
        mode = "simple ping"

    print("mode:    {}".format(mode))
    print("calling...", end="", flush=True)

    start = time.monotonic()
    call_task = asyncio.create_task(client.call(system_prompt, user_message))
    while not call_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(call_task), timeout=2.0)
        except asyncio.TimeoutError:
            print(" {:.0f}s".format(time.monotonic() - start), end="", flush=True)
    elapsed = time.monotonic() - start
    print(" done ({:.1f}s)".format(elapsed))
    print()
    result = call_task.result()
    text = result["text"]
    usage = result["usage"]

    if text is None:
        print("─── response ─────────────────────────────────────────────────")
        print("(empty content — model returned no text)")
        print("──────────────────────────────────────────────────────────────")
        print()
        print("tokens: in={}  out={}".format(
            usage["input_tokens"], usage["output_tokens"]))
        print()
        print("FAIL: model returned no content. Likely cause: a reasoning model")
        print("      consumed all output tokens on hidden thinking before producing")
        print("      visible output. Raise max_tokens in src/instinct_and_soul/llm.py,")
        print("      or switch to a non-reasoning model.")
        return 1

    print("─── response ─────────────────────────────────────────────────")
    print(text)
    print("──────────────────────────────────────────────────────────────")
    print()
    print("tokens: in={}  cache_read={}  cache_write={}  out={}  ({:.0f} tok/s out)".format(
        usage["input_tokens"],
        usage["cache_read_input_tokens"],
        usage["cache_creation_input_tokens"],
        usage["output_tokens"],
        usage["output_tokens"] / elapsed if elapsed > 0 else 0))
    cost = compute_cost(info["model"], usage)
    if cost is not None:
        print("cost:   ${:.4f}".format(cost))

    if creature_path:
        m = re.search(r"<intent>(.*?)</intent>", text, re.DOTALL)
        if m:
            print()
            print("PASS: <intent> tag found ({} chars)".format(len(m.group(1).strip())))
            for tag in ("experience", "instinct"):
                if re.search(r"<{0}>(.*?)</{0}>".format(tag), text, re.DOTALL):
                    print("      <{}> also present".format(tag))
            return 0
        else:
            print()
            print("FAIL: <intent> tag NOT found — spine would silently drop reflections from this model")
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Check that an LLM profile works for spine.")
    parser.add_argument("creature_path", nargs="?", default=None,
                        help="Optional creature dir; uses its embodiment.md for a reflection-shaped test")
    parser.add_argument("--llm", default=None, metavar="NAME",
                        help="LLM profile name; overrides .config/config.toml")
    args = parser.parse_args()

    rc = asyncio.run(_run(args.creature_path, args.llm))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
