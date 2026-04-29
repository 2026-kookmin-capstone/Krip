"""Tour Planner v2 카테고리 그룹 정의 + 균형 후보 풀 cap 계산.

Google Places `types` 배열을 6개 그룹으로 분류하여, 후보 풀이 식당 편향에
빠지지 않고 식사·관광·카페·쇼핑·야간·체험이 고르게 들어가도록 한다.

분류 우선순위 (top → bottom):
    nightlife > cafe > meal > attraction > activity > shopping > other

근거:
- nightlife 우선: bar는 `restaurant`도 동시 보유하는 경우가 많음. 야간 슬롯 분류가 정확.
- cafe 우선: brunch_restaurant 처럼 카페 분위기 + restaurant 토큰 동시 보유 케이스 흡수.
- meal: 그 외 모든 *_restaurant.
"""

from typing import Dict, List, Set


# ──────────────────── 그룹별 type 매핑 ────────────────────


NIGHTLIFE_TYPES: Set[str] = {
    "bar", "night_club", "wine_bar", "cocktail_bar", "pub", "lounge_bar",
    "brewery", "gastropub", "irish_pub", "sports_bar", "beer_garden",
    "brewpub", "hookah_bar",
}

CAFE_TYPES: Set[str] = {
    "cafe", "coffee_shop", "bakery", "dessert_shop", "ice_cream_shop",
    "cake_shop", "tea_house", "brunch_restaurant", "juice_shop", "donut_shop",
    "chocolate_shop", "candy_store", "confectionery", "pastry_shop",
    "coffee_roastery", "tea_store", "bagel_shop", "sandwich_shop",
    "salad_shop", "breakfast_restaurant", "dessert_restaurant",
}

ATTRACTION_TYPES: Set[str] = {
    "tourist_attraction", "museum", "art_gallery", "art_museum", "history_museum",
    "cultural_center", "cultural_landmark", "historical_place", "historical_landmark",
    "observation_deck", "place_of_worship", "church", "buddhist_temple",
    "performing_arts_theater", "concert_hall", "auditorium",
    "park", "city_park", "botanical_garden", "hiking_area", "nature_preserve",
    "national_park", "amusement_park", "zoo", "aquarium", "convention_center",
}

SHOPPING_TYPES: Set[str] = {
    "clothing_store", "shopping_mall", "cosmetics_store", "jewelry_store",
    "electronics_store", "book_store", "gift_shop", "market",
    "womens_clothing_store", "shoe_store", "sporting_goods_store",
    "sportswear_store", "department_store", "store", "food_store",
    "convenience_store", "supermarket", "grocery_store", "wholesaler",
    "home_goods_store", "liquor_store", "florist", "farmers_market",
}

ACTIVITY_TYPES: Set[str] = {
    "karaoke", "amusement_center", "video_arcade", "indoor_playground",
    "playground", "bowling_alley", "sports_activity_location", "sports_complex",
    "sports_club", "live_music_venue", "movie_theater", "event_venue",
    "barbecue_area",
}


# 그룹 이름 상수 (외부에서 참조 시 오타 방지)
GROUP_MEAL = "meal"
GROUP_CAFE = "cafe"
GROUP_ATTRACTION = "attraction"
GROUP_SHOPPING = "shopping"
GROUP_NIGHTLIFE = "nightlife"
GROUP_ACTIVITY = "activity"
GROUP_OTHER = "other"

GROUPS: List[str] = [
    GROUP_MEAL, GROUP_CAFE, GROUP_ATTRACTION,
    GROUP_SHOPPING, GROUP_NIGHTLIFE, GROUP_ACTIVITY,
]


# ──────────────────── 분류 ────────────────────


def classify(types: List[str]) -> str:
    """Google Places types 배열 → 6개 그룹 중 하나 (or 'other').

    분류 우선순위는 모듈 docstring 참고.
    """
    type_set = set(types)
    if type_set & NIGHTLIFE_TYPES:
        return GROUP_NIGHTLIFE
    if type_set & CAFE_TYPES:
        return GROUP_CAFE
    if any(t == "restaurant" or t.endswith("_restaurant") for t in type_set):
        return GROUP_MEAL
    if type_set & ATTRACTION_TYPES:
        return GROUP_ATTRACTION
    if type_set & ACTIVITY_TYPES:
        return GROUP_ACTIVITY
    if type_set & SHOPPING_TYPES:
        return GROUP_SHOPPING
    return GROUP_OTHER


# ──────────────────── 그룹별 cap (균형 분배) ────────────────────


# 기본 cap (스타일 무관) — 합 67
BASE_CAPS: Dict[str, int] = {
    GROUP_MEAL: 25,
    GROUP_CAFE: 12,
    GROUP_ATTRACTION: 12,
    GROUP_SHOPPING: 8,
    GROUP_NIGHTLIFE: 6,
    GROUP_ACTIVITY: 4,
}

# 스타일별 boost — 다중 선택 시 합산
STYLE_BOOSTS: Dict[str, Dict[str, int]] = {
    "food_tour":          {GROUP_MEAL: 10, GROUP_CAFE: 3},
    "shopping":           {GROUP_SHOPPING: 10},
    "culture_history":    {GROUP_ATTRACTION: 10},
    "photo_aesthetic":    {GROUP_CAFE: 5, GROUP_ATTRACTION: 5},
    "healing":            {GROUP_CAFE: 3, GROUP_ATTRACTION: 5},
    "famous_attractions": {GROUP_ATTRACTION: 10, GROUP_SHOPPING: 3},
    "activity":           {GROUP_NIGHTLIFE: 3, GROUP_ACTIVITY: 10},
    "festival_event":     {GROUP_ATTRACTION: 5, GROUP_NIGHTLIFE: 3, GROUP_ACTIVITY: 5},
}

# 후보 풀 hard cap (LLM 토큰 부담 방지)
HARD_CAP: int = 80


def compute_caps(styles: List[str]) -> Dict[str, int]:
    """선택된 styles에 따라 그룹별 cap을 계산.

    - 기본 cap에 스타일별 boost를 합산.
    - 합이 HARD_CAP을 초과하면 비례 축소 (각 그룹 최소 1 보장).
    """
    caps: Dict[str, int] = dict(BASE_CAPS)
    for s in styles:
        for g, boost in STYLE_BOOSTS.get(s, {}).items():
            caps[g] = caps.get(g, 0) + boost

    total = sum(caps.values())
    if total > HARD_CAP:
        scale = HARD_CAP / total
        caps = {g: max(1, int(round(n * scale))) for g, n in caps.items()}

    return caps
