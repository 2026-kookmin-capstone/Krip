## Place DB 마이그레이션 방법
1. docker exec -it example-mongodb mongosh -u cho -p hyeonsang --authenticationDatabase admin
2. source .venv/bin/activate
3. python scripts/load_places.py --mongodb-url mongodb://cho:hyeonsang@example-mongodb:27017/chohyeonsang?authSource=admin 


## Chat Smoke Test 방법
1. scripts/chat/ 까지 이동
2. ./run_smoke.sh
(주의 8100 포트 서버 있으면 안 됌. / 8100 으로 서버가 띄워지기 때문)