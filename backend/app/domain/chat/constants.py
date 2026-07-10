MAX_GROUP_MEMBERS = 100
MAX_GROUP_CREATE_INVITEES = MAX_GROUP_MEMBERS - 1
MAX_INVITE_BATCH = 50

# unread 표시 상한 (999+ 캡) — chat read/unread 경로(room·history·reconcile) 공통 규약.
UNREAD_COUNT_CAP = 999
# count-with-limit 로 "999+" 를 감지하기 위한 조회 상한 (cap + 1).
UNREAD_COUNT_LIMIT = UNREAD_COUNT_CAP + 1
