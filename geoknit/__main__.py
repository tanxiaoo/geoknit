"""Allow ``python -m geoknit``."""

from geoknit.cli import main

# The guard matters: spawned worker processes re-import the main module.
if __name__ == "__main__":
    raise SystemExit(main())
