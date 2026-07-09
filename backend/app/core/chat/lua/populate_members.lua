-- 멤버 캐시 read-repair populate — generation 가드로 stale write 차단.
--
-- read-repair 는 cache miss 시 DB 멤버 스냅샷을 읽어 SADD 하는데, 그 사이 leave/kick 이
-- 커밋(SREM + gen INCR)되면 커밋 전 스냅샷이 SREM 이후에 쓰여 제거된 멤버가 최대 TTL 동안
-- 부활한다. populate 직전 캡처한 gen 과 현재 gen 이 다르면(=그 사이 멤버십 변경 커밋) SADD 를
-- 건너뛴다. removal 의 SREM+INCR 과 이 스크립트는 각각 원자적이라 절대 교차하지 않으므로,
-- SREM 이 적용됐다면 INCR 도 적용됨 → gen 불일치 → skip. 부활 불가능.
--
-- KEYS[1] = room:members:{room}
-- KEYS[2] = room:members:gen:{room}
-- ARGV[1] = gen0  (DB 읽기 직전 캡처한 generation, 부재 시 "0")
-- ARGV[2] = ttl   (ROOM_MEMBERS_TTL)
-- ARGV[3..] = member user_ids (>=1)
-- return  = 1 populate 반영 / 0 gen 불일치로 skip
local cur = tonumber(redis.call('GET', KEYS[2]) or '0')
if cur ~= tonumber(ARGV[1]) then
  return 0
end

-- gen 이 동일 == 그 사이 멤버십 변경 없음 → 스냅샷을 신뢰. 기존 잔재를 지우고 새로 채워
-- merge 로 인한 유령 멤버 잔존을 배제한다.
redis.call('DEL', KEYS[1])
for i = 3, #ARGV do
  redis.call('SADD', KEYS[1], ARGV[i])
end
local ttl = tonumber(ARGV[2])
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)  -- gen 수명도 members 와 함께 연장 (비활성 방 키 누수 방지)
return 1
