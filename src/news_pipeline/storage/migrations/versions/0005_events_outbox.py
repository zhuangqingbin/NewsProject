"""Independent v2 processing state, events, assessments and transactional outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_news", sa.Column("v2_state", sa.String(), nullable=True))
    op.execute("UPDATE raw_news SET v2_state = 'legacy'")
    op.execute("CREATE INDEX idx_raw_v2_pending ON raw_news(id) WHERE v2_state IS NULL")
    op.execute("""CREATE TABLE events (
        id INTEGER PRIMARY KEY, first_seen_at DATETIME NOT NULL, last_seen_at DATETIME NOT NULL,
        headline TEXT NOT NULL, norm_headline TEXT NOT NULL DEFAULT '',
        key_numbers JSON NOT NULL, subject_tickers JSON NOT NULL, tagged_tickers JSON NOT NULL,
        markets JSON NOT NULL, article_count INTEGER NOT NULL DEFAULT 1,
        source_count INTEGER NOT NULL DEFAULT 1, sources JSON NOT NULL,
        first_party BOOLEAN NOT NULL DEFAULT 0, importance_hint INTEGER NOT NULL DEFAULT 0,
        rule_decision TEXT NOT NULL, rule_reason TEXT NOT NULL, rank_score FLOAT NOT NULL DEFAULT 0,
        assess_status TEXT NOT NULL DEFAULT 'pending', assess_attempts INTEGER NOT NULL DEFAULT 0,
        event_type TEXT, scope TEXT, holdings JSON, materiality INTEGER, novelty TEXT,
        same_as_event_id INTEGER, summary TEXT, so_what TEXT, confidence FLOAT, model_used TEXT,
        assessed_at DATETIME, decision TEXT, decision_reason TEXT, decided_at DATETIME,
        digest_delivery_id INTEGER)""")
    op.execute("CREATE INDEX idx_event_first_seen ON events(first_seen_at)")
    op.execute("CREATE INDEX idx_event_assess ON events(assess_status)")
    op.execute("CREATE INDEX idx_event_decision ON events(decision, decided_at)")
    op.execute("""CREATE TABLE event_articles (
        event_id INTEGER NOT NULL REFERENCES events(id),
        raw_id INTEGER NOT NULL REFERENCES raw_news(id), source TEXT NOT NULL,
        joined_at DATETIME NOT NULL, PRIMARY KEY(event_id, raw_id),
        CONSTRAINT uq_evart_raw UNIQUE(raw_id))""")
    op.execute("""CREATE TABLE deliveries (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, event_id INTEGER REFERENCES events(id),
        market TEXT, channel TEXT NOT NULL, payload JSON NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        attempt_timestamps JSON NOT NULL DEFAULT '[]',
        next_attempt_at DATETIME, last_error TEXT, created_at DATETIME NOT NULL, sent_at DATETIME,
        digest_slot TEXT, event_ids JSON NOT NULL, consumed_event_ids JSON NOT NULL,
        CONSTRAINT uq_delivery_event_channel UNIQUE(kind,event_id,channel),
        CONSTRAINT uq_delivery_slot_channel UNIQUE(kind,digest_slot,channel))""")
    op.execute("CREATE INDEX idx_delivery_status ON deliveries(status, next_attempt_at)")
    op.execute("""CREATE TABLE llm_calls (
        id INTEGER PRIMARY KEY, purpose TEXT NOT NULL, event_id INTEGER, model TEXT NOT NULL,
        prompt_version TEXT NOT NULL, tokens_in INTEGER NOT NULL DEFAULT 0,
        tokens_out INTEGER NOT NULL DEFAULT 0, cost_cny FLOAT NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0, ok BOOLEAN NOT NULL DEFAULT 1,
        error TEXT, created_at DATETIME NOT NULL)""")
    op.execute("CREATE INDEX idx_llmcall_created ON llm_calls(created_at)")
    for suffix in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER IF EXISTS news_fts_{suffix}")
    op.execute("DROP TABLE IF EXISTS news_fts")
    op.execute("""CREATE VIRTUAL TABLE events_fts USING fts5(
        headline, summary, content='events', content_rowid='id', tokenize='unicode61')""")
    op.execute("""CREATE TRIGGER events_fts_ai AFTER INSERT ON events BEGIN
        INSERT INTO events_fts(rowid,headline,summary) VALUES(new.id,new.headline,new.summary);
        END""")
    op.execute("""CREATE TRIGGER events_fts_ad AFTER DELETE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,headline,summary)
        VALUES('delete',old.id,old.headline,old.summary); END""")
    op.execute("""CREATE TRIGGER events_fts_au AFTER UPDATE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,headline,summary)
        VALUES('delete',old.id,old.headline,old.summary);
        INSERT INTO events_fts(rowid,headline,summary) VALUES(new.id,new.headline,new.summary);
        END""")


def downgrade() -> None:
    for suffix in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER IF EXISTS events_fts_{suffix}")
    op.execute("DROP TABLE IF EXISTS events_fts")
    for table in ("event_articles", "deliveries", "llm_calls", "events"):
        op.drop_table(table)
    op.drop_index("idx_raw_v2_pending", table_name="raw_news")
    op.drop_column("raw_news", "v2_state")
    # Restore the old FTS implementation for an explicit schema downgrade.
    import importlib

    importlib.import_module("news_pipeline.storage.migrations.versions.0002_fts").upgrade()
