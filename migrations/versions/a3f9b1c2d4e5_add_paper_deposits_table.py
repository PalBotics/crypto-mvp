"""add_paper_deposits_table

Revision ID: a3f9b1c2d4e5
Revises: 8c4f2ab19d7e
Create Date: 2026-03-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a3f9b1c2d4e5"
down_revision: Union[str, Sequence[str], None] = "8c4f2ab19d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_deposits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("amount", postgresql.NUMERIC(precision=20, scale=10), nullable=False),
        sa.Column("note", sa.String(length=100), nullable=True),
        sa.Column("created_ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_deposits_created_ts", "paper_deposits", ["created_ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paper_deposits_created_ts", table_name="paper_deposits")
    op.drop_table("paper_deposits")
