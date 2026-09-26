"""add putusan run lifecycle

Revision ID: db50e3ec8c34
Revises: 88a15dc3ed28
Create Date: 2026-09-26 22:26:36.562633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db50e3ec8c34'
down_revision: Union[str, Sequence[str], None] = '88a15dc3ed28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'putusan',
        sa.Column('run_id', sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        'fk_putusan_run_id_scraping_runs',
        'putusan',
        'scraping_runs',
        ['run_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_index(
        'ix_putusan_run_id_status',
        'putusan',
        ['run_id', 'status_scraping'],
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_putusan_run_id_status',
        table_name='putusan',
    )

    op.drop_constraint(
        'fk_putusan_run_id_scraping_runs',
        'putusan',
        type_='foreignkey',
    )

    op.drop_column(
        'putusan',
        'run_id',
    )
