-- marker, unread count, message watermark, applied read seq를 한 Redis 실행으로 snapshot한다.
-- marker가 있으면 partial recovery일 수 있으므로 snapshot을 반환하지 않는다.
-- KEYS[1] = unread recovery marker
-- KEYS[2] = unread counts HASH
-- KEYS[3] = unread message watermark HASH
-- KEYS[4] = applied read seq HASH
if redis.call("EXISTS", KEYS[1]) == 1 then
    return {0}
end

local counts = redis.call("HGETALL", KEYS[2])
local result = {1}
for i = 1, #counts, 2 do
    local room_id = counts[i]
    result[#result + 1] = room_id
    result[#result + 1] = counts[i + 1]
    result[#result + 1] = redis.call("HGET", KEYS[3], room_id) or 0
    result[#result + 1] = redis.call("HGET", KEYS[4], room_id) or 0
end
return result
