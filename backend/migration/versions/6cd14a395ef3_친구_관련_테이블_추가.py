"""친구 관련 테이블 추가

Revision ID: 6cd14a395ef3
Revises: 8197254a8569
Create Date: 2026-04-20 04:10:29.062218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6cd14a395ef3'
down_revision: Union[str, Sequence[str], None] = '8197254a8569'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('friendship',
    sa.Column('friendship_id', sa.String(length=50), nullable=False),
    sa.Column('requester_id', sa.String(length=50), nullable=False),
    sa.Column('addressee_id', sa.String(length=50), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', name='friendshipstatus'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('requester_id <> addressee_id', name='ck_friendship_not_self'),
    sa.ForeignKeyConstraint(['addressee_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requester_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('friendship_id')
    )
    op.create_index('ix_friendship_addressee_status', 'friendship', ['addressee_id', 'status'], unique=False)
    op.create_index('ix_friendship_requester_status', 'friendship', ['requester_id', 'status'], unique=False)
    op.create_index('uq_friendship_canonical_pair', 'friendship', [sa.literal_column('least(requester_id, addressee_id)'), sa.literal_column('greatest(requester_id, addressee_id)')], unique=True)
    op.create_table('user_block',
    sa.Column('block_id', sa.String(length=50), nullable=False),
    sa.Column('blocker_id', sa.String(length=50), nullable=False),
    sa.Column('blocked_id', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('blocker_id <> blocked_id', name='ck_user_block_not_self'),
    sa.ForeignKeyConstraint(['blocked_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['blocker_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('block_id'),
    sa.UniqueConstraint('blocker_id', 'blocked_id', name='uq_user_block_pair')
    )
    op.create_index('ix_user_block_blocked', 'user_block', ['blocked_id'], unique=False)
    op.create_index('ix_user_block_blocker', 'user_block', ['blocker_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_block_blocker', table_name='user_block')
    op.drop_index('ix_user_block_blocked', table_name='user_block')
    op.drop_table('user_block')
    op.drop_index('uq_friendship_canonical_pair', table_name='friendship')
    op.drop_index('ix_friendship_requester_status', table_name='friendship')
    op.drop_index('ix_friendship_addressee_status', table_name='friendship')
    op.drop_table('friendship')
