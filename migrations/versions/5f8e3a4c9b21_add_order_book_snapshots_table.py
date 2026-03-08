"""add_order_book_snapshots_table

Revision ID: 5f8e3a4c9b21
Revises: 386b20f64042
Create Date: 2026-03-08 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5f8e3a4c9b21"
down_revision: Union[str, Sequence[str], None] = "386b20f64042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "order_book_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=False),
        sa.Column("adapter_name", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("exchange_symbol", sa.String(length=50), nullable=False),
        sa.Column("bid_price_1", postgresql.NUMERIC(precision=28, scale=10), nullable=False),
        sa.Column("bid_size_1", postgresql.NUMERIC(precision=28, scale=10), nullable=False),
        sa.Column("ask_price_1", postgresql.NUMERIC(precision=28, scale=10), nullable=False),
        sa.Column("ask_size_1", postgresql.NUMERIC(precision=28, scale=10), nullable=False),
        sa.Column("bid_price_2", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("bid_size_2", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("ask_price_2", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("ask_size_2", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("bid_price_3", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("bid_size_3", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("ask_price_3", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("ask_size_3", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("spread", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("spread_bps", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("mid_price", postgresql.NUMERIC(precision=28, scale=10), nullable=True),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_book_snapshots_exchange_symbol_event_ts",
        "order_book_snapshots",
        ["exchange", "symbol", "event_ts"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_order_book_snapshots_exchange_symbol_event_ts",
        table_name="order_book_snapshots",
    )
    op.drop_table("order_book_snapshots")
