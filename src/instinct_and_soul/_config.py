"""
_config.py — shared config-file loader for spine and flash.

Lookup order for any relative path `<rel>`:
    1. ./.config/<rel>                          (project-local)
    2. ~/.config/instinct-and-soul/<rel>        (user-global)
"""

import os
import re
import tomllib
from pathlib import Path


def config_search_paths(rel):
    return [
        Path.cwd() / ".config" / rel,
        Path.home() / ".config" / "instinct-and-soul" / rel,
    ]


def find_config(rel):
    for p in config_search_paths(rel):
        if p.is_file():
            return p
    return None


# ── TOML loading with friendly errors ─────────────────────────────────────

# tomllib's error messages embed location like "Invalid value (at line 8, column 9)".
_LINECOL_RE = re.compile(r"\(at line (\d+), column (\d+)\)")


def _extract_line_col(msg: str):
    m = _LINECOL_RE.search(msg)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _format_toml_error(path: Path, exc: tomllib.TOMLDecodeError) -> str:
    """Build a multiline error string showing the offending line and a caret."""
    msg = str(exc)
    line_n, col_n = _extract_line_col(msg)
    out = ["{}: invalid TOML — {}".format(path, msg)]
    if line_n:
        try:
            file_lines = Path(path).read_text().splitlines()
        except Exception:
            file_lines = []
        if 1 <= line_n <= len(file_lines):
            content = file_lines[line_n - 1]
            prefix = "  line {}: ".format(line_n)
            out.append(prefix + content)
            if col_n:
                out.append(" " * (len(prefix) + col_n - 1) + "^")
    return "\n".join(out)


def _load_toml(path: Path) -> dict:
    """Open + parse a TOML file. Re-raises parse errors as SystemExit with
    a file path, line content, and a caret pointing at the column."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(_format_toml_error(path, e))


# ── Public API ────────────────────────────────────────────────────────────

def load_config_toml():
    """Load the top-level config.toml; return {} if missing."""
    p = find_config("config.toml")
    if p is None:
        return {}
    return _load_toml(p)


def load_profile(subdir, name):
    """Load .config/<subdir>/<name>.toml. Raises FileNotFoundError listing
    the paths searched."""
    rel = os.path.join(subdir, name + ".toml")
    p = find_config(rel)
    if p is None:
        searched = ", ".join(str(s) for s in config_search_paths(rel))
        raise FileNotFoundError(
            "{} profile '{}' not found. Searched: {}".format(subdir, name, searched))
    return _load_toml(p)
