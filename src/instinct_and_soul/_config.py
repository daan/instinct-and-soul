"""
_config.py — shared config-file loader for spine and flash.

Lookup order for any relative path `<rel>`:
    1. ./.config/<rel>                          (project-local)
    2. ~/.config/instinct-and-soul/<rel>        (user-global)
"""

import os
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


def load_config_toml():
    """Load the top-level config.toml; return {} if missing."""
    p = find_config("config.toml")
    if p is None:
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def load_profile(subdir, name):
    """Load .config/<subdir>/<name>.toml. Raises FileNotFoundError listing
    the paths searched."""
    rel = os.path.join(subdir, name + ".toml")
    p = find_config(rel)
    if p is None:
        searched = ", ".join(str(s) for s in config_search_paths(rel))
        raise FileNotFoundError(
            "{} profile '{}' not found. Searched: {}".format(subdir, name, searched))
    with open(p, "rb") as f:
        return tomllib.load(f)
