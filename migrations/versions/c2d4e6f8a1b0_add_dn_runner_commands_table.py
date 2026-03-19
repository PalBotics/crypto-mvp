"""add_dn_runner_commands_table

Revision ID: c2d4e6f8a1b0
Revises: 9f7b8a1c3d2e
Create Date: 2026-03-18 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d4e6f8a1b0"
down_revision: Union[str, Sequence[str], None] = "9f7b8a1c3d2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dn_runner_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column(
            "flatten_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_name"),
    )


def downgrade() -> None:
    op.drop_table("dn_runner_commands")
