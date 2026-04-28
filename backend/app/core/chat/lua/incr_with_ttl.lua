-- 원자적 INCR + EXPIRE.
-- INCR 과 EXPIRE 를 분리해서 호출하면 두 명령 사이 크래시/네트워크 단절 시
-- TTL 없는 키가 영구 잔존해 해당 유저가 영구 차단되는 함정이 있다.
-- 반드시 Lua 로 묶어 한 단위로 처리.
--
-- KEYS[1] = 대상 키 (예: rate:msg:{user_id})
-- ARGV[1] = TTL seconds
-- return  = 이번 윈도우 누적 카운트 (int) — 호출측이 임계값 비교
local cur = redis.call('INCR', KEYS[1])
if cur == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return cur
