-- recipient별 unread 증가와 최신 message seq watermark를 한 실행으로 원자화한다.
-- KEYS = unread:{uid}, unread:watermark:{uid} 쌍
-- ARGV[1] = room_id
-- ARGV[2] = server_seq
for i = 1, #KEYS, 2 do
    redis.call("HINCRBY", KEYS[i], ARGV[1], 1)
    redis.call("HSET", KEYS[i + 1], ARGV[1], ARGV[2])
end
return #KEYS / 2
