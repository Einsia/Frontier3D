"""Public unified L1 generation/rerun/scoring entry point."""

# ruff: noqa: I001

from .common.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
