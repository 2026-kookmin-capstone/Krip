"""tripmate 브라우즈 피드 partial 인덱스 추가

Revision ID: c5f8a2d17e94
Revises: 9c4d1f8e2a30
Create Date: 2026-07-19 00:00:00.000000

메인 브라우즈 피드 `find_all_displayed` / `search` 쿼리:
    WHERE is_displayed = true
    ORDER BY created_at DESC, post_id DESC

받쳐줄 인덱스가 없어 페이지마다 Seq Scan + Sort 가 발생하므로, 숨김 글을 제외한
partial index 로 (created_at, post_id) 를 정렬해 둔다. ASC 인덱스지만 PG 의
backward scan 이 DESC ORDER BY 를 그대로 커버한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f8a2d17e94'
down_revision: Union[str, Sequence[str], None] = '9c4d1f8e2a30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_tripmate_post_displayed_created',
        'tripmate_post',
        ['created_at', 'post_id'],
        unique=False,
        postgresql_where=sa.text("is_displayed = true"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tripmate_post_displayed_created', table_name='tripmate_post')
