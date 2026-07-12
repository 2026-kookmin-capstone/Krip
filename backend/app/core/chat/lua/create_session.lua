-- Atomically add a session and revoke exactly the excess oldest sessions.
-- KEYS: sessions ZSET, per-session result, user revoke generation.
-- ARGV: session id, expiry ms, now ms, max sessions, result TTL, expected generation.
local sessions_key = KEYS[1]
local new_session_id = ARGV[1]
local expires_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local max_sessions = tonumber(ARGV[4])

local current_generation = tonumber(redis.call('GET', KEYS[3]) or '0')
if current_generation ~= tonumber(ARGV[6]) then
  local rejected = {'__revoke_generation_mismatch__'}
  redis.call('DEL', 'sess:' .. new_session_id, 'ws_route:' .. new_session_id)
  redis.call('SET', KEYS[2], cjson.encode(rejected), 'EX', ARGV[5])
  return rejected
end

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
