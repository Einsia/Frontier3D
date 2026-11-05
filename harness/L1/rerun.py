"""Public entry point for fixed-seed L1 reruns."""

# ruff: noqa: I001

from .common.rerun import main


if __name__ == "__main__":
    raise SystemExit(main())
