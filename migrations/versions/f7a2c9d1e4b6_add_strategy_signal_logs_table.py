"""add_strategy_signal_logs_table

Revision ID: f7a2c9d1e4b6
Revises: e1f4a9b2c7d3
Create Date: 2026-03-20 20:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a2c9d1e4b6"
down_revision: Union[str, Sequence[str], None] = "e1f4a9b2c7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_signal_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("signal", sa.String(length=50), nullable=False),
        sa.Column("funding_rate_apr", sa.Numeric(precision=18, scale=10), nullable=False),
        sa.Column("eth_mark_price", sa.Numeric(precision=18, scale=10), nullable=False),
        sa.Column("is_dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column(
            "created_ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("strategy_signal_logs")
