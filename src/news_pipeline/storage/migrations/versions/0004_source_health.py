"""Source health and selective first-run initialization."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("first_success_at", "last_success_at", "last_item_at", "health_changed_at"):
        op.add_column("source_state", sa.Column(name, sa.DateTime(), nullable=True))
    op.add_column(
        "source_state",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_state", sa.Column("health", sa.String(), nullable=False, server_default="ok")
    )
    op.add_column(
        "source_state", sa.Column("health_reason", sa.String(), nullable=False, server_default="")
    )
    op.execute("""UPDATE source_state SET last_item_at =
        (SELECT max(fetched_at) FROM raw_news WHERE raw_news.source = source_state.source)""")
    op.execute("""UPDATE source_state SET first_success_at = last_fetched_at,
        last_success_at = last_fetched_at WHERE source IN
        ('sina_global','futu_global','eastmoney_global','ths_global',
         'cctv_news','cjzc_em','finnhub')""")


def downgrade() -> None:
    for name in (
        "health_reason",
        "health",
        "consecutive_failures",
        "health_changed_at",
        "last_item_at",
        "last_success_at",
        "first_success_at",
    ):
        op.drop_column("source_state", name)
