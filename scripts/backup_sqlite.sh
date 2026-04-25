#!/usr/bin/env bash
set -euo pipefail

DB="${NEWS_PIPELINE_DB:-data/news.db}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="/tmp/news_${TS}.db"
GZ="/tmp/news_${TS}.db.gz"

sqlite3 "$DB" ".backup '$TMP'"
gzip -f "$TMP"

OSS_BUCKET="${OSS_BUCKET:?must set}"
OSS_ENDPOINT="${OSS_ENDPOINT:?must set}"
OSSUTIL="${OSSUTIL:-ossutil64}"

"$OSSUTIL" cp "$GZ" "oss://${OSS_BUCKET}/backups/news_${TS}.db.gz" \
    --endpoint "$OSS_ENDPOINT"

# Retention: list and delete entries older than 30 days
"$OSSUTIL" ls "oss://${OSS_BUCKET}/backups/" --endpoint "$OSS_ENDPOINT" \
  | awk '{print $NF}' | grep '\.db\.gz$' | while read -r object; do
    name="$(basename "$object")"
    obj_date="${name#news_}"
    obj_date="${obj_date%.db.gz}"
    obj_epoch="$(date -u -j -f "%Y%m%dT%H%M%SZ" "$obj_date" +%s 2>/dev/null || \
                  date -u -d "$(echo "$obj_date" | sed 's/T/ /')" +%s 2>/dev/null || echo 0)"
    cutoff="$(date -u +%s -d '30 days ago' 2>/dev/null || date -u -v-30d +%s)"
    if [ "$obj_epoch" -gt 0 ] && [ "$obj_epoch" -lt "$cutoff" ]; then
        echo "deleting old backup: $object"
        "$OSSUTIL" rm "$object" --endpoint "$OSS_ENDPOINT" -f
    fi
done

rm -f "$GZ"
echo "backup OK: news_${TS}.db.gz"
