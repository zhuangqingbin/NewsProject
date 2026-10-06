import sqlite3

from alembic import command
from alembic.config import Config


def test_upgrade_backfills_sources_and_isolates_legacy_rows(tmp_path):
    path = tmp_path / "old.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(cfg, "0003")
    with sqlite3.connect(path) as conn:
        for source in ("sina_global", "juchao", "wallstreetcn"):
            conn.execute(
                "INSERT INTO source_state(source,last_fetched_at,error_count) VALUES(?,?,0)",
                (source, "2026-10-05 08:00:00"),
            )
            conn.execute(
                """INSERT INTO raw_news(source,market,url,url_hash,title,title_simhash,
                         fetched_at,published_at,status) VALUES(?,'cn',?,?,?,0,?,?, 'pending')""",
                (
                    source,
                    f"https://example.com/{source}",
                    source,
                    "title",
                    "2026-10-05 08:00:00",
                    "2026-10-05 08:00:00",
                ),
            )
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        rows = dict(conn.execute("SELECT source,last_success_at FROM source_state"))
        assert rows["sina_global"] is not None
        assert rows["juchao"] is None
        assert rows["wallstreetcn"] is None
        assert (
            conn.execute("SELECT count(*) FROM raw_news WHERE v2_state='legacy'").fetchone()[0] == 3
        )
        conn.execute("""INSERT INTO events(first_seen_at,last_seen_at,headline,key_numbers,
             subject_tickers,tagged_tickers,markets,sources,rule_decision,rule_reason)
             VALUES('2026-10-06','2026-10-06','NVIDIA buyback',
                    '[]','[]','[]','[]','[]','push','event')""")
        assert (
            conn.execute(
                "SELECT headline FROM events_fts WHERE events_fts MATCH 'buyback'"
            ).fetchone()[0]
            == "NVIDIA buyback"
        )
        conn.execute("UPDATE events SET headline='NVIDIA earnings' WHERE id=1")
        assert (
            conn.execute(
                "SELECT count(*) FROM events_fts WHERE events_fts MATCH 'buyback'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM events_fts WHERE events_fts MATCH 'earnings'"
            ).fetchone()[0]
            == 1
        )
        conn.execute("DELETE FROM events")
        assert (
            conn.execute(
                "SELECT count(*) FROM events_fts WHERE events_fts MATCH 'earnings'"
            ).fetchone()[0]
            == 0
        )
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='idx_raw_v2_pending'"
        ).fetchone()
