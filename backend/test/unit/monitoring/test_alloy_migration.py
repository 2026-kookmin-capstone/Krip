import json
import subprocess
from io import StringIO
from pathlib import Path

from loguru import logger


ROOT = Path(__file__).parents[4]
COMPOSE = ROOT / "monitoring/docker-compose.monitoring.yml"
ALLOY_CONFIG = ROOT / "monitoring/alloy/config.alloy"
PROMETHEUS_CONFIG = ROOT / "monitoring/prometheus/prometheus.yml"
MAKEFILE = ROOT / "monitoring/Makefile"
WORKERS_DASHBOARD = ROOT / "monitoring/grafana/provisioning/dashboards/workers.json"
BACKEND_LOGS_DASHBOARD = (
    ROOT / "monitoring/grafana/provisioning/dashboards/backend-logs.json"
)
DASHBOARD_DIR = ROOT / "monitoring/grafana/provisioning/dashboards"
MONITORING_README = ROOT / "monitoring/README.md"
CHAT_DASHBOARD = ROOT / "monitoring/grafana/provisioning/dashboards/chat-domain.json"
CHAT_METRIC = ROOT / "backend/app/core/metric/chat.py"
CHAT_INSTRUMENTATION = ROOT / "backend/app/core/instrumentation/chat.py"


def test_compose_uses_supported_alloy_collector():
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "grafana/promtail" not in compose
    assert "\n  promtail:" not in compose
    assert "alloy:" in compose
    assert "grafana/alloy:v1.17.1" in compose
    assert "/etc/alloy/config.alloy" in compose
    assert "alloy-data:/var/lib/alloy/data" in compose
    # promtail cutover 브릿지 잔재가 되살아나지 않도록 가드.
    assert "promtail" not in compose
    assert "/var/lib/promtail" not in compose


def test_alloy_pipeline_preserves_collection_and_privacy_contract():
    config = ALLOY_CONFIG.read_text(encoding="utf-8")

    assert config.count('loki.process "backend"') == 1
    assert 'loki.source.file "current"' in config
    assert 'loki.source.file "rotated"' in config
    assert '"/backend/logs/app.log"' in config
    assert '"/backend/logs/app.*.log.gz"' in config
    assert "decompression {" in config
    assert 'format  = "gz"' in config
    assert 'source = "timestamp"' in config
    assert 'format = "2006-01-02 15:04:05.999999-07:00"' in config
    assert config.count("stage.replace {") == 4
    assert 'replace    = "<email>"' in config
    assert 'replace    = "<jwt>"' in config
    assert 'replace    = "<phone>"' in config
    assert 'replace    = "<rrn>"' in config
    assert "stage.label_drop {" in config
    assert 'values = ["filename"]' in config
    # legacy promtail offset 브릿지는 clean 배포에서 완전히 제거됨.
    assert "legacy_positions_file" not in config
    assert "promtail" not in config
    assert config.count("stage.labels {") == 1
    assert 'level = null' in config
    assert 'env         = sys.env("ENV")' in config
    assert 'node_id     = sys.env("NODE_ID")' in config
    assert 'url       = sys.env("LOKI_URL")' in config


def test_loguru_schema_matches_alloy_and_dashboard_contract():
    output = StringIO()
    sink_id = logger.add(output, serialize=True)
    try:
        logger.bind(
            event="http_client_error",
            logger_name="schema.fixture",
            method="GET",
            path="/api/items/{item_id}",
            request_id="RID_SCHEMA",
            route="/api/items/{item_id}",
            status_code=404,
            user_id=None,
            validation_errors="body.age: int_parsing",
        ).warning("HTTP client error response")
    finally:
        logger.remove(sink_id)

    record = json.loads(output.getvalue())
    extra = record["record"]["extra"]
    assert record["record"]["level"]["name"] == "WARNING"
    assert record["record"]["message"] == "HTTP client error response"
    assert set(extra) >= {
        "event", "logger_name", "method", "path", "request_id", "route",
        "status_code", "user_id",
    }

    config = ALLOY_CONFIG.read_text(encoding="utf-8")
    for field in extra:
        assert f"record.extra.{field}" in config

    dashboard = json.loads(BACKEND_LOGS_DASHBOARD.read_text(encoding="utf-8"))
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == 3)
    expression = panel["targets"][0]["expr"]
    assert 'level="WARNING"' in expression
    assert 'event="record.extra.event"' in expression
    assert 'event="http_client_error"' in expression


def test_success_schema_matches_alloy_contract():
    output = StringIO()
    sink_id = logger.add(output, serialize=True)
    try:
        logger.bind(
            event="http_success",
            logger_name="schema.fixture",
            method="GET",
            path="/api/items/{item_id}",
            process_time=0.012,
            request_id="RID_SCHEMA",
            route="/api/items/{item_id}",
            status_code=200,
            user_id=None,
        ).info("HTTP request completed")
    finally:
        logger.remove(sink_id)

    record = json.loads(output.getvalue())["record"]
    extra = record["extra"]
    assert record["level"]["name"] == "INFO"
    assert record["message"] == "HTTP request completed"

    config = ALLOY_CONFIG.read_text(encoding="utf-8")
    for field in extra:
        assert f"record.extra.{field}" in config


def test_server_error_schema_matches_alloy_and_dashboard_contract():
    output = StringIO()
    sink_id = logger.add(output, serialize=True)
    try:
        logger.bind(
            event="http_server_error",
            logger_name="schema.fixture",
            method="POST",
            path="/api/items/{item_id}",
            request_id="RID_SCHEMA",
            route="/api/items/{item_id}",
            status_code=500,
            user_id=None,
            error_type="RuntimeError",
            error_location="app.domain.items:create",
            error_line=42,
        ).error("HTTP server error response")
    finally:
        logger.remove(sink_id)

    record = json.loads(output.getvalue())["record"]
    extra = record["extra"]
    assert record["level"]["name"] == "ERROR"
    assert record["message"] == "HTTP server error response"

    config = ALLOY_CONFIG.read_text(encoding="utf-8")
    for field in extra:
        assert f"record.extra.{field}" in config

    dashboard_text = BACKEND_LOGS_DASHBOARD.read_text(encoding="utf-8")
    dashboard = json.loads(dashboard_text)
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == 4)
    expression = panel["targets"][0]["expr"]
    assert panel["title"] == "HTTP 5xx"
    assert 'level="ERROR"' in expression
    assert 'event="record.extra.event"' in expression
    assert 'event="http_server_error"' in expression
    assert "traceback" not in dashboard_text.lower()


def test_readme_dashboard_inventory_matches_provisioned_json():
    readme = MONITORING_README.read_text(encoding="utf-8")
    rows = {
        cells[0].strip(" `"): int(cells[2].strip())
        for line in readme.splitlines()
        if line.startswith("| `krip-")
        for cells in [line.strip("|").split("|")]
        if len(cells) == 4 and cells[2].strip().isdigit()
    }
    expected = {
        dashboard["uid"]: len(dashboard.get("panels", []))
        for path in DASHBOARD_DIR.glob("*.json")
        for dashboard in [json.loads(path.read_text(encoding="utf-8"))]
    }
    assert rows == expected


def test_five_xx_ratio_preserves_low_traffic_error_rate():
    for name in ("api-overview.json", "krip-overview.json"):
        dashboard = json.loads((DASHBOARD_DIR / name).read_text(encoding="utf-8"))
        panel = next(panel for panel in dashboard["panels"] if "5xx" in panel["title"])
        expression = panel["targets"][0]["expr"]

        assert "clamp_min" not in expression
        assert "unless" in expression
        assert "or vector(0)" in expression


def test_rollback_ratio_preserves_low_traffic_error_rate():
    dashboard = json.loads(
        (DASHBOARD_DIR / "infra-stores.json").read_text(encoding="utf-8")
    )
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == 4)
    expression = panel["targets"][0]["expr"]

    assert "clamp_min" not in expression
    assert "unless" in expression
    assert "or vector(0)" in expression


def test_operational_consumers_target_alloy_health_and_metrics():
    prometheus = PROMETHEUS_CONFIG.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "promtail-self" not in prometheus
    assert 'job_name: alloy-self' in prometheus
    assert 'targets: ["alloy:12345"]' in prometheus
    assert "Promtail" not in makefile
    assert "http://alloy:12345/-/ready" in makefile


def test_up_build_rebuilds_backend_then_starts_full_stack():
    result = subprocess.run(
        ["make", "-n", "up-build"],
        cwd=MAKEFILE.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    compose_commands = [
        line for line in result.stdout.splitlines()
        if line.startswith("docker-compose ")
    ]

    assert len(compose_commands) == 2
    assert compose_commands[0].endswith(" build backend")
    assert compose_commands[1].endswith(" up -d")


def test_worker_liveness_panels_use_worst_node_tick():
    dashboard = json.loads(WORKERS_DASHBOARD.read_text(encoding="utf-8"))
    expected = {
        1: "reconcile",
        2: "node_heartbeat",
        3: "fanout_dispatch",
        4: "withdraw_purge",
        5: "pending_recovery",
    }

    for panel_id, worker in expected.items():
        panel = next(panel for panel in dashboard["panels"] if panel["id"] == panel_id)
        expr = panel["targets"][0]["expr"]
        assert f'min(worker_last_tick_timestamp{{worker="{worker}"}})' in expr
        assert "max(worker_last_tick_timestamp" not in expr


def test_reconcile_observability_describes_lease_claim_protocol():
    dashboard = CHAT_DASHBOARD.read_text(encoding="utf-8")
    metric = CHAT_METRIC.read_text(encoding="utf-8")
    instrumentation = CHAT_INSTRUMENTATION.read_text(encoding="utf-8")

    combined = dashboard + metric + instrumentation
    assert "lease-claim" in combined
    assert "processing lease" in combined
    assert "batch pop" not in combined
    assert "재적재" not in combined
