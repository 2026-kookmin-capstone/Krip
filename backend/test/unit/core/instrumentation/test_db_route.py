"""db_route_for_path — HTTP path → DB 메트릭 route 라벨 매핑 단위 테스트.

regression: route enum 값이 실제 URL segment 와 달라야 하는데 "menu_ai"(언더스코어)로
등록돼 있어 /api/menu-ai(하이픈) 요청이 전부 "other" 로 유실됐다.
"""
import pytest

from app.core.instrumentation.db import db_route_for_path


pytestmark = pytest.mark.unit


class TestDbRouteForPath:
    def test_menu_ai_hyphen_path_maps_to_menu_ai(self):
        # 핵심 회귀 — 이전엔 "other" 로 유실됐다.
        assert db_route_for_path("/api/menu-ai/ocr") == "menu-ai"
        assert db_route_for_path("/api/menu-ai/ocr/batch") == "menu-ai"

    @pytest.mark.parametrize("domain", [
        "auth", "chat", "tour", "friend", "feed",
        "notification", "tripmate", "translation", "public",
    ])
    def test_known_domains_map_to_themselves(self, domain):
        assert db_route_for_path(f"/api/{domain}/whatever") == domain

    def test_health_paths_map_to_health(self):
        assert db_route_for_path("/health") == "health"
        assert db_route_for_path("/health/deep") == "health"
        assert db_route_for_path("/ready") == "health"

    def test_unknown_domain_maps_to_other(self):
        assert db_route_for_path("/api/unknown/x") == "other"
        assert db_route_for_path("/metrics") == "other"

    def test_underscore_variant_no_longer_matches(self):
        # 언더스코어 경로는 실제로 존재하지 않지만, 매핑이 segment 정확 대조임을 고정.
        assert db_route_for_path("/api/menu_ai/ocr") == "other"
