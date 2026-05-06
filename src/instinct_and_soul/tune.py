"""
tune.py — launcher for per-creature tuners.

Usage:
    tune creatures/cores3

Locates `<creature_path>/tune.py`, inserts the creature directory onto
sys.path so `from recipes import RECIPES, INSTINCT_IDLE` resolves, and
runs the file as if it were `python tune.py`.
"""

import argparse
import os
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description="Launch a creature's tuner")
    parser.add_argument("creature_path",
                        help="Path to the creature directory (e.g. creatures/cores3)")
    args = parser.parse_args()

    creature_dir = os.path.abspath(args.creature_path)
    tune_file = os.path.join(creature_dir, "tune.py")
    if not os.path.isfile(tune_file):
        parser.error("no tune.py in {}".format(creature_dir))

    # Let the creature's tune.py do `from recipes import ...`.
    sys.path.insert(0, creature_dir)
    runpy.run_path(tune_file, run_name="__main__")


if __name__ == "__main__":
    main()
