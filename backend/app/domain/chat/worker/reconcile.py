"""채팅 백그라운드 reconcile / recover.

- `reconcile_last_message_once`: 5분 주기로 `dirty:chat_room` SET 을 소진하며
  `chat_room.last_message_*` 역정규화 필드를 Mongo 진실값으로 수렴.
- `recover_unread_for_user`: WS 재접속 시 `unread:{uid}` HASH 가 비면 RDB `last_read_*` +
  Mongo 메시지 수로 재계산. Redis flush/장애 후 복구 경로.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections import deque
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    DIRTY_CHAT_ROOM_DEFERRED_KEY,
    DIRTY_CHAT_ROOM_KEY,
    DIRTY_CHAT_ROOM_PROCESSING_KEY,
    DIRTY_CHAT_ROOM_PROCESSING_OWNER_KEY,
    ROOM_PENDING_MESSAGE_PREFIX,
    read_sync_key,
    room_members_gen_key,
    unread_key,
)
from app.core.instrumentation import (
    chat_reconcile_batch_pop_inc,
    chat_reconcile_dirty_set_size_set,
    chat_reconcile_rooms_processed_inc,
    chat_reconcile_tick,
    chat_unread_recover_inc,
    worker_tick,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client, get_redis_dedupe_client
from app.database.session import mongodb
from app.domain.chat.constants import UNREAD_COUNT_CAP, UNREAD_COUNT_LIMIT
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.message import (
    _clear_pending_message,
    _recover_pending_message,
)


logger = get_logger("chat.reconcile")


# 너무 크면 Mongo aggregate 페이로드 비대 + tick 길어져 shutdown 반응 느려짐.
RECONCILE_BATCH_SIZE = 500
RECONCILE_CLAIM_LEASE_MS = 60_000
RECONCILE_MAX_BATCHES_PER_TICK = 20
PENDING_SWEEP_BATCH_SIZE = 100
PENDING_SCAN_MAX_CALLS_PER_TICK = 100
PENDING_RECOVERY_MAX_ROOMS_PER_TICK = 5
PENDING_RECOVERY_CANCEL_AFTER_SEC = 5.0
PENDING_DISCOVERY_BACKLOG_LIMIT = 100

# alarm SLO 15분보다 충분히 짧게. env 로 override (smoke/개발에서 1~2초로 줄임).
RECONCILE_INTERVAL_SEC = int(os.getenv("CHAT_RECONCILE_INTERVAL_SEC", "300"))
PENDING_RECOVERY_INTERVAL_SEC = int(
    os.getenv("CHAT_PENDING_RECOVERY_INTERVAL_SEC", "5"),
)

RECONCILE_SHUTDOWN_GRACE_SEC = 10.0

# 재접속당 방 수십 개 × 동시 재접속이면 Mongo 부하 폭주 — semaphore 로 제한.
UNREAD_MONGO_CONCURRENCY = 10


# main.py lifespan 에서 1회 주입.
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

_reconcile_task: Optional[asyncio.Task] = None
_pending_recovery_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_pending_scan_cursor = 0
_pending_key_backlog: deque[str] = deque()
_pending_key_backlog_set: set[str] = set()
_pending_page_offset = 0


class PendingRecoveryBatchError(RuntimeError):
    pass


def _require_factory() -> async_sessionmaker[AsyncSession]:
    """lifespan 초기화 전 호출 시 즉시 실패."""
    if _session_factory is None:
        raise RuntimeError(
            "chat reconcile 워커가 초기화되지 않았습니다. "
            "main.py lifespan 에서 start_reconcile_scheduler(session_factory) 를 먼저 호출하세요.",
        )
    return _session_factory


def _as_room_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, set, tuple)):
        return list(value)
    return [value]


async def _claim_dirty_rooms(redis_hot, claim_token: str) -> tuple[list[str], bool]:
    """dirty room 한 배치를 lease token으로 원자 claim한다."""
    script = lua_scripts.claim_dirty_rooms
    if script is None:
        raise RuntimeError("claim_dirty_rooms Lua script가 로드되지 않았습니다.")
    result = _as_room_list(await script(
        keys=[
            DIRTY_CHAT_ROOM_KEY,
            DIRTY_CHAT_ROOM_PROCESSING_KEY,
            DIRTY_CHAT_ROOM_PROCESSING_OWNER_KEY,
            DIRTY_CHAT_ROOM_DEFERRED_KEY,
        ],
        args=[RECONCILE_BATCH_SIZE, RECONCILE_CLAIM_LEASE_MS, claim_token],
    ))
    if not result:
        return [], False
    return result[1:], bool(int(result[0]))


async def _ack_dirty_rooms(claim_token: str, room_ids: list[str]) -> int:
    if not room_ids:
        return 0
    script = lua_scripts.ack_dirty_rooms
    if script is None:
        raise RuntimeError("ack_dirty_rooms Lua script가 로드되지 않았습니다.")
    return int(await script(
        keys=[
            DIRTY_CHAT_ROOM_PROCESSING_KEY,
            DIRTY_CHAT_ROOM_PROCESSING_OWNER_KEY,
            DIRTY_CHAT_ROOM_DEFERRED_KEY,
            DIRTY_CHAT_ROOM_KEY,
        ],
        args=[claim_token, *room_ids],
    ))


async def reconcile_last_message_once() -> int:
    """dirty room 한 배치를 claim 후 RDB `last_message_*` 를 Mongo 값으로 갱신.

    Returns:
        이번 호출에서 claim 한 방 개수. `< BATCH_SIZE` 면 drain 중단 신호로 사용.
    """
    redis_hot = await get_redis_client()

    dirty_size = await redis_hot.scard(DIRTY_CHAT_ROOM_KEY)
    processing_size = await redis_hot.zcard(DIRTY_CHAT_ROOM_PROCESSING_KEY)
    deferred_size = await redis_hot.scard(DIRTY_CHAT_ROOM_DEFERRED_KEY)
    chat_reconcile_dirty_set_size_set(dirty_size + processing_size + deferred_size)

    async with chat_reconcile_tick():
        claim_token = uuid.uuid4().hex
        room_ids, has_more_ready = await _claim_dirty_rooms(redis_hot, claim_token)
        if not room_ids:
            chat_reconcile_batch_pop_inc("empty")
            return RECONCILE_BATCH_SIZE if has_more_ready else 0

        message_repo = ChatMessageRepository(mongodb.database)
        try:
            last_by_room = await message_repo.find_last_by_rooms(room_ids)
        except Exception as e:
            chat_reconcile_batch_pop_inc("mongo_failed")
            logger.warning(
                "reconcile: Mongo aggregate 실패 → {} 개 processing 유지: {}",
                len(room_ids), type(e).__name__,
            )
            return 0

        if not last_by_room:
            # Mongo 메시지 0 — 방 생성 직후 삭제 등의 이상 상태. UPDATE 없이 결과만 흘려보냄.
            await _ack_dirty_rooms(claim_token, room_ids)
            chat_reconcile_batch_pop_inc("ok")
            chat_reconcile_rooms_processed_inc("skipped", len(room_ids))
            logger.info(
                "reconcile: claimed={} 이지만 Mongo hit 0 — last_message 없는 방으로 간주하고 ACK",
                len(room_ids),
            )
            return RECONCILE_BATCH_SIZE if has_more_ready else len(room_ids)

        factory = _require_factory()
        failed: list[str] = []
        updated = 0
        commit_failed = False
        async with factory() as session:
            chat_room_repo = ChatRoomRepository(session)
            for room_id, doc in last_by_room.items():
                try:
                    await chat_room_repo.update_last_message_if_greater(
                        chat_room_id=room_id,
                        message_id=doc["message_id"],
                        server_seq=doc["server_seq"],
                        at=doc["created_at"],
                    )
                    updated += 1
                except Exception as e:
                    logger.warning(
                        "reconcile: 방 {} UPDATE 실패 — processing lease 유지: {}",
                        room_id, type(e).__name__,
                    )
                    failed.append(room_id)
            try:
                await session.commit()
            except Exception as e:
                # commit 실패 시 명시 rollback — `async with` 가 자동 rollback 하지 않으면
                # 커넥션이 aborted 트랜잭션 상태로 풀에 반납될 위험.
                logger.warning(
                    "reconcile: commit 실패 → 배치 processing lease 유지 ({} 개): {}",
                    len(last_by_room), type(e).__name__,
                )
                try:
                    await session.rollback()
                except Exception as rb_err:
                    logger.warning(
                        "reconcile: rollback 도 실패 (커넥션 풀 보호 실패 가능): {}",
                        type(rb_err).__name__,
                    )
                failed.extend(last_by_room.keys() - set(failed))
                updated = 0
                commit_failed = True

        if commit_failed:
            chat_reconcile_batch_pop_inc("rdb_failed")
        else:
            acknowledged = list(set(room_ids) - set(failed))
            await _ack_dirty_rooms(claim_token, acknowledged)
            chat_reconcile_batch_pop_inc("ok")
            chat_reconcile_rooms_processed_inc("updated", updated)
            chat_reconcile_rooms_processed_inc("failed", len(failed))

        logger.info(
            "reconcile: claimed={}, mongo_hit={}, updated={}, retained={}",
            len(room_ids), len(last_by_room), updated, len(failed),
        )
        if commit_failed or failed:
            return 0
        return RECONCILE_BATCH_SIZE if has_more_ready else len(room_ids)


def _force_invalidate_session(session: AsyncSession, room_id: str) -> bool:
    try:
        # greenlet 밖의 sync invalidate는 asyncpg connection을 await 없이 force-close한다.
        session.sync_session.invalidate()
    except BaseException as exc:
        logger.error(
            "pending sweep connection 강제 invalidate 실패: room_id={}, err={}",
            room_id, type(exc).__name__,
        )
        return False
    return True


async def _recover_pending_room(
    factory: async_sessionmaker[AsyncSession],
    redis_hot,
    redis_dedupe,
    message_repo: ChatMessageRepository,
    room_id: str,
) -> bool:
    session = factory()
    connection_invalidated = False
    try:
        room_repo = ChatRoomRepository(session)
        room = await room_repo.find_by_id_for_update(room_id)
        if room is None:
            await _clear_pending_message(redis_hot, room_id)
            await session.commit()
            logger.warning("pending sweep: 존재하지 않는 room intent 폐기: room_id={}", room_id)
            return False

        await _recover_pending_message(
            redis_hot, redis_dedupe, message_repo, room_id,
            # Motor executor는 asyncio cancel 뒤에도 동작할 수 있어 현재 operation은 drain한다.
            defer_cancellation=True,
        )
        await session.commit()
        return True
    except BaseException:
        connection_invalidated = _force_invalidate_session(session, room_id)
        raise
    finally:
        if not connection_invalidated:
            session.sync_session.close()


async def recover_pending_messages_once() -> int:
    """후속 sender가 없는 orphan pending을 room X-lock 아래 제한적으로 복구한다."""
    global _pending_page_offset, _pending_scan_cursor

    redis_hot = await get_redis_client()
    redis_dedupe = await get_redis_dedupe_client()
    factory = _require_factory()
    message_repo = ChatMessageRepository(mongodb.database)
    resolved = 0
    failures = 0

    for _ in range(PENDING_SCAN_MAX_CALLS_PER_TICK):
        if len(_pending_key_backlog) >= PENDING_RECOVERY_MAX_ROOMS_PER_TICK:
            break
        next_cursor, page = await redis_hot.scan(
            cursor=_pending_scan_cursor,
            match=f"{ROOM_PENDING_MESSAGE_PREFIX}*",
            count=PENDING_SWEEP_BATCH_SIZE,
        )
        _pending_scan_cursor = int(next_cursor)
        candidates: list[str] = []
        for raw_key in page:
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            if key not in _pending_key_backlog_set:
                candidates.append(key)
        capacity = PENDING_DISCOVERY_BACKLOG_LIMIT - len(_pending_key_backlog)
        if candidates and capacity > 0:
            start = _pending_page_offset % len(candidates)
            selected = (candidates[start:] + candidates[:start])[:capacity]
            _pending_page_offset = (start + len(selected)) % len(candidates)
            for key in selected:
                _pending_key_backlog.append(key)
                _pending_key_backlog_set.add(key)
        if _pending_scan_cursor == 0:
            break

    rooms_this_tick = min(
        len(_pending_key_backlog), PENDING_RECOVERY_MAX_ROOMS_PER_TICK,
    )
    for _ in range(rooms_this_tick):
        key = _pending_key_backlog.popleft()
        _pending_key_backlog_set.discard(key)
        if not key.startswith(ROOM_PENDING_MESSAGE_PREFIX):
            continue
        room_id = key[len(ROOM_PENDING_MESSAGE_PREFIX):]
        if not room_id:
            continue

        try:
            recovered = await asyncio.wait_for(
                _recover_pending_room(
                    factory, redis_hot, redis_dedupe, message_repo, room_id,
                ),
                timeout=PENDING_RECOVERY_CANCEL_AFTER_SEC,
            )
            resolved += int(recovered)
        except Exception as exc:
            logger.warning(
                "pending sweep 복구 실패 (intent 유지): room_id={}, err={}",
                room_id, type(exc).__name__,
            )
            failures += 1
    if failures:
        raise PendingRecoveryBatchError(
            f"pending recovery failed for {failures} room(s)",
        )
    return resolved


async def _reconcile_loop(stop_event: asyncio.Event) -> None:
    """stop_event 가 set 될 때까지 무한 반복. 한 사이클 내 백로그 drain 후 다음 tick 대기."""
    logger.info(
        "reconcile 루프 시작: interval={}s, batch={}",
        RECONCILE_INTERVAL_SEC, RECONCILE_BATCH_SIZE,
    )
    while not stop_event.is_set():
        try:
            async with worker_tick("reconcile"):
                for _ in range(RECONCILE_MAX_BATCHES_PER_TICK):
                    processed = await reconcile_last_message_once()
                    if processed < RECONCILE_BATCH_SIZE:
                        break
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(0)
                else:
                    logger.warning(
                        "reconcile tick 작업 예산 소진: batches={}",
                        RECONCILE_MAX_BATCHES_PER_TICK,
                    )
        except Exception as e:
            logger.exception("reconcile tick 전역 실패 (계속 진행): {}", e)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=RECONCILE_INTERVAL_SEC)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("reconcile 루프 종료")


async def _pending_recovery_loop(stop_event: asyncio.Event) -> None:
    """ambiguous pending 복구를 projection reconcile과 격리한다."""
    logger.info("pending recovery 루프 시작: interval={}s", PENDING_RECOVERY_INTERVAL_SEC)
    while not stop_event.is_set():
        try:
            async with worker_tick("pending_recovery"):
                await recover_pending_messages_once()
        except Exception as exc:
            logger.exception("pending recovery tick 전역 실패 (계속 진행): {}", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=PENDING_RECOVERY_INTERVAL_SEC,
            )
            break
        except asyncio.TimeoutError:
            pass
    logger.info("pending recovery 루프 종료")


async def recover_unread_for_user(
    user_id: str,
    only_room: Optional[str] = None,
) -> dict[str, int]:
    """DB 기준으로 `unread:{user_id}` HASH 재계산 후 HSET.

    Redis flush/장애 또는 재초대 후 호출. ws.py 가 백그라운드 태스크로 트리거.

    Args:
        only_room: 특정 방만 복구 (재초대 등). None 이면 유저 전체 방.

    Returns:
        Redis 에 반영된 `{room_id: count}` (0 포함). 실패 시 빈 dict.
    """
    factory = _require_factory()

    generation_error: Optional[Exception] = None
    generations: dict[str, int] = {}
    async with factory() as session:
        member_repo = ChatRoomMemberRepository(session)
        last_reads = await member_repo.find_last_read_seqs(
            user_id,
            room_ids=[only_room] if only_room else None,
            for_share=True,
        )
        if last_reads:
            try:
                redis_hot = await get_redis_client()
                values = await asyncio.gather(*(
                    redis_hot.get(room_members_gen_key(room_id))
                    for room_id in last_reads
                ))
                generations = {
                    room_id: int(value or 0)
                    for room_id, value in zip(last_reads, values)
                }
            except Exception as e:
                generation_error = e

    if generation_error is not None:
        logger.warning(
            "recover_unread: generation snapshot 실패 — user_id={}, err={}",
            user_id, generation_error,
        )
        cleanup_ok = True
        try:
            redis_hot = await get_redis_client()
            await redis_hot.delete(unread_key(user_id))
        except Exception as del_err:
            cleanup_ok = False
            logger.warning(
                "recover_unread: generation 실패 cleanup DEL 실패 — partial state 잔존 위험: {}",
                type(del_err).__name__,
            )
        chat_unread_recover_inc("redis_failed" if cleanup_ok else "cleanup_failed")
        return {}

    if not last_reads:
        chat_unread_recover_inc("ok")
        logger.info(
            "recover_unread: user_id={}, only_room={} — 활성 방 없음, skip",
            user_id, only_room,
        )
        return {}

    sem = asyncio.Semaphore(UNREAD_MONGO_CONCURRENCY)
    message_repo = ChatMessageRepository(mongodb.database)

    async def _count(room_id: str, last_read: int) -> tuple[str, int, int, int, int]:
        async with sem:
            redis_hot = await get_redis_client()
            # count 직전 baseline 스냅샷 — count~write 창에 도착한 메시지의 HINCRBY 를 delta 로
            # 보존하기 위해. 절대 HSET 이면 그 증가분이 소거돼 뱃지가 undercount 되고 자가치유
            # 되지 않는다 (mark_read 에서 Lua 로 고친 것과 동일한 레이스).
            baseline = int(await redis_hot.hget(unread_key(user_id), room_id) or 0)
            raw = await message_repo.count_after_seq(
                chat_room_id=room_id,
                after_seq=last_read,
                limit=UNREAD_COUNT_LIMIT,
            )
            return room_id, min(raw, UNREAD_COUNT_CAP), baseline, last_read, generations[room_id]

    results = await asyncio.gather(
        *(_count(rid, seq) for rid, seq in last_reads.items()),
        return_exceptions=True,
    )

    count_errors = [item for item in results if isinstance(item, BaseException)]
    if count_errors:
        for error in count_errors:
            logger.warning("recover_unread: user_id={} 방 count 실패: {}", user_id, error)
        redis_hot = await get_redis_client()
        cleanup_ok = True
        try:
            await redis_hot.delete(unread_key(user_id))
        except Exception as del_err:
            cleanup_ok = False
            logger.warning(
                "recover_unread: count 실패 cleanup DEL 실패 — partial state 잔존 위험: {}",
                type(del_err).__name__,
            )
        chat_unread_recover_inc("mongo_failed" if cleanup_ok else "cleanup_failed")
        return {}

    recovered = [
        item for item in results if not isinstance(item, BaseException)
    ]  # (room_id, residual, baseline, last_read, membership_generation)

    counts: dict[str, int] = {}
    if recovered:
        redis_hot = await get_redis_client()
        try:
            for room_id, residual, baseline, last_read, generation in recovered:
                # 절대 HSET 대신 baseline+delta Lua — residual(DB 잔여) 에 baseline 이후 증가분을
                # 더해 동시 HINCRBY 를 보존한다 (mark_read_unread.lua 재사용, cap clamp 포함).
                final, sync_status, _ = await lua_scripts.mark_read_unread(
                    keys=[
                        unread_key(user_id), read_sync_key(user_id),
                        room_members_gen_key(room_id),
                    ],
                    args=[
                        room_id, residual, baseline, UNREAD_COUNT_CAP, last_read, 1,
                        generation,
                    ],
                )
                if int(sync_status) == 3:
                    raise RuntimeError("membership changed during unread recovery")
                counts[room_id] = int(final)
        except Exception as e:
            # 중간 실패 시 partial state 로 남으면 다음 재연결의 `get_unread_counts` 가 non-empty
            # 라 복구 재시도가 안 된다. DEL 로 전체 쓸어 EXISTS=0 을 강제해야 재trigger 된다.
            logger.warning(
                "recover_unread: Redis 반영 실패 — partial state 정리 후 counts 취소: "
                "user_id={}, err={}",
                user_id, e,
            )
            cleanup_ok = True
            try:
                await redis_hot.delete(unread_key(user_id))
            except Exception as del_err:
                cleanup_ok = False
                logger.warning(
                    "recover_unread: cleanup DEL 실패 — partial state 잔존 위험: {}",
                    type(del_err).__name__,
                )
            chat_unread_recover_inc("redis_failed" if cleanup_ok else "cleanup_failed")
            logger.info(
                "recover_unread: user_id={}, rooms={}, recovered=0 (redis 실패)",
                user_id, len(last_reads),
            )
            return {}

    chat_unread_recover_inc("ok")
    logger.info(
        "recover_unread: user_id={}, rooms={}, recovered={}, only_room={}",
        user_id, len(last_reads), len(counts), only_room,
    )
    return counts


def start_reconcile_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """앱 startup 1회 — 주기 루프 시작 + 워커 전역 의존성 주입.

    `recover_unread_for_user` 도 같은 factory 를 공유하므로 ws.py 호출보다 먼저 실행되어야 한다.
    """
    global _session_factory, _reconcile_task, _pending_recovery_task, _stop_event

    _session_factory = session_factory

    if any(
        task is not None and not task.done()
        for task in (_reconcile_task, _pending_recovery_task)
    ):
        logger.warning("reconcile 스케줄러 중복 시작 무시")
        return

    _stop_event = asyncio.Event()
    _reconcile_task = asyncio.create_task(
        _reconcile_loop(_stop_event),
        name="chat-reconcile",
    )
    _pending_recovery_task = asyncio.create_task(
        _pending_recovery_loop(_stop_event),
        name="chat-pending-recovery",
    )


async def stop_reconcile_scheduler() -> None:
    """앱 shutdown — graceful 종료 후 `GRACE_SEC` 초과 시 cancel.

    Mongo aggregate 중이면 짧게 기다리고 강제 취소 — 무한 대기는 배포 블로킹.
    """
    global _reconcile_task, _pending_recovery_task, _stop_event

    task = _reconcile_task
    pending_task = _pending_recovery_task
    event = _stop_event
    _reconcile_task = None
    _pending_recovery_task = None
    _stop_event = None

    if event is not None:
        event.set()
        tasks = {
            candidate for candidate in (task, pending_task)
            if candidate is not None
        }
        if tasks:
            _done, still_running = await asyncio.wait(
                tasks, timeout=RECONCILE_SHUTDOWN_GRACE_SEC,
            )
            if still_running:
                logger.warning(
                    "chat recovery 루프 {}개가 {}s 내에 종료되지 않아 강제 취소",
                    len(still_running), RECONCILE_SHUTDOWN_GRACE_SEC,
                )
                for running in still_running:
                    running.cancel()
                await asyncio.gather(*still_running, return_exceptions=True)
