#!/usr/bin/env bash
set -euo pipefail

OBJECT="${1:?usage: restore_sqlite.sh oss://bucket/backups/news_TS.db.gz [target=data/news.db]}"
TARGET="${2:-data/news.db}"
OSS_ENDPOINT="${OSS_ENDPOINT:?must set}"
OSSUTIL="${OSSUTIL:-ossutil64}"

TMP="/tmp/restore_$$.db.gz"
"$OSSUTIL" cp "$OBJECT" "$TMP" --endpoint "$OSS_ENDPOINT"
gunzip -f "$TMP"
RESTORED="${TMP%.gz}"

if [ -f "$TARGET" ]; then
    cp "$TARGET" "${TARGET}.before-restore"
fi
mv "$RESTORED" "$TARGET"
echo "restore OK -> $TARGET (previous saved as ${TARGET}.before-restore)"
