-- 성공한 recovery가 시작 시 관찰한 marker만 제거한다.
-- 다른 concurrent recovery가 남긴 더 최신 failure marker는 보존한다.
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
