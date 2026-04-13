## Place DB 마이그레이션 방법
1. docker exec -it example-mongodb mongosh -u cho -p hyeonsang --authenticationDatabase admin
2. source .venv/bin/activate
3. python scripts/load_places.py --mongodb-url mongodb://cho:hyeonsang@example-mongodb:27017/chohyeonsang?authSource=admin 