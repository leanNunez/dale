"""`DALE_APP_DATABASE_URL=... python -m dale.erp_sim.infrastructure.seed`: reseed the app DB."""

import os
import sys

import sqlalchemy as sa

from dale.erp_sim.infrastructure.seed import reseed


def main() -> int:
    if not (url := os.environ.get("DALE_APP_DATABASE_URL")):
        print("DALE_APP_DATABASE_URL is not set", file=sys.stderr)
        return 2
    engine = sa.create_engine(url)
    try:
        reseed(engine)
    finally:
        engine.dispose()
    print("reseeded Distribuidora El Hornero")
    return 0


if __name__ == "__main__":
    sys.exit(main())
