"""add news_fts virtual table + triggers"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIRTUAL TABLE news_fts USING fts5(
            title, summary,
            content='news_processed',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    op.execute("""
        CREATE TRIGGER news_fts_ai AFTER INSERT ON news_processed BEGIN
            INSERT INTO news_fts(rowid, title, summary) VALUES (new.id, '', new.summary);
        END
    """)
    op.execute("""
        CREATE TRIGGER news_fts_ad AFTER DELETE ON news_processed BEGIN
            INSERT INTO news_fts(news_fts, rowid, title, summary)
            VALUES('delete', old.id, '', old.summary);
        END
    """)
    op.execute("""
        CREATE TRIGGER news_fts_au AFTER UPDATE ON news_processed BEGIN
            INSERT INTO news_fts(news_fts, rowid, title, summary)
            VALUES('delete', old.id, '', old.summary);
            INSERT INTO news_fts(rowid, title, summary) VALUES (new.id, '', new.summary);
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS news_fts_au")
    op.execute("DROP TRIGGER IF EXISTS news_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS news_fts_ai")
    op.execute("DROP TABLE IF EXISTS news_fts")
