#!/usr/bin/env bash
# 채팅 Phase 1 E2E smoke runner.
#
# 사용법:
#   cd backend
#   ./scripts/chat/run_smoke.sh
#
# 단계:
#   1) docker compose up  (postgres / redis / mongo, healthcheck 대기)
#   2) .env.smoke 를 export 후 alembic 마이그레이션
#   3) 테스트 유저 2명 DB 시드
#   4) FastAPI 서버를 백그라운드로 기동 → /docs 헬스체크
#   5) Python E2E (smoke_test.py) 실행
#   6) 종료 시 FastAPI kill + docker compose down -v
#
# 환경변수:
#   KEEP_STACK=1  테스트 후에도 컨테이너/서버 유지 (디버깅용)
#   VERBOSE=1     FastAPI 로그를 stdout 으로 직접 출력

set -euo pipefail

cd "$(dirname "$0")/../.."  # → backend/ 루트

ENV_FILE=scripts/chat/.env.smoke
COMPOSE_FILE=scripts/chat/docker-compose.smoke.yml
LOG_DIR=scripts/chat/.logs

# `python scripts/chat/*.py` 실행 시 sys.path 에 스크립트 디렉토리가 들어가므로
# backend/ 를 명시적으로 얹어야 `import app.*` 가 해석된다. uvicorn 은 자체적으로
# cwd 를 sys.path 에 넣어 문제 없지만 일관성 위해 함께 export.
export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$LOG_DIR"

# ─────────────────── 정리 핸들러 ───────────────────
APP_PID=""

cleanup() {
  local exit_code=$?
  set +e
  echo
  echo "── cleanup ──"

  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    echo "  FastAPI (PID=$APP_PID) 종료"
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi

  if [[ "${KEEP_STACK:-0}" != "1" ]]; then
    echo "  docker compose down -v"
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
  else
    echo "  KEEP_STACK=1 — 컨테이너 유지 (docker compose -f $COMPOSE_FILE ps)"
  fi

  exit "$exit_code"
}
trap cleanup EXIT INT TERM


# ─────────────────── 1) docker compose up ───────────────────
echo "[1/5] docker compose up (postgres + redis + mongo)..."
docker compose -f "$COMPOSE_FILE" up -d --wait
echo "      ready"

# ─────────────────── 2) env + alembic ───────────────────
echo "[2/5] alembic upgrade head..."
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
alembic upgrade head >"$LOG_DIR/alembic.log" 2>&1 || {
  echo "FAIL: alembic 실패 — $LOG_DIR/alembic.log 확인"
  tail -40 "$LOG_DIR/alembic.log"
  exit 1
}
echo "      done"

# ─────────────────── 3) seed users ───────────────────
echo "[3/5] seed test users..."
python scripts/chat/seed_users.py

# ─────────────────── 4) FastAPI 기동 ───────────────────
echo "[4/5] start FastAPI (uvicorn)..."
if [[ "${VERBOSE:-0}" == "1" ]]; then
  uvicorn app.main:app --host 127.0.0.1 --port 8100 --log-level info &
else
  uvicorn app.main:app --host 127.0.0.1 --port 8100 --log-level info \
    >"$LOG_DIR/uvicorn.log" 2>&1 &
fi
APP_PID=$!
echo "      PID=$APP_PID"

# /docs health 대기 (최대 20초)
for i in {1..40}; do
  if curl -fsS "http://127.0.0.1:8100/docs" >/dev/null 2>&1; then
    echo "      health OK ($i/40)"
    break
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "FAIL: FastAPI 기동 실패 — $LOG_DIR/uvicorn.log 확인"
    tail -40 "$LOG_DIR/uvicorn.log" 2>/dev/null || true
    exit 1
  fi
  sleep 0.5
done

# ─────────────────── 5) smoke test ───────────────────
echo "[5/5] run smoke_test.py..."
python scripts/chat/smoke_test.py
