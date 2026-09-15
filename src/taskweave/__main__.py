"""Package smoke-check entry point; execution features follow in later requirements."""

import argparse

from taskweave import __version__


def main():
    parser = argparse.ArgumentParser(description="TaskWeave — 本地任务与步骤自动化")
    parser.add_argument("--version", action="version", version=f"TaskWeave {__version__}")
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
