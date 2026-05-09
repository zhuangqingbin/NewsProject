"""Baseline schema for quote_watcher.

Revision ID: 0001
Revises:
Create Date: 2026-05-09

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_bars_1min",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("bar_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.UniqueConstraint("ticker", "bar_start", name="uq_bar1min_ticker_start"),
    )
    op.create_index("idx_bar1min_ticker_ts", "quote_bars_1min", ["ticker", "bar_start"])

    op.create_table(
        "quote_bars_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("prev_close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.UniqueConstraint("ticker", "trade_date", name="uq_bardaily_ticker_date"),
    )

    op.create_table(
        "alert_state",
        sa.Column("rule_id", sa.String(64), primary_key=True),
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("last_triggered_at", sa.BigInteger(), nullable=False),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column(
            "trigger_count_today",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index("idx_alert_state_ticker", "alert_state", ["ticker"])

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column(
            "pushed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("push_message_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("alert_history")
    op.drop_index("idx_alert_state_ticker", table_name="alert_state")
    op.drop_table("alert_state")
    op.drop_table("quote_bars_daily")
    op.drop_index("idx_bar1min_ticker_ts", table_name="quote_bars_1min")
    op.drop_table("quote_bars_1min")
