"""유저 국적 정보 추가

Revision ID: 698b222e8f15
Revises: a89d4f05a8fa
Create Date: 2026-04-07 23:39:13.587085

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '698b222e8f15'
down_revision: Union[str, Sequence[str], None] = 'a89d4f05a8fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_detail_inform', sa.Column('nationality', sa.String(length=50), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_detail_inform', 'nationality')
