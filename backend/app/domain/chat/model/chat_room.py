from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column, String, DateTime, BigInteger, Enum, ForeignKey, Index,
    CheckConstraint, Computed, literal_column,
)
import enum

from app.util.id_generator import generate_chat_room_id
from app.database.session import Base


class ChatRoomType(str, enum.Enum):
    DIRECT = "direct"   # 1:1 방
    GROUP = "group"     # 그룹 방 (Phase 2 에서 사용)


class ChatRoom(Base):
    """채팅방 메타 정보

    - 1:1 방(type='DIRECT') 은 `(direct_user_a_id, direct_user_b_id)` 를 canonical 정렬(`a < b`)해
      저장하며, UNIQUE INDEX 로 같은 쌍의 중복 방 생성을 DB 레벨에서 차단한다.
    - 그룹 방(type='GROUP') 은 `direct_user_*` 가 NULL — CheckConstraint 로 강제.
    - `last_message_*` 는 방 리스트 정렬·미리보기용 역정규화. 실패 시에도 기능에 치명적이지 않도록
      `dirty:chat_room` Redis SET 에 적재하고 reconcile job 이 최종 정합성 복구.
    - `effective_last_at` 은 GENERATED STORED 컬럼 — 방 리스트 정렬 인덱스 1개로 끝냄
      (COALESCE 를 매번 수행하지 않아도 됨).
    - 첨자 `updated_at` 에는 auto-trigger 를 붙이지 않는다 — ON CONFLICT DO UPDATE 경로와의
      상호작용 함정을 피하기 위함.

    **탈퇴 정책**: 3개 유저 FK 는 모두 `ON DELETE SET NULL`. 유저가 탈퇴해도 대화 히스토리와
    방 자체는 보존되어 남은 멤버가 계속 열람 가능하도록 한다. 탈퇴자가 있던 자리는 NULL 이 되고,
    조회 시 "탈퇴한 사용자" 로 표시. 반면 `chat_room_member.user_id` 는 CASCADE 유지 —
    탈퇴자의 멤버십 row 만 제거되어 본인 방 리스트에서는 자연스럽게 사라진다.
    """

    __tablename__ = "chat_room"

    chat_room_id = Column(String(50), primary_key=True, default=generate_chat_room_id)
    type = Column(Enum(ChatRoomType), nullable=False)
    title = Column(String(100), nullable=True)  # direct 방은 NULL
    # creator 탈퇴 시 SET NULL → 방 유지. 조회 시 "알 수 없음" 으로 표시.
    creator_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # 1:1 전용 canonical 쌍. 생성 시점엔 항상 direct_user_a_id < direct_user_b_id.
    # 한 쪽이 탈퇴하면 해당 컬럼만 NULL — 방과 대화 히스토리는 유지.
    direct_user_a_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    direct_user_b_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # 최신 메시지 역정규화 (방 리스트용). MongoDB `chat_message._id` 를 참조.
    last_message_id = Column(String(50), nullable=True)
    last_message_server_seq = Column(BigInteger, nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # 방 리스트 정렬을 단일 인덱스로 처리: last_message_at 이 NULL 이면 created_at 으로 fallback
    effective_last_at = Column(
        DateTime(timezone=True),
        Computed("COALESCE(last_message_at, created_at)", persisted=True),
        nullable=False,
    )

    creator = relationship("User", foreign_keys=[creator_id], backref="created_chat_rooms")
    direct_user_a = relationship("User", foreign_keys=[direct_user_a_id], backref="direct_chat_rooms_as_a")
    direct_user_b = relationship("User", foreign_keys=[direct_user_b_id], backref="direct_chat_rooms_as_b")

    __table_args__ = (
        # 1:1 방은 (a, b) 쌍당 최대 1개. DB 레벨에서 race 직렬화.
        Index(
            "uq_chat_room_direct_pair",
            "direct_user_a_id", "direct_user_b_id",
            unique=True,
            postgresql_where=literal_column("type = 'DIRECT'"),
        ),
        # 방 리스트 정렬 인덱스
        Index("ix_chat_room_effective_last_at", "effective_last_at"),
        # 방 종류별 direct_user_* 정합성 강제 (탈퇴로 NULL 된 DIRECT 는 허용)
        #   - GROUP: 항상 둘 다 NULL
        #   - DIRECT (생성 시):   둘 다 NOT NULL + canonical 정렬 (a < b)
        #   - DIRECT (탈퇴 후):   한 쪽 또는 양쪽이 NULL
        # 생성은 서비스 레이어에서 canonical 정렬을 강제하고, 이 CHECK 는 탈퇴에 의한 SET NULL 을
        # 막지 않기만 하면 된다.
        CheckConstraint(
            "("
            "  type = 'GROUP'"
            "  AND direct_user_a_id IS NULL"
            "  AND direct_user_b_id IS NULL"
            ") OR ("
            "  type = 'DIRECT'"
            "  AND direct_user_a_id IS NOT NULL"
            "  AND direct_user_b_id IS NOT NULL"
            "  AND direct_user_a_id < direct_user_b_id"
            ") OR ("
            "  type = 'DIRECT'"
            "  AND (direct_user_a_id IS NULL OR direct_user_b_id IS NULL)"
            ")",
            name="ck_chat_room_direct_pair_shape",
        ),
    )

    def __repr__(self):
        return f"<ChatRoom(chat_room_id={self.chat_room_id}, type={self.type})>"
