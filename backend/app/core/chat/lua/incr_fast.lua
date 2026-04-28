-- 방 시퀀스 fast-path 채번.
-- 키가 살아있으면 그대로 INCR, Redis 가 리셋되어 키가 증발한 상태면 -1 을 돌려
-- 호출측이 Mongo 조회 후 recover_and_incr.lua 로 넘어가도록 분기한다.
-- 그냥 INCR 하면 0→1 으로 시작해 Mongo 의 마지막 seq 와 충돌(C1 UNIQUE 걸림).
--
-- KEYS[1] = room:seq:{room_id}
-- return  = 다음 seq (int) | -1 (복구 경로 필요)
if redis.call('EXISTS', KEYS[1]) == 1 then
    return redis.call('INCR', KEYS[1])
end
return -1
