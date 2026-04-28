"""유저 프로필 이미지 url 추가

Revision ID: c4f1a8b2d6e3
Revises: 2ed78c5c56db
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1a8b2d6e3'
down_revision: Union[str, Sequence[str], None] = '2ed78c5c56db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_detail_inform',
        sa.Column('profile_image_url', sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_detail_inform', 'profile_image_url')
