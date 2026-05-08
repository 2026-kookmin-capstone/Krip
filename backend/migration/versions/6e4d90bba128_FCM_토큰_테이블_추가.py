"""FCM 토큰 테이블 추가

Revision ID: 6e4d90bba128
Revises: 5779377394cc
Create Date: 2026-05-03 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e4d90bba128'
down_revision: Union[str, Sequence[str], None] = '5779377394cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'fcm_token',
        sa.Column('fcm_token_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('fcm_token_id'),
        sa.UniqueConstraint('token', name='uq_fcm_token_token'),
    )
    op.create_index('ix_fcm_token_user_id', 'fcm_token', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_fcm_token_user_id', table_name='fcm_token')
    op.drop_table('fcm_token')
