"""알림 차단 컬럼 추가

Revision ID: bb406aafa5ce
Revises: 6e4d90bba128
Create Date: 2026-05-03 18:30:00.000000

users.notification_muted          전역 알림 차단 (True / NULL)
chat_room_member.notification_muted   방별 알림 차단 (True / NULL)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb406aafa5ce'
down_revision: Union[str, Sequence[str], None] = '6e4d90bba128'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('notification_muted', sa.Boolean(), nullable=True),
    )
    op.add_column(
        'chat_room_member',
        sa.Column('notification_muted', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_room_member', 'notification_muted')
    op.drop_column('users', 'notification_muted')
