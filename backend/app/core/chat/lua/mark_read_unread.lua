-- mark_read 의 unread 재계산.
-- 절대값 HSET 은 count~write 창에서 도착한 메시지의 HINCRBY 를 소거해 뱃지를 잃는다.
-- baseline(count 직전 스냅샷) 이후 증가분(delta)을 residual 에 더해 보존하고 cap 으로 clamp.
-- delta 는 0 미만으로 내려가지 않아 읽음 처리로 뱃지를 잃지 않는다 (드물게 소폭 over-count
-- 가능하나 다음 read 에서 self-heal — 안전한 방향).
--
-- KEYS[1] = unread:{user_id}
-- ARGV[1] = room_id  (hash field)
-- ARGV[2] = residual (final_seq 이후 DB 잔여 개수)
-- ARGV[3] = baseline (count 직전 HGET 스냅샷)
-- ARGV[4] = cap      (999 표시 상한)
-- return  = 반영된 최종 unread (int)
local current = tonumber(redis.call('HGET', KEYS[1], ARGV[1]) or '0')
local residual = tonumber(ARGV[2])
local baseline = tonumber(ARGV[3])
local cap = tonumber(ARGV[4])
local delta = current - baseline
if delta < 0 then delta = 0 end
local final = residual + delta
if final > cap then final = cap end
redis.call('HSET', KEYS[1], ARGV[1], final)
return final
