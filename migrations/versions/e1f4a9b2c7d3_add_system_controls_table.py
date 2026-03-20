"""add_system_controls_table

Revision ID: e1f4a9b2c7d3
Revises: c2d4e6f8a1b0
Create Date: 2026-03-20 15:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f4a9b2c7d3"
down_revision: Union[str, Sequence[str], None] = "c2d4e6f8a1b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO system_controls (key, value, updated_at, reason)
            VALUES
              ('kill_switch_active', 'false', CURRENT_TIMESTAMP, 'migration_seed'),
              ('mm_enabled', 'true', CURRENT_TIMESTAMP, 'migration_seed'),
              ('dn_enabled', 'true', CURRENT_TIMESTAMP, 'migration_seed')
            """
        )
    )


def downgrade() -> None:
    op.drop_table("system_controls")
