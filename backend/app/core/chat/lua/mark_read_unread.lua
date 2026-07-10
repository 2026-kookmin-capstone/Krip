-- mark_read 의 unread 재계산.
-- 절대값 HSET 은 count~write 창에서 도착한 메시지의 HINCRBY 를 소거해 뱃지를 잃는다.
-- baseline(count 직전 스냅샷) 이후 증가분(delta)을 residual 에 더해 보존하고 cap 으로 clamp.
-- delta 는 0 미만으로 내려가지 않아 읽음 처리로 뱃지를 잃지 않는다 (드물게 소폭 over-count
-- 가능하나 다음 read 에서 self-heal — 안전한 방향).
--
-- KEYS[1] = unread:{user_id}
-- KEYS[2] = unread:read_seq:{user_id}
-- KEYS[3] = room:members:gen:{room_id}
-- ARGV[1] = room_id  (hash field)
-- ARGV[2] = residual (final_seq 이후 DB 잔여 개수)
-- ARGV[3] = baseline (count 직전 HGET 스냅샷)
-- ARGV[4] = cap      (999 표시 상한)
-- ARGV[5] = read_seq (이번 DB commit의 최종 read seq)
-- ARGV[6] = allow_equal_if_missing (recovery만 1: unread field가 없을 때 같은 seq 재계산)
-- ARGV[7] = expected_members_generation (read/recovery 시작 시점)
-- 반환 status: 0=더 높은 seq, 1=unread 반영, 2=동일 seq retry, 3=멤버십 변경
-- return  = {최종 unread, status, Redis에 적용된 read seq}
local current_raw = redis.call('HGET', KEYS[1], ARGV[1])
local current = tonumber(current_raw or '0')
local applied_seq = tonumber(redis.call('HGET', KEYS[2], ARGV[1]) or '-1')
local read_seq = tonumber(ARGV[5])
local allow_equal_if_missing = tonumber(ARGV[6])
local current_generation = tonumber(redis.call('GET', KEYS[3]) or '0')
local expected_generation = tonumber(ARGV[7])
if current_generation ~= expected_generation then
    return {current, 3, read_seq}
end
local equal_is_stale = read_seq == applied_seq and (
    allow_equal_if_missing ~= 1 or current_raw ~= false
)
if read_seq < applied_seq then
    return {current, 0, applied_seq}
end
if equal_is_stale then
    return {current, 2, applied_seq}
end

local residual = tonumber(ARGV[2])
local baseline = tonumber(ARGV[3])
local cap = tonumber(ARGV[4])
local delta = current - baseline
if delta < 0 then delta = 0 end
local final = residual + delta
if final > cap then final = cap end
redis.call('HSET', KEYS[1], ARGV[1], final)
redis.call('HSET', KEYS[2], ARGV[1], read_seq)
return {final, 1, read_seq}
