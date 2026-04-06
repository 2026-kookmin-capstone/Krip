"""유저 email 중복 제약 해제

Revision ID: d00557f2cb96
Revises: e37189fd0a87
Create Date: 2026-04-06 04:57:35.534824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd00557f2cb96'
down_revision: Union[str, Sequence[str], None] = 'e37189fd0a87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('ix_user_detail_inform_email', table_name='user_detail_inform')
    op.create_index('ix_user_detail_inform_email', 'user_detail_inform', ['email'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_detail_inform_email', table_name='user_detail_inform')
    op.create_index('ix_user_detail_inform_email', 'user_detail_inform', ['email'], unique=True)
