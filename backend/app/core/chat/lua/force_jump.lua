-- Mongo DuplicateKey 재시도 경로에서 seq 를 강제로 앞으로 점프.
-- 키가 증발한 엣지 케이스는 cur=0 으로 안전 처리.
-- jitter 는 호출측이 `random.randint(1, 10000)` 으로 생성 — 여러 프로세스가
-- 동시에 force_jump 를 치더라도 서로 다른 위치로 튀게 해 재충돌 확률을 낮춘다.
--
-- KEYS[1] = room:seq:{room_id}
-- ARGV[1] = gap     (예: 1000)
-- ARGV[2] = jitter  (1..10000 범위 권장)
-- return  = 새로 세팅된 seq (int)
local cur = redis.call('GET', KEYS[1])
local cur_num = tonumber(cur) or 0
local new_val = cur_num + tonumber(ARGV[1]) + tonumber(ARGV[2])
redis.call('SET', KEYS[1], new_val)
return new_val
