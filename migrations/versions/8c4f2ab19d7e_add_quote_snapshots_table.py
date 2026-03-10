"""add_quote_snapshots_table

Revision ID: 8c4f2ab19d7e
Revises: 5f8e3a4c9b21
Create Date: 2026-03-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8c4f2ab19d7e"
down_revision: Union[str, Sequence[str], None] = "5f8e3a4c9b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quote_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("snapshot_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("twap", postgresql.NUMERIC(precision=20, scale=10), nullable=False),
        sa.Column("mid_price", postgresql.NUMERIC(precision=20, scale=10), nullable=False),
        sa.Column("bid_quote", postgresql.NUMERIC(precision=20, scale=10), nullable=True),
        sa.Column("ask_quote", postgresql.NUMERIC(precision=20, scale=10), nullable=True),
        sa.Column("twap_lookback_hours", sa.Integer(), nullable=False),
        sa.Column("spread_bps", postgresql.NUMERIC(precision=10, scale=4), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_snapshots_snapshot_ts", "quote_snapshots", ["snapshot_ts"], unique=False)
    op.create_index(
        "ix_quote_snapshots_exchange_symbol_account_snapshot_ts",
        "quote_snapshots",
        ["exchange", "symbol", "account_name", "snapshot_ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quote_snapshots_exchange_symbol_account_snapshot_ts", table_name="quote_snapshots")
    op.drop_index("ix_quote_snapshots_snapshot_ts", table_name="quote_snapshots")
    op.drop_table("quote_snapshots")
