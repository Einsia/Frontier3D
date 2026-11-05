"""Allow the renderer to be run with ``python -m src.render``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
