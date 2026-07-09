from typing import Optional
from sqlalchemy.orm import contains_eager, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.domain.friend.model.user_block import UserBlock
from app.domain.auth.model.user_detail_inform import UserDetailInform
from app.domain.auth.model.user import User, UserStatus
from app.util.cursor import decode_cursor, keyset_where


# 검색 결과 페이지 크기
PAGE_SIZE = 30


class FriendSearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Read (검색 — 커서 페이지네이션) ────────────────────

    async def search_active_users(
        self,
        viewer_id: str,
        keyword: str,
        cursor: Optional[str] = None,
    ) -> list[User]:
        """`viewer_id` 기준 친구 추가 후보 ACTIVE 유저 검색.

        - 매칭: `user_id` 또는 `user_detail_inform.user_name` 부분일치 (ILIKE)
        - 본인 / 내가 차단 / 나를 차단한 유저 제외
        - 정렬: 가입 최신순 (created_at DESC, user_id DESC)
        - detail 미존재(2차 회원가입 미완료) 유저는 INNER JOIN 으로 자연 제외
          — 검색 결과는 `user_name` 표시가 필수이므로 detail 없는 유저는 노출 X
        - detail (1:1) 은 필터용 join 을 그대로 재사용해 `contains_eager` 로 로드
          → user_detail_inform 으로의 join 은 1번만 발생
        - travel_styles 는 1:N 이라 joinedload + LIMIT 의 cardinality 충돌을 피해
          `selectinload` 로 별도 IN 쿼리 로드
        """
        # `\` 를 먼저 이스케이프해야 뒤의 `\%`/`\_` 가 깨지지 않는다. 끝의 `\` 하나만으로도
        # 패턴이 escape 문자로 끝나 오검색/DB 에러가 나므로 순서가 중요.
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_pattern = f"%{escaped}%"

        blocked_by_me = (
            select(UserBlock.blocked_id).where(UserBlock.blocker_id == viewer_id)
        )
        blocked_me = (
            select(UserBlock.blocker_id).where(UserBlock.blocked_id == viewer_id)
        )

        stmt = (
            select(User)
            .join(User.detail)
            .options(
                contains_eager(User.detail),
                selectinload(User.travel_styles),
            )
            .where(
                User.user_id != viewer_id,
                User.status == UserStatus.ACTIVE,
                User.user_id.notin_(blocked_by_me),
                User.user_id.notin_(blocked_me),
                or_(
                    User.user_id.ilike(like_pattern, escape="\\"),
                    UserDetailInform.user_name.ilike(like_pattern, escape="\\"),
                ),
            )
        )

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded is None:
                raise ValueError("유효하지 않은 커서입니다.")
            cur_ts, cur_id = decoded
            stmt = stmt.where(keyset_where(
                User.created_at, User.user_id, cur_ts, cur_id,
            ))

        stmt = stmt.order_by(User.created_at.desc(), User.user_id.desc()).limit(PAGE_SIZE)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())
