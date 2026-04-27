"""채팅방, 멤버 테이블 추가

Revision ID: 2ed78c5c56db
Revises: 6cd14a395ef3
Create Date: 2026-04-22 08:58:07.355193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ed78c5c56db'
down_revision: Union[str, Sequence[str], None] = '6cd14a395ef3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # chat_room 테이블
    op.create_table(
        'chat_room',
        sa.Column('chat_room_id', sa.String(length=50), nullable=False),
        sa.Column('type', sa.Enum('DIRECT', 'GROUP', name='chatroomtype'), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=True),
        # 탈퇴 정책: 유저 삭제 시 FK 는 SET NULL → 방과 히스토리는 유지, 탈퇴자 자리만 NULL 로.
        sa.Column('creator_id', sa.String(length=50), nullable=True),
        sa.Column('direct_user_a_id', sa.String(length=50), nullable=True),
        sa.Column('direct_user_b_id', sa.String(length=50), nullable=True),
        sa.Column('last_message_id', sa.String(length=50), nullable=True),
        sa.Column('last_message_server_seq', sa.BigInteger(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column(
            'effective_last_at',
            sa.DateTime(timezone=True),
            sa.Computed('COALESCE(last_message_at, created_at)', persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "("
            "  type = 'GROUP'"
            "  AND direct_user_a_id IS NULL"
            "  AND direct_user_b_id IS NULL"
            ") OR ("
            "  type = 'DIRECT'"
            "  AND direct_user_a_id IS NOT NULL"
            "  AND direct_user_b_id IS NOT NULL"
            "  AND direct_user_a_id < direct_user_b_id"
            ") OR ("
            "  type = 'DIRECT'"
            "  AND (direct_user_a_id IS NULL OR direct_user_b_id IS NULL)"
            ")",
            name='ck_chat_room_direct_pair_shape',
        ),
        # 유저 탈퇴 시 방·히스토리는 보존 → SET NULL
        sa.ForeignKeyConstraint(['creator_id'], ['users.user_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['direct_user_a_id'], ['users.user_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['direct_user_b_id'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('chat_room_id'),
    )
    op.create_index(
        'ix_chat_room_effective_last_at', 'chat_room', ['effective_last_at'], unique=False,
    )
    op.create_index(
        'uq_chat_room_direct_pair',
        'chat_room',
        ['direct_user_a_id', 'direct_user_b_id'],
        unique=True,
        postgresql_where=sa.text("type = 'DIRECT'"),
    )

    # chat_room 은 last_message_* 가 메시지마다 UPDATE 되므로 autovacuum 을 공격적으로.
    op.execute(
        "ALTER TABLE chat_room SET ("
        "autovacuum_vacuum_scale_factor = 0.05, "
        "autovacuum_analyze_scale_factor = 0.05"
        ")"
    )

    # chat_room_member 테이블
    op.create_table(
        'chat_room_member',
        sa.Column('chat_room_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_read_message_server_seq', sa.BigInteger(), nullable=True),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_left', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.ForeignKeyConstraint(['chat_room_id'], ['chat_room.chat_room_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('chat_room_id', 'user_id'),
    )
    op.create_index(
        'ix_chat_room_member_user_active',
        'chat_room_member',
        ['user_id'],
        unique=False,
        postgresql_where=sa.text('is_left = false'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_room_member_user_active', table_name='chat_room_member')
    op.drop_table('chat_room_member')
    op.drop_index('uq_chat_room_direct_pair', table_name='chat_room')
    op.drop_index('ix_chat_room_effective_last_at', table_name='chat_room')
    op.drop_table('chat_room')
    # ENUM 타입 제거 (PostgreSQL 은 drop_table 해도 자동 제거 안 됨)
    sa.Enum(name='chatroomtype').drop(op.get_bind(), checkfirst=True)
