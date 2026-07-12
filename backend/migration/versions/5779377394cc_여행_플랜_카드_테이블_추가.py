"""여행 플랜 카드 테이블 추가

Revision ID: 5779377394cc
Revises: c4f1a8b2d6e3
Create Date: 2026-05-01 03:55:07.501955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5779377394cc'
down_revision: Union[str, Sequence[str], None] = 'c4f1a8b2d6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tour_plan',
    sa.Column('plan_id', sa.String(length=50), nullable=False),
    sa.Column('user_id', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=True),
    sa.Column('travel_days', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('travel_days >= 1', name='ck_tour_plan_travel_days_min'),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('plan_id')
    )
    op.create_index('ix_tour_plan_user_id', 'tour_plan', ['user_id'], unique=False)
    op.create_table('tour_plan_item',
    sa.Column('item_id', sa.String(length=50), nullable=False),
    sa.Column('plan_id', sa.String(length=50), nullable=False),
    sa.Column('day_number', sa.Integer(), nullable=False),
    sa.Column('position', sa.Float(), nullable=False),
    sa.Column('place_id', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('address', sa.String(length=500), nullable=False),
    sa.Column('visit_time', sa.String(length=5), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('day_number >= 1', name='ck_tour_plan_item_day_min'),
    sa.ForeignKeyConstraint(['plan_id'], ['tour_plan.plan_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('item_id'),
    sa.UniqueConstraint('plan_id', 'day_number', 'position', name='uq_tour_plan_item_position')
    )
    op.create_index('ix_tour_plan_item_place_id', 'tour_plan_item', ['place_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tour_plan_item_place_id', table_name='tour_plan_item')
    op.drop_table('tour_plan_item')
    op.drop_index('ix_tour_plan_user_id', table_name='tour_plan')
    op.drop_table('tour_plan')
