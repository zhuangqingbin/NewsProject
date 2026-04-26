#!/bin/sh
# Run DB migrations then start the main process (or whatever CMD is passed).
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] exec: $*"
exec "$@"
