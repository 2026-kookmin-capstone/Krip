# 테스트 가이드

Krip 백엔드의 비즈니스 로직은 **단위 테스트 + 통합 테스트** 2계층으로 검증합니다.

| 계층 | 대상 | 의존성 | 실행 속도 |
|---|---|---|---|
| **unit** | Service 로직 | 레포지토리·세션 Mock | < 1s |
| **integration** | Service → Repository → PostgreSQL | 실 DB 필요 | 수 초 |

## 현재 커버리지

| 도메인 | 단위 | 통합 | 합계 |
|---|---|---|---|
| friend | 44 | 27 | 71 |

---

## 실행 방법

```bash
# 전체 (통합은 POSTGRES_TEST_URL 미설정 시 자동 skip)
uv run pytest

# 단위 테스트만
uv run pytest test/unit/

# 통합 테스트만 (test DB 필요)
POSTGRES_TEST_URL="postgresql+asyncpg://cho:hyeonsang@localhost:5432/chohyeonsang_test" \
  uv run pytest test/integration/

# 특정 도메인
uv run pytest test/unit/domain/friend/

# 특정 서비스
uv run pytest test/unit/domain/friend/friendship_service/

# 마커 기반
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m "not slow"
```

### 통합 테스트 DB 준비

PostgreSQL 에 테스트 전용 DB 를 한 번 생성해두면 됩니다.

```bash
psql -h localhost -p 5432 -U <superuser> -d postgres \
  -c "CREATE DATABASE chohyeonsang_test OWNER cho;"
```

`POSTGRES_TEST_URL` 이 설정되지 않은 환경 (CI 의 unit 전용 잡 등) 에서는 통합 테스트가 모두 skip 되므로 안전합니다.

---

## 디렉토리 구조

```
test/
├── unit/                                      # 단위 테스트
│   ├── conftest.py                           # app.database.model 선 import (매퍼 등록)
│   └── domain/
│       └── friend/
│           ├── friendship_service/
│           │   ├── __init__.py
│           │   ├── model_factory.py          # 테스트 데이터 팩토리
│           │   ├── mock_factory.py           # UoW·Session·Repository Mock 팩토리
│           │   ├── conftest.py               # service fixture + autouse 카운터 reset
│           │   └── test_friendship_service.py
│           └── user_block_service/
│               └── ...
└── integration/                               # 통합 테스트
    ├── conftest.py                           # 실 DB engine + seed_users fixture
    └── domain/
        └── friend/
            ├── test_friendship_flow.py
            └── test_user_block_flow.py
```

### 서비스 단위 테스트 구성

```
{service_name}/
├── __init__.py
├── model_factory.py       # 도메인 객체 팩토리 (SimpleNamespace 권장, 아래 "주의사항" 참고)
├── mock_factory.py        # Repository / UoW / Session Mock 팩토리
├── conftest.py            # 서비스별 fixture
└── test_{service}.py      # 테스트 코드
```

### 통합 테스트 구성

통합 테스트는 실제 Repository + DB 를 쓰므로 별도 팩토리가 거의 필요 없습니다. `conftest.py` 의 `seed_users` fixture 로 유저만 심고, Service 를 직접 호출해 DB 상태를 검증합니다.

---

## 코드 컨벤션

### 1. 테스트 클래스 네이밍

```python
@pytest.mark.unit
class Test{MethodName}:
    """Tests for {method_name} method."""
```

**예시:**
```python
@pytest.mark.unit
class TestSendRequest:
    """Tests for FriendshipService.send_request."""
```

### 2. 테스트 메서드 네이밍

```python
async def test_{action}_{condition_or_result}(self):
```

**예시:**
```python
async def test_raises_when_sending_to_self(self): ...
async def test_creates_new_friendship_when_no_existing(self): ...
async def test_upserts_rejected_to_pending_same_direction(self): ...
```

### 3. AAA 패턴

```python
async def test_accept_updates_status(self, service, friendship_repo_mock):
    # Arrange
    friendship = FriendshipFactory.create(
        requester_id="USER_a",
        addressee_id="USER_b",
        status=FriendshipStatus.PENDING,
    )
    friendship_repo_mock.find_by_id.return_value = friendship

    # Act
    await service.accept_request(friendship_id="FS_x", user_id="USER_b")

    # Assert
    assert friendship.status == FriendshipStatus.ACCEPTED
    friendship_repo_mock.update.assert_awaited_once_with(friendship)
```

### 4. Model Factory 패턴

도메인 객체를 외부 의존성 없이 생성합니다. **SQLAlchemy 모델을 직접 인스턴스화하면 relationship 할당 시 backref 이벤트가 `_sa_instance_state` 를 요구해 에러가 나므로, 단위 테스트에서는 `SimpleNamespace` 로 속성만 흉내내는 팩토리를 권장합니다.**

```python
class FriendshipFactory:
    _counter = 0

    @classmethod
    def create(
        cls,
        friendship_id: Optional[str] = None,
        requester_id: str = "USER_req",
        addressee_id: str = "USER_addr",
        status: FriendshipStatus = FriendshipStatus.PENDING,
        ...
    ) -> SimpleNamespace:
        cls._counter += 1
        return SimpleNamespace(
            friendship_id=friendship_id or f"FS_test_{cls._counter:04d}",
            requester_id=requester_id,
            addressee_id=addressee_id,
            status=status,
            ...
        )

    @classmethod
    def reset_counter(cls) -> None:
        cls._counter = 0
```

### 5. Mock Factory 패턴

Repository · UoW · Session 을 모두 Mock 으로 대체합니다.

```python
class FakeUnitOfWork:
    """@transactional 이 쓰는 async with self.uow as session 을 만족."""
    def __init__(self, session):
        self._session = session
    async def __aenter__(self): return self._session
    async def __aexit__(self, *exc): return False


def make_mock_session() -> MagicMock:
    session = MagicMock(name="session")
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.begin_nested = MagicMock(return_value=FakeAsyncContextManager())
    return session


class FriendshipRepositoryMockFactory:
    @classmethod
    def create(cls) -> AsyncMock:
        mock = AsyncMock()
        mock.find_by_id.return_value = None
        mock.find_between.return_value = None
        ...
        return mock
```

### 6. Service fixture (monkeypatch)

서비스 내부에서 `self._session` 으로 레포지토리를 생성하기 때문에, 서비스 모듈 레벨 클래스를 `monkeypatch` 로 Mock 생성자로 치환합니다.

```python
@pytest.fixture
def service(monkeypatch, mock_session, friendship_repo_mock, block_repo_mock, user_repo_mock):
    monkeypatch.setattr(
        "app.domain.friend.service.friendship.FriendshipRepository",
        lambda session: friendship_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.friend.service.friendship.UserBlockRepository",
        lambda session: block_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.friend.service.friendship.UserRepository",
        lambda session: user_repo_mock,
    )
    return FriendshipService(uow=FakeUnitOfWork(mock_session))
```

### 7. Fixture 활용 (autouse)

```python
@pytest.fixture(autouse=True)
def reset_factories():
    FriendshipFactory.reset_counter()
    UserBlockFactory.reset_counter()
    UserFactory.reset_counter()
    yield
    FriendshipFactory.reset_counter()
    UserBlockFactory.reset_counter()
    UserFactory.reset_counter()
```

### 8. 테스트 마커

```python
@pytest.mark.unit           # 단위 테스트
@pytest.mark.integration    # 통합 테스트
@pytest.mark.slow           # 느린 테스트
# @pytest.mark.asyncio 는 asyncio_mode="auto" 로 자동 적용됨
```

---

## 통합 테스트 특이사항

### function-scope engine + `NullPool`

`asyncpg` + `pytest-asyncio 1.x` 조합에서 session-scope async fixture 는 event loop 격리 문제를 일으킵니다. 따라서 통합 테스트의 `engine` fixture 는 **function-scope 로 두고 `NullPool` 을 사용**해 매 테스트마다 스키마를 drop/create 합니다. 속도보다 신뢰성 우선.

```python
@pytest_asyncio.fixture
async def engine():
    url = _require_test_db_url()
    engine = create_async_engine(url, echo=False, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
```

### `seed_users` 팩토리 fixture

FK 제약(`friendship.requester_id → users.user_id`)을 충족하려면 테스트 시작 시 유저를 먼저 심어야 합니다.

```python
@pytest_asyncio.fixture
async def seed_users(session_factory):
    async def _seed(count: int = 3) -> list[str]:
        ...  # User + UserDetailInform N 건 insert
        return user_ids
    return _seed


# 사용
async def test_xxx(uow, seed_users):
    a, b, c = await seed_users(3)
    service = FriendshipService(uow=uow)
    await service.send_request(requester_id=a, addressee_id=b)
```

---

## pytest 설정 (pyproject.toml)

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["test/unit", "test/integration"]
asyncio_mode = "auto"
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: marks tests as unit tests",
    "integration: marks tests as integration tests",
    "slow: marks tests as slow running",
]
```

---

## 테스트 작성 체크리스트

### 새 서비스 단위 테스트 추가 시

1. 디렉토리 생성
   ```bash
   mkdir -p test/unit/domain/{domain}/{service_name}
   ```
2. 필수 파일
   - `__init__.py`
   - `model_factory.py` — 도메인 객체 팩토리 (SimpleNamespace 기반)
   - `mock_factory.py` — UoW / Session / Repository Mock 팩토리
   - `conftest.py` — service fixture + autouse 카운터 reset
   - `test_{service}.py`

### 새 서비스 통합 테스트 추가 시

1. `test/integration/domain/{domain}/test_{flow}.py` 생성
2. `pytestmark = pytest.mark.integration` 로 마커 지정
3. `uow`, `seed_users`, `session_factory` fixture 조합해 실 DB 플로우 검증

### 커버리지 기준

- 모든 public 메서드 테스트
- 정상 케이스 + 예외 케이스 (권한·상태·검증 실패)
- 경계값 (빈 목록, 페이지 full, 커서)
- Mock / 실 DB 로 의존성 격리

---

## 주의사항

1. **SQLAlchemy 매퍼 등록**: `test/unit/conftest.py` 에서 `app.database.model` 을 import 해 모든 ORM 모델을 먼저 등록합니다 (relationship 문자열 해결).
2. **SimpleNamespace 팩토리**: SQLAlchemy 모델 인스턴스를 직접 만들면 backref 이벤트가 `_sa_instance_state` 를 요구해 실패합니다. 단위 테스트에선 반드시 `SimpleNamespace` 로 감쌉니다.
3. **Mock session 메서드**: 서비스가 `self._session.flush / refresh / begin_nested` 를 쓰므로 Mock 에 세 메서드를 모두 등록해야 합니다.
4. **Factory Counter 초기화**: `autouse=True` fixture 로 테스트 간 독립성 보장.
5. **비동기 테스트**: `asyncio_mode = "auto"` 로 `@pytest.mark.asyncio` 자동 적용.
6. **통합 테스트 DB 격리**: 매 테스트마다 drop/create. TRUNCATE 보다 느리지만 enum·index 변경도 완전 반영.
