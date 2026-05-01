# Tour Recommend API 명세

서울 여행 코스 추천 (v2). 일자별 입력을 받아 시간 기반 코스를 생성한다.

---

## 1. 엔드포인트

| 항목 | 값 |
| --- | --- |
| Method | `POST` |
| Path | `/api/tour/recommend` |
| Content-Type | `application/json` |
| 인증 | Bearer Token (전역 미들웨어) |
| 응답 시간 | LLM 호출 포함, 일자당 수 초 |

---

## 2. Request Body

### 2.1 최상위 (`TourRecommendRequest`)

| 필드 | 타입 | 필수 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `travel_days` | `int` | ✓ | `1 ≤ N ≤ 3` | 여행 일수 |
| `food_preference` | `enum` | ✓ | [§3.1](#31-food_preference) | 음식 옵션 |
| `days` | `TourDayRequest[]` | ✓ | `len(days) === travel_days` | 일자별 입력 |

> **검증**: `len(days)`가 `travel_days`와 다르면 422.

### 2.2 일자별 (`TourDayRequest`)

| 필드 | 타입 | 필수 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `departure_cluster` | `string` | ✓ | [§4](#4-cluster-권역) 키 | 출발 권역 |
| `arrival_cluster` | `string` | ✓ | [§4](#4-cluster-권역) 키 | 도착 권역 |
| `additional_place_id` | `string \| null` | ✗ | DB 존재 필수 | 필수 포함 장소 1개 (`place` API의 `place_id`) |
| `transport` | `enum` | ✓ | [§3.2](#32-transport) | 이동 수단 |
| `start_time` | `string` | ✓ | `HH:MM` (24h) | 시작 시각 |
| `end_time` | `string` | ✓ | `HH:MM`, `start_time < end_time` | 종료 시각 |
| `companion` | `enum` | ✓ | [§3.3](#33-companion) | 동행 유형 |
| `budget_per_person_krw` | `int` | ✓ | `≥ 0` | 1인 예산 (원) |
| `styles` | `enum[]` | ✓ | 길이 ≥ 1, [§3.4](#34-styles) | 여행 스타일 (다중) |
| `schedule_density` | `enum` | ✓ | [§3.5](#35-schedule_density) | 일정 밀도 |

---

## 3. Enum 정의

> 모든 값은 **영어 코드 그대로** 전송. 한글은 UI 표시용.

### 3.1 `food_preference`

| 코드 | 한글 |
| --- | --- |
| `halal` | 할랄 |
| `vegetarian` | 채식 |
| `any` | 상관없음 |

### 3.2 `transport`

| 코드 | 한글 |
| --- | --- |
| `public_transport` | 대중교통 |

### 3.3 `companion`

| 코드 | 한글 |
| --- | --- |
| `solo` | 혼자 |
| `couple` | 연인 |
| `spouse` | 부부 |
| `friends_colleagues` | 친구·동료 |
| `family_parents` | 가족(부모님) |
| `family_with_kids` | 가족(아이 동반) |

### 3.4 `styles` (다중 선택, 최소 1개)

| 코드 | 한글 |
| --- | --- |
| `activity` | 체험·액티비티 |
| `famous_attractions` | 유명 관광지 |
| `healing` | 휴양·힐링 |
| `culture_history` | 관광·문화·역사 |
| `shopping` | 쇼핑 |
| `food_tour` | 맛집 탐방 |
| `photo_aesthetic` | 사진·감성 |
| `festival_event` | 축제·이벤트 |

### 3.5 `schedule_density`

| 코드 | 한글 |
| --- | --- |
| `relaxed` | 여유롭게 |
| `packed` | 빡빡하게 |

---

## 4. Cluster (권역)

> 백엔드에 보낼 키는 **첫 번째 컬럼(영문)** 그대로. 한글은 UI용.

| 영문 키 (전송용) | 위도 | 경도 | 한글 |
| --- | --- | --- | --- |
| `Myeongdong / Euljiro` | 37.565 | 126.987 | 명동/을지로 |
| `Gangnam Station` | 37.500 | 127.032 | 강남역 |
| `Hongdae / Hapjeong` | 37.555 | 126.923 | 홍대/합정 |
| `Itaewon` | 37.535 | 126.998 | 이태원 |
| `Jamsil` | 37.515 | 127.083 | 잠실 |
| `Konkuk Univ. Station (Kondae)` | 37.543 | 127.070 | 건대입구 |
| `Sinchon / Yonsei Univ.` | 37.558 | 126.940 | 신촌/연대 |
| `Jongno / Insadong` | 37.575 | 126.988 | 종로/인사동 |
| `Yeouido` | 37.525 | 126.928 | 여의도 |
| `Seongsu-dong` | 37.547 | 127.060 | 성수동 |
| `Mangwon / Yeonnam-dong` | 37.563 | 126.912 | 망원/연남동 |
| `Euljiro 3-ga / Chungmuro` | 37.566 | 126.995 | 을지로3가/충무로 |
| `Apgujeong / Cheongdam` | 37.527 | 127.047 | 압구정/청담 |
| `Garosu-gil (Sinsa)` | 37.521 | 127.025 | 가로수길(신사) |
| `Bukchon / Samcheong-dong` | 37.582 | 126.984 | 북촌/삼청동 |
| `Gwangjang Market / Dongdaemun` | 37.572 | 127.004 | 광장시장/동대문 |
| `Yongsan / Haebangchon (HBC)` | 37.544 | 126.987 | 용산/해방촌 |
| `Hannam-dong` | 37.536 | 127.004 | 한남동 |
| `Mullae-dong` | 37.516 | 126.900 | 문래동 |
| `Songridan-gil (Songpa)` | 37.507 | 127.113 | 송리단길(송파) |
| `Seoul Forest / Ttukseom` | 37.547 | 127.048 | 서울숲/뚝섬 |
| `Mapo / Gongdeok` | 37.546 | 126.953 | 마포/공덕 |
| `Nakseongdae / Sharosu-gil` | 37.479 | 126.955 | 낙성대/샤로수길 |
| `Hyehwa / Daehangno` | 37.584 | 127.004 | 혜화/대학로 |
| `Hoegi / Kyung Hee Univ.` | 37.590 | 127.054 | 회기/경희대 |
| `Noryangjin / Dongjak` | 37.513 | 126.945 | 노량진/동작 |
| `Wangsimni / Sangwangsimni` | 37.563 | 127.039 | 왕십리/상왕십리 |
| `Dosan Park / Hak-dong` | 37.524 | 127.035 | 도산공원/학동 |
| `Samseong / COEX` | 37.512 | 127.060 | 삼성/코엑스 |
| `Bangbae / Seorae Village` | 37.482 | 126.993 | 방배/서래마을 |
| `Sangsu-dong` | 37.550 | 126.924 | 상수동 |
| `Ikseon-dong` | 37.575 | 126.991 | 익선동 |
| `Banpo Hangang Park` | 37.509 | 126.998 | 반포한강공원 |
| `N Seoul Tower Area (Namsan)` | 37.552 | 126.989 | 남산타워 일대 |
| `DDP / Dongdaemun` | 37.569 | 127.011 | DDP/동대문 |
| `Seongbuk-dong` | 37.597 | 126.995 | 성북동 |
| `Yeonhui-dong` | 37.573 | 126.932 | 연희동 |
| `Ssangmun / Suyu` | 37.650 | 127.024 | 쌍문/수유 |

> ⚠️ 슬래시·공백·점·괄호까지 **완전 동일하게** 전송. 매칭 실패 시 422.

---

## 5. Response (200)

### 5.1 최상위 (`TourRecommendResponse`)

```ts
{
  tour_plan: TourDayResponse[]   // 일자별 플랜, 길이 === travel_days
}
```

### 5.2 일자별 (`TourDayResponse`)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `day` | `int` | 1-indexed 일차 |
| `timeline` | `TimelineSlot[]` | 시간 기반 동선 (시각 순 정렬) |
| `places` | `PlaceDetail[]` | 장소 상세 목록 |
| `movements` | `MovementHop[]` | 인접 장소 간 이동 흐름 |
| `budget_breakdown` | `BudgetItem[]` | 예산 항목 (Lunch, Cafe 등) |
| `budget_total_krw` | `int` | 예산 합계 (= breakdown 합) |
| `summary` | `string` | 마감 요약 (영어, 2-3문장) |

### 5.3 하위 객체

```ts
TimelineSlot {
  time: string         // "HH:MM"
  place_id: string     // 항상 places 또는 추가 장소의 place_id
  title: string        // "Place Name → Activity" (영어)
}

PlaceDetail {
  place_id: string
  display_name: string
  category: string
  address: string
  location: { lat: number, lng: number }
  rating: number | null
  reason: string                  // 추천 이유 (영어, 2-3문장)
  estimated_cost_krw: int         // 1인 예상 지출 (KRW). ⚠️ 0이라도 무료가 아닐 수 있음 — §10 참고
  stay_minutes: int               // > 0
}

MovementHop {
  from_place: string              // PlaceDetail.display_name
  to_place: string                // PlaceDetail.display_name
  method: string                  // 영어 (예: "Subway Line 2 → 5 min walk")
}

BudgetItem {
  label: string                   // 영어 (예: "Lunch", "Admission")
  amount_krw: int
}
```

> 모든 사용자 노출 텍스트 (`title`, `reason`, `summary`, `method`, `label`)는 **영어**. 외국인 여행자 대상 서비스이기 때문.

---

## 6. 응답 규칙·보장

- `timeline[].place_id`는 **항상 `places[]` 안의 어떤 항목과 일치** (transit-only 슬롯 없음).
- 이동 흐름은 `movements`에만 존재하며 timeline에는 등장하지 않음.
- 요청에 `additional_place_id`를 보냈다면 응답 `places[]` 안에 동일 `place_id`가 **반드시 1개 포함**됨 (강제 보장).
- `budget_total_krw === sum(budget_breakdown[].amount_krw)`.
- `places[]`는 절대 비어있지 않음 (비면 500).

---

## 7. 에러 응답

| Status | 조건 | `detail` 예시 |
| --- | --- | --- |
| `400` | `additional_place_id`가 DB에 없음 | `additional_place_id not found: ChIJxxx` |
| `422` | Pydantic 검증 실패 (시각 형식, 길이 불일치, 알 수 없는 cluster, enum 값 오류 등) | FastAPI 기본 형식 |
| `500` | LLM/서버 측 처리 실패 | `Failed to generate tour recommendation.` |

---

## 8. 예시

### 8.1 Request — 1박 2일, 커플, 할랄

```json
{
  "travel_days": 2,
  "food_preference": "halal",
  "days": [
    {
      "departure_cluster": "Hongdae / Hapjeong",
      "arrival_cluster": "N Seoul Tower Area (Namsan)",
      "additional_place_id": "ChIJ0X7IQw2jfDURa8XanOsn0cw",
      "transport": "public_transport",
      "start_time": "10:00",
      "end_time": "21:00",
      "companion": "couple",
      "budget_per_person_krw": 80000,
      "styles": ["food_tour", "famous_attractions"],
      "schedule_density": "packed"
    },
    {
      "departure_cluster": "Bukchon / Samcheong-dong",
      "arrival_cluster": "Myeongdong / Euljiro",
      "additional_place_id": null,
      "transport": "public_transport",
      "start_time": "10:00",
      "end_time": "20:00",
      "companion": "couple",
      "budget_per_person_krw": 70000,
      "styles": ["culture_history", "shopping"],
      "schedule_density": "relaxed"
    }
  ]
}
```

### 8.2 Response 200 (요약)

```json
{
  "tour_plan": [
    {
      "day": 1,
      "timeline": [
        { "time": "10:00", "place_id": "ChIJ...HongdaeCafe", "title": "Thanks Nature Cafe → Brunch & Coffee" },
        { "time": "13:30", "place_id": "ChIJ0X7IQw2jfDURa8XanOsn0cw", "title": "Cherry Garden → Halal Korean Lunch" },
        { "time": "20:30", "place_id": "ChIJ...NSeoulTower", "title": "N Seoul Tower → Night View" }
      ],
      "places": [
        {
          "place_id": "ChIJ0X7IQw2jfDURa8XanOsn0cw",
          "display_name": "Cherry Garden Restaurant (Halal)",
          "category": "Korean restaurant",
          "address": "Jongno-gu, Seoul",
          "location": { "lat": 37.5723, "lng": 127.0140 },
          "rating": 5.0,
          "reason": "Halal-certified Korean restaurant ...",
          "estimated_cost_krw": 18000,
          "stay_minutes": 75
        }
      ],
      "movements": [
        { "from_place": "Thanks Nature Cafe", "to_place": "Cherry Garden Restaurant (Halal)", "method": "Subway Line 2 → Line 1" }
      ],
      "budget_breakdown": [
        { "label": "Brunch & Cafe", "amount_krw": 18000 },
        { "label": "Halal Lunch", "amount_krw": 18000 },
        { "label": "Dinner", "amount_krw": 22000 }
      ],
      "budget_total_krw": 58000,
      "summary": "A natural arc through Hongdae's youth scene to Namsan's night view, anchored by halal lunch at Cherry Garden."
    }
  ]
}
```

---

## 9. 프론트 연동 체크리스트

- [ ] cluster 드롭다운 항목은 [§4](#4-cluster-권역) 표를 그대로 사용 (영문 키 전송, 한글 표시).
- [ ] `styles`는 멀티셀렉트, 최소 1개 강제.
- [ ] `start_time < end_time` 클라이언트 측 사전 검증.
- [ ] `additional_place_id`는 별도 장소 검색 API 결과에서 골라 넘김 (선택).
- [ ] 응답 텍스트는 영어이므로 그대로 표시 (i18n 별도 미적용).
- [ ] `timeline[].place_id`로 `places[]`를 lookup하여 카드 렌더 (slot ↔ detail 조인).
- [ ] `movements`는 인접 카드 사이의 이동 라벨로 렌더.
- [ ] "필수 방문" 뱃지가 필요하면 `place.place_id === request.days[i].additional_place_id` 비교로 클라이언트에서 판별.
- [ ] 응답이 `travel_days`초~수십 초 걸릴 수 있으니 로딩 UI 필수.

---

## 10. 주의사항 (Frontend Caveats)

> 명세 외 함정·약한 보장 항목. 렌더 전 반드시 확인.

### 10.1 `estimated_cost_krw: 0`은 "무료"가 아닐 수 있다 ⚠️
- `0`이 항상 무료를 뜻하지 않는다. **추정 실패/누락**으로 0이 들어오는 경로가 존재한다.
  - 추가 장소(`additional_place_id`)가 LLM 응답에서 누락되어 서버가 강제 삽입한 경우, fallback default로 `0`이 들어간다 — 실제 입장료가 있는 장소도 마찬가지.
  - LLM이 비용을 추정하지 못한 케이스도 0으로 떨어질 수 있음.
- **권장 렌더링**:
  - `0`이면 `"₩—"` / `"비용 정보 없음"` 같은 중립 표기.
  - "Free" 라벨을 보여주려면 `category`나 `types`로 별도 검증 (e.g. `park`, `historical_landmark`).

### 10.2 예산 초과 가능
- 서버는 `budget_total_krw > budget_per_person_krw`를 **경고만 로그**하고 응답을 그대로 반환.
- 또한 `sum(places[].estimated_cost_krw)`도 예산을 초과할 수 있음.
- 프론트에서 합계가 입력 예산을 넘으면 "⚠ 예산 초과" 표시 권장.

### 10.3 `budget_total_krw === sum(budget_breakdown)` (보장)
- 서버 후처리가 강제 동기화. 프론트에서 별도 합산 없이 `budget_total_krw` 그대로 사용 가능.
- 단, `budget_breakdown`이 비어있고 places 비용도 없으면 `budget_total_krw === 0`이 들어올 수 있음.

### 10.4 `timeline.place_id`는 `places[]` 안에 반드시 존재 (보장)
- transit-only 슬롯 (`"Travel to X"` 등)은 응답에 없음. 이동은 `movements`에만.
- 따라서 `places.find(p => p.place_id === slot.place_id)`는 절대 `undefined`가 되지 않음 — null 체크 불필요.

### 10.5 `movements`는 timeline과 1:1이 아니다
- `movements`는 **장소 → 장소** 인접 흐름이고, timeline 슬롯 수와 일치하지 않을 수 있음.
- 같은 장소 연속 슬롯(체류)은 movement 없음. 0건일 수도 있음 (1개 장소만 있는 날 등).
- 렌더 시 `places` 순서를 기준으로 `movements`를 끼워 넣는 식이 안전.

### 10.6 cluster 키 정확성
- 영문 키는 슬래시(`/`), 공백, 점(`.`), 괄호 포함 **글자 그대로** 전송.
  - `"Hongdae / Hapjeong"` ✅ / `"Hongdae/Hapjeong"` ❌ (422)
  - `"Sinchon / Yonsei Univ."` (마지막 점 포함) ✅
- 드롭다운은 §4 표의 영문 키를 enum으로 박아두는 게 안전.

### 10.7 `additional_place_id`는 검증된 ID만
- DB에 없는 ID를 넘기면 400 (`additional_place_id not found`).
- 반드시 **장소 검색/조회 API 응답에서 받은 `place_id`**만 사용. 사용자 직접 입력 금지.
- 여러 일자에 같은 ID 지정은 허용 (서버가 일자 간 일반 장소 중복은 막지만, 추가 장소는 의도적 중복 허용).

### 10.8 시각 범위는 약한 보장
- 첫 슬롯 `time ≥ start_time`, 마지막 슬롯 `time ≤ end_time`은 LLM에 위임돼 **강제되지 않음**.
- 약간의 spillover(예: end_time 21:00인데 마지막 슬롯 21:30) 가능. 프론트에서 critical하면 클라이언트 사이드 가드.

### 10.9 텍스트 언어
- `reason`, `summary`, `timeline.title`, `movements.method`, `budget_breakdown.label`은 **항상 영어**.
- 외국인 여행자 대상 서비스 전제. 한국어 i18n 필요하면 클라이언트에서 별도 번역 레이어.

### 10.10 `rating: null` 가능
- 평점/리뷰가 없는 장소는 `null`. 별점 컴포넌트에 null safe 처리 필요.

### 10.11 응답 시간
- LLM 호출이 일자별로 발생 → `travel_days` × 수 초 (네트워크 포함 5~30초 흔함).
- 클라이언트 타임아웃은 **최소 60초** 권장. 로딩 스피너/스켈레톤 필수.
- 동일 입력에 대한 결과 캐싱은 서버에서 하지 않음 (매 호출이 새 LLM 호출).

### 10.12 `places[]`는 비어있지 않다 (보장)
- 빈 배열이면 서버가 500을 던짐. 클라이언트에서 빈 케이스 별도 분기 불필요.
- 단, 일자별 length는 가변 (3~7개). 그리드/리스트는 가변 길이 가정.

### 10.13 `is_additional` 필드 부재
- 응답에 `is_additional` 플래그는 **포함되지 않음**.
- "필수 방문" 식별이 필요하면 클라이언트에서 `place.place_id === request.days[i].additional_place_id`로 비교.

