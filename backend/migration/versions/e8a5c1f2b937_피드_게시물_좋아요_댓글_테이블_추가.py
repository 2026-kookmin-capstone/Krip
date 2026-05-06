"""피드 게시물/좋아요/댓글 테이블 추가

Revision ID: e8a5c1f2b937
Revises: f3a1c8d4e2b9
Create Date: 2026-05-06 00:00:00.000000

피드 도메인 RDB 모델:
    - feed_post          : 메인 게시물 메타 (visibility / caption / 다해상도 이미지 URL)
    - feed_post_like     : composite PK (user_id, post_id) — 유저당 게시물 1회 제한
    - feed_post_comment  : 댓글 (1~500자, char_length >= 1 CHECK)

cascade:
    - users 삭제 → feed_post / feed_post_like / feed_post_comment 모두 ON DELETE CASCADE
    - feed_post 삭제 → feed_post_like / feed_post_comment 자동 정리
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8a5c1f2b937'
down_revision: Union[str, Sequence[str], None] = 'f3a1c8d4e2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── feed_post ─────────────────────────────────────────
    op.create_table(
        'feed_post',
        sa.Column('post_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column(
            'visibility',
            sa.Enum('PRIVATE', 'FRIENDS', 'PUBLIC', name='feedvisibility'),
            nullable=False,
        ),
        sa.Column('caption', sa.String(length=100), nullable=True),
        sa.Column('original_url', sa.String(length=500), nullable=False),
        sa.Column('thumbnail_small_url', sa.String(length=500), nullable=False),
        sa.Column('thumbnail_medium_url', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id'),
    )
    # 본인 / 친구 / 비친구 모든 페이지네이션을 단일 인덱스로 커버.
    # service 가 visibility 부분집합을 IN 으로 좁히면 PG btree 가 reverse-scan + 멀티 IN 처리.
    op.create_index(
        'ix_feed_post_owner_visibility_created',
        'feed_post',
        ['user_id', 'visibility', 'created_at', 'post_id'],
        unique=False,
    )

    # ── feed_post_like ────────────────────────────────────
    op.create_table(
        'feed_post_like',
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('post_id', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['feed_post.post_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'post_id'),
    )
    op.create_index('ix_feed_post_like_post_id', 'feed_post_like', ['post_id'], unique=False)

    # ── feed_post_comment ─────────────────────────────────
    op.create_table(
        'feed_post_comment',
        sa.Column('comment_id', sa.String(length=50), nullable=False),
        sa.Column('post_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('content', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('char_length(content) >= 1', name='ck_feed_post_comment_min_length'),
        sa.ForeignKeyConstraint(['post_id'], ['feed_post.post_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('comment_id'),
    )
    op.create_index(
        'ix_feed_post_comment_post_created',
        'feed_post_comment',
        ['post_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_feed_post_comment_post_created', table_name='feed_post_comment')
    op.drop_table('feed_post_comment')

    op.drop_index('ix_feed_post_like_post_id', table_name='feed_post_like')
    op.drop_table('feed_post_like')

    op.drop_index('ix_feed_post_owner_visibility_created', table_name='feed_post')
    op.drop_table('feed_post')

    # Enum 타입 정리 — drop_table 만으로는 PG 의 ENUM TYPE 이 남음.
    # checkfirst=True 로 idempotent 하게 처리 (이미 다른 곳에서 정리된 경우 대비).
    sa.Enum(name='feedvisibility').drop(op.get_bind(), checkfirst=True)
