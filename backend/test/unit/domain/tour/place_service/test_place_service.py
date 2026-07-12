"""PlaceService — 거리순 장소 조회 + 즐겨찾기 합성 단위 테스트.

검증 대상:
    - `get_nearby_places`: 정상 반환, 빈 결과, next_cursor 합성, 즐겨찾기 매핑, user_id 빈 문자열
    - `get_place_by_id`: 정상, 미존재 None
    - `search_nearby_places`: keyword 전달
"""
import pytest

from app.domain.tour.repository.place import PAGE_SIZE, PlaceRepository
from test.unit.domain.tour.place_service.model_factory import PlaceRawFactory


@pytest.mark.unit
class TestGetNearbyPlaces:
    """Tests for PlaceService.get_nearby_places."""

    async def test_returns_empty_when_no_places(
        self, service, place_repo_mock, fav_repo_mock,
    ):
        place_repo_mock.find_nearby.return_value = []

        result = await service.get_nearby_places(lat=37.5, lng=127.0, user_id="USER_a")

        assert result.places == []
        assert result.next_cursor is None
        fav_repo_mock.find_favorited_place_ids.assert_not_awaited()

    async def test_returns_places_with_distance_and_favorite(
        self, service, place_repo_mock, fav_repo_mock,
    ):
        """즐겨찾기 매핑 — favorited set 안에 있으면 is_favorite=True."""
        place_repo_mock.find_nearby.return_value = [
            PlaceRawFactory.create(place_id="PLACE_1", distance=50.0),
            PlaceRawFactory.create(place_id="PLACE_2", distance=200.0),
        ]
        fav_repo_mock.find_favorited_place_ids.return_value = {"PLACE_1"}

        result = await service.get_nearby_places(
            lat=37.5, lng=127.0, user_id="USER_a",
        )

        assert len(result.places) == 2
        assert result.places[0].place_id == "PLACE_1"
        assert result.places[0].is_favorite is True
        assert result.places[0].distance == 50.0
        assert result.places[1].is_favorite is None

    async def test_no_favorited_when_user_id_empty(
        self, service, place_repo_mock, fav_repo_mock,
    ):
        """user_id 빈 문자열 (비로그인) → favorited 조회 skip."""
        place_repo_mock.find_nearby.return_value = [PlaceRawFactory.create()]

        result = await service.get_nearby_places(lat=37.5, lng=127.0, user_id="")

        fav_repo_mock.find_favorited_place_ids.assert_not_awaited()
        assert result.places[0].is_favorite is None

    async def test_no_next_cursor_when_partial_page(
        self, service, place_repo_mock,
    ):
        """fetch < PAGE_SIZE → 다음 페이지 없음."""
        place_repo_mock.find_nearby.return_value = [
            PlaceRawFactory.create() for _ in range(PAGE_SIZE - 1)
        ]

        result = await service.get_nearby_places(lat=37.5, lng=127.0, user_id="")

        assert result.next_cursor is None

    async def test_no_next_cursor_when_exact_page(self, service, place_repo_mock):
        """fetch == PAGE_SIZE → 초과 row가 없으므로 마지막 페이지."""
        places = [
            PlaceRawFactory.create(place_id=f"PLACE_{i}", distance=float(i))
            for i in range(PAGE_SIZE)
        ]
        place_repo_mock.find_nearby.return_value = places

        result = await service.get_nearby_places(lat=37.5, lng=127.0, user_id="")

        assert len(result.places) == PAGE_SIZE
        assert result.next_cursor is None

    async def test_next_cursor_when_page_overflows(self, service, place_repo_mock):
        places = [
            PlaceRawFactory.create(place_id=f"PLACE_{i}", distance=float(i))
            for i in range(PAGE_SIZE + 1)
        ]
        place_repo_mock.find_nearby.return_value = places

        result = await service.get_nearby_places(lat=37.5, lng=127.0, user_id="")

        assert len(result.places) == PAGE_SIZE
        from app.domain.tour.repository.place import PlaceRepository
        expected = PlaceRepository.build_cursor(
            float(PAGE_SIZE - 1), f"PLACE_{PAGE_SIZE - 1}",
        )
        assert result.next_cursor == expected
        assert place_repo_mock.find_nearby.await_args.kwargs["limit"] == PAGE_SIZE + 1


@pytest.mark.unit
class TestGetPlaceById:
    """Tests for PlaceService.get_place_by_id."""

    async def test_returns_dto_when_place_exists(
        self, service, place_repo_mock,
    ):
        place_repo_mock.find_by_place_id.return_value = PlaceRawFactory.create(
            place_id="PLACE_x", display_name="Custom",
        )

        result = await service.get_place_by_id(place_id="PLACE_x", user_id="")

        assert result is not None
        assert result.place_id == "PLACE_x"
        assert result.display_name == "Custom"

    async def test_returns_none_when_not_found(self, service, place_repo_mock):
        """미존재 → None (router 가 404 매핑)."""
        place_repo_mock.find_by_place_id.return_value = None

        result = await service.get_place_by_id(place_id="PLACE_x", user_id="USER_a")

        assert result is None


@pytest.mark.unit
class TestSearchNearbyPlaces:
    """Tests for PlaceService.search_nearby_places."""

    async def test_passes_keyword_and_filters_to_repo(
        self, service, place_repo_mock,
    ):
        place_repo_mock.search_nearby.return_value = []

        await service.search_nearby_places(
            lat=37.5, lng=127.0, keyword="피자", cursor="abc", max_distance=500.0,
            user_id="USER_a",
        )

        place_repo_mock.search_nearby.assert_awaited_once_with(
            37.5, 127.0, "피자", cursor="abc", max_distance=500.0,
            limit=PAGE_SIZE + 1,
        )

    async def test_exact_and_overflow_cursor_boundaries(self, service, place_repo_mock):
        exact = [
            PlaceRawFactory.create(place_id=f"PLACE_{i}", distance=float(i))
            for i in range(PAGE_SIZE)
        ]
        place_repo_mock.search_nearby.return_value = exact
        result = await service.search_nearby_places(37.5, 127.0, "피자")
        assert len(result.places) == PAGE_SIZE
        assert result.next_cursor is None

        place_repo_mock.search_nearby.return_value = exact + [
            PlaceRawFactory.create(place_id="PLACE_extra", distance=float(PAGE_SIZE)),
        ]
        result = await service.search_nearby_places(37.5, 127.0, "피자")
        assert len(result.places) == PAGE_SIZE
        expected = PlaceRepository.build_cursor(
            float(PAGE_SIZE - 1), f"PLACE_{PAGE_SIZE - 1}",
        )
        assert result.next_cursor == expected
