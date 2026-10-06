#!/bin/sh
# Run DB migrations then start the main process (or whatever CMD is passed).
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

echo "[entrypoint] exec: $*"
exec "$@"
