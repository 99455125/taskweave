"""Frozen Windows desktop entry point."""

import multiprocessing
import sys

from taskweave.__main__ import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main(["workbench", *sys.argv[1:]]))
