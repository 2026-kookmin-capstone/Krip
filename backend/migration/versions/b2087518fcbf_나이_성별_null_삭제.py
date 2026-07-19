"""나이, 성별 null 삭제

Revision ID: b2087518fcbf
Revises: 698b222e8f15
Create Date: 2026-04-08 00:03:18.080797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2087518fcbf'
down_revision: Union[str, Sequence[str], None] = '698b222e8f15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('user_detail_inform', 'age',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.alter_column('user_detail_inform', 'gender',
               existing_type=postgresql.ENUM('MALE', 'FEMALE', name='gender'),
               nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('user_detail_inform', 'gender',
               existing_type=postgresql.ENUM('MALE', 'FEMALE', name='gender'),
               nullable=True)
    op.alter_column('user_detail_inform', 'age',
               existing_type=sa.INTEGER(),
               nullable=True)
