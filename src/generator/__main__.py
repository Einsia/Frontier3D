"""Allow the generator to be run with ``python -m src.generator``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
