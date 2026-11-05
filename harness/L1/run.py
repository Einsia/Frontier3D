# ruff: noqa: I001
"""Command-line entry point for the first-stage L1 harness."""

from harness.L1.common.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
