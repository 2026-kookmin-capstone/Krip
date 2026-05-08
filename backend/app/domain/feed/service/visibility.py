"""피드 가시성 결정 — 순수 함수.

본 모듈은 DB / 외부 의존이 0. (viewer, owner, image_visibility, is_friend, is_blocked) 5
입력만으로 "보여줘도 되는가" 를 결정한다. service 레이어가 (block_repo, friend_repo) 결과를
합성해 본 함수를 호출 — 단위 테스트 친화 + 규칙 단일 진입점 (`_resolve_viewer_visibilities`
도 본 함수를 enum 에 대해 iterate 해서 visibilities 부분집합을 만든다).

규칙 매트릭스:

    is_blocked | viewer == owner | image_visibility | is_friend | result
    -----------+-----------------+------------------+-----------+--------
    True       | *               | *                | *         | False    (차단 우선)
    False      | True            | *                | *         | True     (본인은 모든 visibility)
    False      | False           | PUBLIC           | *         | True
    False      | False           | FRIENDS          | True      | True
    False      | False           | FRIENDS          | False     | False
    False      | False           | PRIVATE          | *         | False
"""
from app.domain.feed.model.feed_post import FeedVisibility


def can_view(
    *,
    viewer_id: str,
    owner_id: str,
    image_visibility: FeedVisibility,
    is_friend: bool,
    is_blocked_either_way: bool,
) -> bool:
    """주어진 관계에서 viewer 가 image 를 볼 수 있는지 판정.

    호출 패턴:
        - 단건 (`get_post_for_viewer` — 후속) : 한 visibility 에 대해 단발 호출
        - 목록 (`_resolve_viewer_visibilities`) : enum 에 대해 iterate 해 IN-list 구성

    인자는 keyword-only — 위치 인자 swap (viewer↔owner) 같은 미묘한 버그를 차단.
    """
    if is_blocked_either_way:
        return False
    if viewer_id == owner_id:
        return True
    if image_visibility == FeedVisibility.PUBLIC:
        return True
    if image_visibility == FeedVisibility.FRIENDS and is_friend:
        return True
    return False
