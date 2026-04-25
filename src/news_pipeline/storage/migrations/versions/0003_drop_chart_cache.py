"""drop chart_cache table"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_chart_req_hash", table_name="chart_cache")
    op.drop_table("chart_cache")


def downgrade() -> None:
    op.create_table(
        "chart_cache",
        sa.Column("id", sa.Integer(), nullable=True),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("oss_url", sa.String(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_chart_req_hash", "chart_cache", ["request_hash"], unique=True)
