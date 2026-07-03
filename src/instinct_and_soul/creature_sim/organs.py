"""Per-creature organs — the socket.

A creature directory may contain an `organs.py` defining one entry point:

    def attach(scope) -> None

The harness loads the file ONCE per session (module-level state therefore
survives instinct hot-swaps, like Mem does) and calls `attach(scope)` at every
instinct (re)load, before the code is exec'd. `attach` may wrap existing scope
entries (e.g. replace Synth with a capturing wrapper) or add new senses under
new names (e.g. an Ear). The harness knows nothing about any specific organ —
it only provides the socket. On the real device, the creature's main.py plays
this role when it builds INSTINCT_ENV.
"""
import os


def load_organs(creature_dir):
    """Exec <creature_dir>/organs.py once; return its attach(scope), or None."""
    if not creature_dir:
        return None
    path = os.path.join(creature_dir, "organs.py")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        src = f.read()
    ns = {"__name__": "__organs__", "__file__": path}
    exec(compile(src, path, "exec"), ns)
    attach = ns.get("attach")
    if not callable(attach):
        raise RuntimeError(f"{path} defines no attach(scope) function")
    return attach
