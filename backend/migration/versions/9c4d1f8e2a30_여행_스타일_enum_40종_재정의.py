"""여행 스타일 enum 40종 재정의

Revision ID: 9c4d1f8e2a30
Revises: e8a5c1f2b937
Create Date: 2026-05-07 00:00:00.000000

기존 user_travel_style.style enum 5개를 통째로 교체. 운영 데이터는 비움.
PG ENUM 값 제거가 어렵기 때문에 column type 을 잠시 풀고 type 자체를 재생성.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '9c4d1f8e2a30'
down_revision: Union[str, Sequence[str], None] = 'e8a5c1f2b937'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VALUES = (
    'ACTIVITY', 'FAMOUS_ATTRACTIONS', 'HEALING', 'CULTURE_HISTORY', 'SHOPPING',
    'FOOD_TOUR', 'PHOTO_AESTHETIC', 'FESTIVAL_EVENT', 'NATURE', 'TRADITIONAL',
    'TREKKING', 'HIDDEN_GEMS', 'ART_EXHIBITION', 'THEME_PARK',
    'FOOD_HALAL', 'FOOD_VEGETARIAN', 'FOODIE', 'CAFE_LOVER',
    'DENSITY_RELAXED', 'DENSITY_PACKED',
    'BUDGET_SAVING', 'BUDGET_MODERATE', 'BUDGET_PREMIUM',
    'WALKING_LOW', 'WALKING_MEDIUM', 'WALKING_HIGH',
    'TRANSPORT_PUBLIC', 'TRANSPORT_CAR', 'TRANSPORT_TAXI',
    'COMPANION_INDEPENDENT', 'COMPANION_TOGETHER', 'COMPANION_FLEXIBLE',
    'DAYTIME', 'NIGHTLIFE', 'NIGHT_VIEW',
    'COMMUNICATION_HIGH', 'COMMUNICATION_LOW',
    'PLANNER', 'SPONTANEOUS', 'FOLLOWER',
)

_OLD_VALUES = ('ACTIVITY', 'RELAXATION', 'TOURISM', 'SHOPPING', 'FOOD')


def _enum_literal(values: Sequence[str]) -> str:
    return ', '.join(f"'{v}'" for v in values)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("TRUNCATE TABLE user_travel_style")
    op.execute("ALTER TABLE user_travel_style ALTER COLUMN style TYPE VARCHAR(50)")
    op.execute("DROP TYPE travelstyle")
    op.execute(f"CREATE TYPE travelstyle AS ENUM ({_enum_literal(_NEW_VALUES)})")
    op.execute(
        "ALTER TABLE user_travel_style "
        "ALTER COLUMN style TYPE travelstyle USING style::travelstyle"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("TRUNCATE TABLE user_travel_style")
    op.execute("ALTER TABLE user_travel_style ALTER COLUMN style TYPE VARCHAR(50)")
    op.execute("DROP TYPE travelstyle")
    op.execute(f"CREATE TYPE travelstyle AS ENUM ({_enum_literal(_OLD_VALUES)})")
    op.execute(
        "ALTER TABLE user_travel_style "
        "ALTER COLUMN style TYPE travelstyle USING style::travelstyle"
    )
