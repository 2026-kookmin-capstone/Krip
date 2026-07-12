-- Atomically advance the user revoke generation and remove authoritative sessions.
-- KEYS: sessions ZSET, revoke generation, idempotent operation result.
-- ARGV[1]: result TTL seconds.
local prior_result = redis.call("GET", KEYS[3])
if prior_result then
    return cjson.decode(prior_result)
end

redis.call("INCR", KEYS[2])
local session_ids = redis.call("ZRANGE", KEYS[1], 0, -1)
for _, session_id in ipairs(session_ids) do
    redis.call("DEL", "sess:" .. session_id)
end
redis.call("DEL", KEYS[1])
redis.call("SET", KEYS[3], cjson.encode(session_ids), "EX", ARGV[1])
return session_ids
