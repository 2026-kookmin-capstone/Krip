"""탐색용 active 유저 partial 인덱스 추가

Revision ID: f3a1c8d4e2b9
Revises: bb406aafa5ce
Create Date: 2026-05-04 00:00:00.000000

`/api/auth/profile/all` 등 본인 제외 ACTIVE 유저 탐색 쿼리:
    WHERE status='active' AND user_id != $1
    ORDER BY created_at DESC, user_id DESC

ACTIVE 가 전체의 압도적 다수라 단순 status 인덱스는 planner 가 스킵하므로,
partial index 로 ACTIVE row 만 (created_at, user_id) 로 정렬해 둔다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a1c8d4e2b9'
down_revision: Union[str, Sequence[str], None] = 'bb406aafa5ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_users_active_created',
        'users',
        ['created_at', 'user_id'],
        unique=False,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_users_active_created', table_name='users')
