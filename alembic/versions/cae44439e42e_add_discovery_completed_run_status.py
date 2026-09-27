"""add discovery completed run status

Revision ID: cae44439e42e
Revises: db50e3ec8c34
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "cae44439e42e"
down_revision: Union[str, Sequence[str], None] = "db50e3ec8c34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add DISCOVERY_COMPLETED to scrapingrunstatus enum."""
    op.execute(
        "ALTER TYPE scrapingrunstatus "
        "ADD VALUE IF NOT EXISTS 'DISCOVERY_COMPLETED'"
    )


def downgrade() -> None:
    """PostgreSQL does not support removing an enum value directly."""
    raise NotImplementedError(
        "Downgrade is not supported for this PostgreSQL enum value."
    )
