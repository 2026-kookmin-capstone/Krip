# 최종 데이터 (final_data)

`preprocessed_data/`의 모든 장소를 **`place_id` 기준으로 중복 제거**하여 하나로 병합한 뒤, 100개 단위로 분할한 최종 데이터셋입니다.

## 데이터 요약

| 항목 | 수치 |
|------|------|
| 전처리 데이터 총 장소 | 36,075개 |
| 중복 제거 (place_id 기준) | 7,766건 |
| **최종 고유 장소** | **28,309개** |
| 파일 수 | 284개 |
| 파일당 장소 수 | 100개 (마지막 파일 9개) |

## 파일 구조

```
final_data/
├── final_data1.json      (장소 1~100)
├── final_data2.json      (장소 101~200)
├── final_data3.json      (장소 201~300)
├── ...
├── final_data283.json    (장소 28201~28300)
└── final_data284.json    (장소 28301~28309)
```

## JSON 포맷

각 파일은 **장소 객체의 배열**입니다. 메타데이터 래퍼 없이 바로 배열로 시작합니다.

```json
[
  {
    "place_id": "ChIJwWOTWyegfDURhL8aXElHsOc",
    "display_name": "모다밥상",
    "category": "한식당",
    "types": ["korean_restaurant", "restaurant", ...],
    "address": "대한민국 서울특별시 관악구 관악로14길 36 1층",
    "short_address": "관악구 관악로14길 36 1층",
    "location": { "lat": 37.4787, "lng": 126.9544 },
    "rating": 4.1,
    ...
  },
  ...
]
```

## 장소 필드 (27개)

| # | 필드 | 타입 | 설명 |
|---|------|------|------|
| 1 | `place_id` | string | Google Places 고유 ID |
| 2 | `display_name` | string | 장소 이름 |
| 3 | `category` | string | 한글 카테고리명 |
| 4 | `types` | string[] | Google Places 타입 태그 |
| 5 | `address` | string | 전체 주소 |
| 6 | `short_address` | string | 간략 주소 |
| 7 | `location` | object | `{ "lat": number, "lng": number }` |
| 8 | `rating` | number \| null | 평균 별점 (1.0~5.0) |
| 9 | `rating_stars` | string \| null | 별점 시각화 문자열 |
| 10 | `rating_count` | number \| null | 리뷰 수 |
| 11 | `price_level` | number \| null | 가격 수준 (1~4) |
| 12 | `price_range` | object \| null | `{ "min": string, "max": string }` (KRW) |
| 13 | `editorial_summary` | string \| null | Google 편집자 요약 |
| 14 | `generative_summary` | string \| null | AI 생성 요약 |
| 15 | `review_summary` | string \| null | 리뷰 요약 |
| 16 | `phone` | string \| null | 국내 전화번호 |
| 17 | `phone_international` | string \| null | 국제 전화번호 |
| 18 | `website` | string \| null | 웹사이트 URL |
| 19 | `google_maps_url` | string | Google Maps 장소 페이지 URL |
| 20 | `google_map_review_link` | string \| null | Google Maps 리뷰 페이지 URL |
| 21 | `opening_hours` | string[] \| null | 요일별 영업시간 |
| 22 | `services` | string[] \| null | 제공 서비스 |
| 23 | `payment` | string[] \| null | 결제 수단 |
| 24 | `accessibility` | string[] \| null | 접근성 정보 |
| 25 | `parking` | string[] \| null | 주차 정보 |
| 26 | `reviews` | object[] | 리뷰 목록 |
| 27 | `photos` | string[] | 사진 URL 목록 |

## preprocessed_data와의 차이점

| 항목 | preprocessed_data | final_data |
|------|-------------------|------------|
| 구조 | 상권별 폴더 > 카테고리별 파일 | 단일 폴더, 순번 파일 |
| 메타데이터 | area, category 등 파일 래퍼 있음 | 없음 (장소 배열만) |
| 중복 | 상권/카테고리 간 동일 place_id 존재 | place_id 고유 보장 |
| 장소 수 | 36,075개 | 28,309개 |

## 중복 제거 기준

- 동일한 `place_id`가 여러 상권 또는 카테고리에 중복 수집된 경우, **첫 번째로 등장한 데이터만 유지**
- 상권은 가나다순(DDP_동대문 → 회기_경희대), 카테고리는 번호순(01 → 40)으로 처리되므로, 가나다순 앞 상권의 데이터가 우선
