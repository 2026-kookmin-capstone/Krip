-- Extend a live session, or clean stale membership/route atomically.
--
-- KEYS[1] = sess:{session_id} HASH
-- KEYS[2] = ws_route:{session_id}
-- KEYS[3] = sessions:{user_id} ZSET
-- ARGV[1] = session id
-- ARGV[2] = new expiry ms
-- ARGV[3] = TTL seconds

local session_id = ARGV[1]
if redis.call('EXISTS', KEYS[1]) == 0
    or redis.call('ZSCORE', KEYS[3], session_id) == false then
  redis.call('DEL', KEYS[2])
  redis.call('ZREM', KEYS[3], session_id)
  return 0
end

redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
redis.call('ZADD', KEYS[3], 'XX', ARGV[2], session_id)
return 1
