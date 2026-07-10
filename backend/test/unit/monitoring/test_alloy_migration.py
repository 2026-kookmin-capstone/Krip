from pathlib import Path


ROOT = Path(__file__).parents[4]
COMPOSE = ROOT / "monitoring/docker-compose.monitoring.yml"
ALLOY_CONFIG = ROOT / "monitoring/alloy/config.alloy"
PROMETHEUS_CONFIG = ROOT / "monitoring/prometheus/prometheus.yml"
MAKEFILE = ROOT / "monitoring/Makefile"


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


def test_operational_consumers_target_alloy_health_and_metrics():
    prometheus = PROMETHEUS_CONFIG.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "promtail-self" not in prometheus
    assert 'job_name: alloy-self' in prometheus
    assert 'targets: ["alloy:12345"]' in prometheus
    assert "Promtail" not in makefile
    assert "http://alloy:12345/-/ready" in makefile
