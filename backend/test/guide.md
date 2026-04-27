# 테스트 실행 가이드

상황별 명령어만 정리. 구조/컨벤션은 [`README.md`](./README.md) 참고.

모든 명령은 `backend/` 루트에서 실행한다.

---

## A. 단위만 (가장 빠름, 외부 의존 없음)

```bash
uv run pytest test/unit
```

---

## B. Postgres 만 있는 통합까지

최초 1회 — 네이티브 Postgres 에 테스트 DB 생성:
```bash
createdb -U cho -h localhost chohyeonsang_test
```

매번 실행:
```bash
POSTGRES_TEST_URL='postgresql+asyncpg://cho:hyeonsang@localhost:5432/chohyeonsang_test' \
  uv run pytest
```

> `REDIS_TEST_URL` / `MONGODB_TEST_URL` 미설정 시 채팅 통합 3개 파일은 자동 skip.

---

## C. 채팅 전체 통합 (Redis + Mongo 추가)

smoke compose 를 재사용 — 포트는 `5532 / 6479 / 27117` 로 고정.

최초 1회 — compose 기동 + 테스트 DB 생성:
```bash
docker compose -f scripts/chat/docker-compose.smoke.yml up -d --wait
docker compose -f scripts/chat/docker-compose.smoke.yml exec -T postgres \
  psql -U cho -d postgres -c "CREATE DATABASE chohyeonsang_test;"
```

매번 실행:
```bash
POSTGRES_TEST_URL='postgresql+asyncpg://cho:hyeonsang@localhost:5532/chohyeonsang_test' \
REDIS_TEST_URL='redis://localhost:6479' \
MONGODB_TEST_URL='mongodb://cho:hyeonsang@localhost:27117/chohyeonsang_test?authSource=admin' \
  uv run pytest
```

정리:
```bash
docker compose -f scripts/chat/docker-compose.smoke.yml down -v
```

---

## 팁 — 환경변수 박아두기

매번 타이핑 싫으면 `~/.zshrc` 에 `export` 해두면 `uv run pytest` 한 줄로 끝.

```bash
export POSTGRES_TEST_URL='postgresql+asyncpg://cho:hyeonsang@localhost:5532/chohyeonsang_test'
export REDIS_TEST_URL='redis://localhost:6479'
export MONGODB_TEST_URL='mongodb://cho:hyeonsang@localhost:27117/chohyeonsang_test?authSource=admin'
```

> ⚠️ `scripts/chat/run_smoke.sh` 는 종료 시 compose 볼륨을 `down -v` 로 지운다.
> smoke 와 통합 테스트를 동시에 돌리지 말 것.
