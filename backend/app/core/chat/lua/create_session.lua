-- Atomically add a session and revoke exactly the excess oldest sessions.
--
-- KEYS[1] = sessions:{user_id} ZSET (score = expiry ms)
-- KEYS[2] = session_create_result:{new_session_id} STRING
-- ARGV[1] = new session id
-- ARGV[2] = new expiry ms
-- ARGV[3] = current time ms
-- ARGV[4] = max sessions
-- ARGV[5] = result TTL seconds
--
-- Revoked sess HASH keys are deleted here so authorization stops atomically with
-- ZSET removal. ws_route keys remain until the caller publishes revoke events.

local sessions_key = KEYS[1]
local new_session_id = ARGV[1]
local expires_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local max_sessions = tonumber(ARGV[4])

local prior_result = redis.call('GET', KEYS[2])
if prior_result then
  return cjson.decode(prior_result)
end

redis.call('ZREMRANGEBYSCORE', sessions_key, '-inf', now_ms)
redis.call('ZADD', sessions_key, expires_ms, new_session_id)

local overflow = redis.call('ZCARD', sessions_key) - max_sessions
local revoked = {}
if overflow > 0 then
  local sessions = redis.call('ZRANGE', sessions_key, 0, -1)
  for _, session_id in ipairs(sessions) do
    if session_id ~= new_session_id then
      redis.call('ZREM', sessions_key, session_id)
      redis.call('DEL', 'sess:' .. session_id)
      table.insert(revoked, session_id)
      if #revoked == overflow then
        break
      end
    end
  end
end

redis.call('SET', KEYS[2], cjson.encode(revoked), 'EX', ARGV[5])
return revoked
