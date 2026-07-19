from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.main import app, create_app


def _instrumentation_count(application) -> int:
    middleware = next(
        item
        for item in application.user_middleware
        if item.cls.__name__ == "PrometheusInstrumentatorMiddleware"
    )
    return len(middleware.kwargs["instrumentations"])


def test_create_app_reuses_all_prometheus_instrumentations():
    assert _instrumentation_count(app) == 4
    assert _instrumentation_count(create_app()) == 4
    assert _instrumentation_count(create_app()) == 4


def test_factory_app_updates_shared_request_counter():
    labels = {"handler": "none", "method": "GET", "status": "401"}
    before = REGISTRY.get_sample_value("http_requests_total", labels) or 0

    response = TestClient(create_app()).get("/definitely-missing")

    after = REGISTRY.get_sample_value("http_requests_total", labels) or 0
    assert response.status_code == 401
    assert after == before + 1
