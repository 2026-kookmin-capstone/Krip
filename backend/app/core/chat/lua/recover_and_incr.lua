-- Redis 리셋 이후 첫 채번 복구.
-- 키가 없거나 현재값이 base(=mongo_max + safety_gap) 보다 작은 경우에만 SET —
-- 다른 프로세스가 이미 앞서 나가 있는 상태를 덮지 않도록 `cur < base` 가드.
-- SET 후 항상 INCR 로 다음 seq 를 반환해 호출측이 한 라운드트립으로 채번 완료.
--
-- KEYS[1] = room:seq:{room_id}
-- ARGV[1] = base  (mongo_max + 1000 를 권장 — 동시 여러 프로세스가 겹쳐도 흡수)
-- return  = 다음 seq (int)
local cur = redis.call('GET', KEYS[1])
local base = tonumber(ARGV[1])
if (not cur) or (tonumber(cur) < base) then
    redis.call('SET', KEYS[1], base)
end
return redis.call('INCR', KEYS[1])
