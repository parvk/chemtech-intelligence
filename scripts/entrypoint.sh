#!/bin/bash
set -e

echo "==> ChemFlow Intelligence starting (env: ${APP_ENV:-development})"

# Wait for postgres (belt-and-suspenders on top of healthcheck)
if [ -n "$DATABASE_URL" ]; then
    echo "==> Waiting for database..."
    until pg_isready -h "${DB_HOST:-postgres}" -U "${DB_USER:-chemflow}" -q; do
        sleep 1
    done
    echo "==> Database ready."
fi

# Future: run alembic migrations here
# echo "==> Running migrations..."
# alembic upgrade head

exec "$@"
