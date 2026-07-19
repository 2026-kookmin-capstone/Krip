"""유저 회원가입 관련 테이블

Revision ID: e37189fd0a87
Revises: 
Create Date: 2026-04-06 01:16:05.654436

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e37189fd0a87'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('user_id', sa.String(length=50), nullable=False),
    sa.Column('auth_provider', sa.Enum('GOOGLE', name='oauthprovider'), nullable=False),
    sa.Column('auth_provider_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'SUSPENDED', name='userstatus'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('auth_provider', 'auth_provider_id', name='uq_provider_account')
    )
    op.create_index('ix_provider_lookup', 'users', ['auth_provider', 'auth_provider_id'], unique=False)
    op.create_table('user_detail_inform',
    sa.Column('user_id', sa.String(length=50), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('user_name', sa.String(length=100), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=True),
    sa.Column('age', sa.Integer(), nullable=True),
    sa.Column('gender', sa.Enum('MALE', 'FEMALE', name='gender'), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_user_detail_inform_email'), 'user_detail_inform', ['email'], unique=True)
    op.create_table('user_travel_style',
    sa.Column('id', sa.String(length=50), nullable=False),
    sa.Column('user_id', sa.String(length=50), nullable=False),
    sa.Column('style', sa.Enum('ACTIVITY', 'RELAXATION', 'TOURISM', 'SHOPPING', 'FOOD', name='travelstyle'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_travel_style_user_id', 'user_travel_style', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_travel_style_user_id', table_name='user_travel_style')
    op.drop_table('user_travel_style')
    op.drop_index(op.f('ix_user_detail_inform_email'), table_name='user_detail_inform')
    op.drop_table('user_detail_inform')
    op.drop_index('ix_provider_lookup', table_name='users')
    op.drop_table('users')
