#!/bin/sh
# Migrate, seed once, then hand over to the CMD.
#
# Migrations run on start rather than in a separate job because there is one
# API replica in this compose file. With more than one you would run
# `alembic upgrade head` as a pre-deploy step instead -- see the README.
set -e

echo "==> waiting for postgres"
python - <<'PY'
import os, time, sys
import psycopg
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
for attempt in range(60):
    try:
        psycopg.connect(url, connect_timeout=2).close()
        print("    database is up")
        break
    except Exception as exc:
        if attempt == 59:
            print(f"    giving up: {exc}", file=sys.stderr)
            raise
        time.sleep(1)
PY

echo "==> running migrations"
alembic upgrade head

if [ "${SEED_ON_START:-true}" = "true" ]; then
  echo "==> seeding"
  python -m app.seed
fi

echo "==> starting api"
exec "$@"
