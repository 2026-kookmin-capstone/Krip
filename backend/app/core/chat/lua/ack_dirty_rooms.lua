-- Compare-and-delete ACK for claimed dirty-room generations.
-- KEYS[1]: processing expiry ZSET, KEYS[2]: owner HASH,
-- KEYS[3]: deferred dirty SET, KEYS[4]: ready dirty SET
-- ARGV[1]: claim token, ARGV[2..]: room IDs
local processing_key = KEYS[1]
local owner_key = KEYS[2]
local deferred_key = KEYS[3]
local dirty_key = KEYS[4]
local token = ARGV[1]
local acknowledged = 0

for index = 2, #ARGV do
    local room_id = ARGV[index]
    if redis.call("HGET", owner_key, room_id) == token then
        redis.call("ZREM", processing_key, room_id)
        redis.call("HDEL", owner_key, room_id)
        if redis.call("SREM", deferred_key, room_id) == 1 then
            redis.call("SADD", dirty_key, room_id)
        end
        acknowledged = acknowledged + 1
    end
end

return acknowledged
