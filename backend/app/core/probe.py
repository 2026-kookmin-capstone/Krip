"""k8s/LB probe 엔드포인트의 단일 정의."""

PROBE_ROUTES: frozenset[str] = frozenset({"/health", "/health/deep", "/ready"})
