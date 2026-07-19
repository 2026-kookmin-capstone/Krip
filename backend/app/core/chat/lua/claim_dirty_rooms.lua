-- Lease-based recoverable dirty-room claim.
-- KEYS[1]: ready dirty SET, KEYS[2]: processing expiry ZSET,
-- KEYS[3]: owner HASH, KEYS[4]: deferred dirty SET
-- ARGV[1]: batch size, ARGV[2]: lease milliseconds, ARGV[3]: claim token
local dirty_key = KEYS[1]
local processing_key = KEYS[2]
local owner_key = KEYS[3]
local deferred_key = KEYS[4]
local batch_size = tonumber(ARGV[1])
local lease_ms = tonumber(ARGV[2])
local token = ARGV[3]

local redis_time = redis.call("TIME")
local now_ms = tonumber(redis_time[1]) * 1000 + math.floor(tonumber(redis_time[2]) / 1000)
local deadline = now_ms + lease_ms
-- First element is `more ready work`; following elements are claimed room IDs.
local result = {0}
local seen = {}

-- Reserve at most half for expired claims while ready work exists. Unused
-- recovery capacity remains available to ready work below.
local expired_limit = batch_size
if redis.call("SCARD", dirty_key) > 0 then
    expired_limit = math.max(1, math.floor(batch_size / 2))
end
local expired = redis.call(
    "ZRANGEBYSCORE", processing_key, "-inf", now_ms,
    "LIMIT", 0, expired_limit
)
for _, room_id in ipairs(expired) do
    redis.call("HSET", owner_key, room_id, token)
    redis.call("ZADD", processing_key, deadline, room_id)
    table.insert(result, room_id)
    seen[room_id] = true
end

local claimed_count = #result - 1
local remaining = batch_size - claimed_count
if remaining > 0 then
    -- Each sampled blocker leaves ready, so repeated bounded calls make progress.
    local candidates = redis.call("SRANDMEMBER", dirty_key, remaining * 2)
    for _, room_id in ipairs(candidates) do
        if (#result - 1) >= batch_size then
            break
        end
        if not seen[room_id] then
            if redis.call("ZSCORE", processing_key, room_id) ~= false then
                if redis.call("SREM", dirty_key, room_id) == 1 then
                    redis.call("SADD", deferred_key, room_id)
                end
            elseif redis.call("SREM", dirty_key, room_id) == 1 then
                redis.call("HSET", owner_key, room_id, token)
                redis.call("ZADD", processing_key, deadline, room_id)
                table.insert(result, room_id)
                seen[room_id] = true
            end
        end
    end
end

if redis.call("SCARD", dirty_key) > 0 then
    result[1] = 1
end
return result
