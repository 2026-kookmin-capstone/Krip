import {
  API_BASE_URL,
  TOUR_PLACES_AUTHORIZATION_BEARER,
} from "./auth/config";

export const BRAND = "#01C0C0";
export const ACCENT = "#FFBE0F";
export const AI_PLAN_STORAGE_KEY = "krip-ai-trip-preferences";
export const SAVED_PLANS_STORAGE_KEY = "krip-saved-trip-plans";
export const SAVED_PLANS_EVENT = "krip:saved-plans-updated";
export const DEFAULT_MAP_CENTER = { lat: 37.5665, lng: 126.978 };
export const INCHEON_AIRPORT_CENTER = { lat: 37.4602, lng: 126.4407 };
export const SEOUL_SHILLA_HOTEL_CENTER = { lat: 37.5564, lng: 127.0056 };

export type PaceOption = "Slow" | "Balanced" | "Packed";
export type TransportOption = "Public Transit" | "Taxi" | "Walk";
export type CompanionOption = "Solo" | "Friends" | "Family" | "Couple";
export type BudgetCategory = "Low" | "Moderate" | "High";
export type PlannerMode = "ai" | "manual";

type SelectableValue<T extends string> = T | "";

export interface AiPreferenceState {
  departure: string;
  arrival: string;
  styles: string[];
  pace: SelectableValue<PaceOption>;
  extraPlace: string;
  transport: SelectableValue<TransportOption>;
  startTime: string;
  endTime: string;
  companion: SelectableValue<CompanionOption>;
  budgetValue: number;
  budgetCategory: BudgetCategory;
  foodNeed: string;
  durationDays: number;
  days?: AiPlanDayInput[];
  additionalPlaceId?: string | null;
  additionalPlaceName?: string;
}

export interface AiRouteStop {
  id: string;
  name: string;
  category: string;
  summary: string;
  address: string;
  latitude?: number;
  longitude?: number;
  keyword: string;
  timeLabel?: string;
  day?: number;
  order?: number;
  clusterName?: string;
  tip?: string;
  rating?: number | null;
  eventType?: "start" | "place" | "meal" | "return" | "airport" | "required";
}

export interface SavedManualStop {
  plannedId: string;
  id: string;
  name: string;
  category: string;
  summary: string;
  address: string;
  rating?: number;
  visitDate: string;
  visitTime: string;
  durationMinutes: number;
  note: string;
  latitude?: number;
  longitude?: number;
}

export interface SavedTripPlan {
  id: string;
  type: PlannerMode;
  title: string;
  summary: string;
  updatedAt: string;
  aiPreferences?: AiPreferenceState;
  aiRouteStops?: AiRouteStop[];
  manualStartDate?: string;
  manualEndDate?: string;
  manualStops?: SavedManualStop[];
}

export interface TourRecommendRequest {
  travel_days: number;
  travel_style: "맛집 탐방" | "쇼핑" | "문화/역사" | "카페" | "자연/공원";
  budget: "저예산" | "중간" | "고예산";
  companion_type: "혼자" | "연인" | "친구" | "가족";
  schedule_density: "빽빽하게" | "널널하게";
}

export interface TourRecommendPlace {
  place_id: string;
  display_name: string;
  category: string;
  address: string;
  location?: {
    lat?: number;
    lng?: number;
  } | null;
  rating?: number | null;
  description?: string;
  tip?: string;
}

export interface TourRecommendDayPlan {
  day: number;
  cluster_name: string;
  places: TourRecommendPlace[];
}

export interface TourRecommendResponse {
  tour_plan: TourRecommendDayPlan[];
}
export interface AiPlanDayInput {
  departureCluster: string;
  arrivalCluster: string;
  startTime: string;
  endTime: string;
  additionalPlaceId: string | null;
}

export type FoodPreferenceCode = "halal" | "vegetarian" | "any";
export type TransportCode = "public_transport";
export type ScheduleDensityCode = "relaxed" | "packed";
export type CompanionCode =
  | "solo"
  | "couple"
  | "spouse"
  | "friends_colleagues"
  | "family_parents"
  | "family_with_kids";
export type StyleCode =
  | "activity"
  | "famous_attractions"
  | "healing"
  | "culture_history"
  | "shopping"
  | "food_tour"
  | "photo_aesthetic"
  | "festival_event";

export interface TourDayRequestV2 {
  departure_cluster: string;
  arrival_cluster: string;
  additional_place_id: string | null;
  transport: TransportCode;
  start_time: string;
  end_time: string;
  companion: CompanionCode;
  budget_per_person_krw: number;
  styles: StyleCode[];
  schedule_density: ScheduleDensityCode;
}

export interface TourRecommendRequestV2 {
  travel_days: number;
  food_preference: FoodPreferenceCode;
  days: TourDayRequestV2[];
}

export interface TimelineSlotV2 {
  time: string;
  place_id: string;
  title: string;
}

export interface PlaceDetailV2 {
  place_id: string;
  display_name: string;
  category: string;
  address: string;
  location: { lat: number; lng: number };
  rating: number | null;
  reason: string;
  estimated_cost_krw: number;
  stay_minutes: number;
}

export interface MovementHopV2 {
  from_place: string;
  to_place: string;
  method: string;
}

export interface BudgetItemV2 {
  label: string;
  amount_krw: number;
}

export interface TourDayResponseV2 {
  day: number;
  timeline: TimelineSlotV2[];
  places: PlaceDetailV2[];
  movements: MovementHopV2[];
  budget_breakdown: BudgetItemV2[];
  budget_total_krw: number;
  summary: string;
}

export interface TourRecommendResponseV2 {
  tour_plan: TourDayResponseV2[];
}

export const defaultPreferences: AiPreferenceState = {
  departure: "",
  arrival: "",
  styles: [],
  pace: "",
  extraPlace: "",
  transport: "",
  startTime: "10:00",
  endTime: "21:00",
  companion: "",
  budgetValue: 5,
  budgetCategory: "Low",
  foodNeed: "",
  durationDays: 1,
};

export const styleTokens = [
  "Experiences & Activities",
  "Hot Place",
  "Relaxation & Wellness",
  "Culture & History",
  "Festivals & Events",
  "Food Tours",
  "Shopping",
  "Photography & Aesthetics",
];

export const paceOptions: PaceOption[] = ["Slow", "Packed"];
export const transportOptions: TransportOption[] = [
  "Public Transit",
  "Taxi",
  "Walk",
];
export const companionOptions: CompanionOption[] = [
  "Solo",
  "Friends",
  "Family",
  "Couple",
];
export const foodNeeds = ["Halal Food", "Vegan"];
export const durationOptions = [1, 2, 3];
export const seoulClusterKeys = [
  "Myeongdong / Euljiro",
  "Gangnam Station",
  "Hongdae / Hapjeong",
  "Itaewon",
  "Jamsil",
  "Konkuk Univ. Station (Kondae)",
  "Sinchon / Yonsei Univ.",
  "Jongno / Insadong",
  "Yeouido",
  "Seongsu-dong",
  "Mangwon / Yeonnam-dong",
  "Euljiro 3-ga / Chungmuro",
  "Apgujeong / Cheongdam",
  "Garosu-gil (Sinsa)",
  "Bukchon / Samcheong-dong",
  "Gwangjang Market / Dongdaemun",
  "Yongsan / Haebangchon (HBC)",
  "Hannam-dong",
  "Mullae-dong",
  "Songridan-gil (Songpa)",
  "Seoul Forest / Ttukseom",
  "Mapo / Gongdeok",
  "Nakseongdae / Sharosu-gil",
  "Hyehwa / Daehangno",
  "Hoegi / Kyung Hee Univ.",
  "Noryangjin / Dongjak",
  "Wangsimni / Sangwangsimni",
  "Dosan Park / Hak-dong",
  "Samseong / COEX",
  "Bangbae / Seorae Village",
  "Sangsu-dong",
  "Ikseon-dong",
  "Banpo Hangang Park",
  "N Seoul Tower Area (Namsan)",
  "DDP / Dongdaemun",
  "Seongbuk-dong",
  "Yeonhui-dong",
  "Ssangmun / Suyu",
];

export function getAiPlanDayInputs(value: AiPreferenceState): AiPlanDayInput[] {
  const travelDays = Math.max(1, Math.min(3, value.durationDays || 1));
  const existing = Array.isArray(value.days) ? value.days : [];
  const defaultCluster = seoulClusterKeys[0];

  return Array.from({ length: travelDays }, (_, index) => ({
    departureCluster:
      existing[index]?.departureCluster || value.departure || defaultCluster,
    arrivalCluster:
      existing[index]?.arrivalCluster || value.arrival || defaultCluster,
    startTime: existing[index]?.startTime || value.startTime || "10:00",
    endTime: existing[index]?.endTime || value.endTime || "21:00",
    additionalPlaceId:
      existing[index]?.additionalPlaceId ?? value.additionalPlaceId ?? null,
  }));
}

export function toFoodPreferenceCode(value: AiPreferenceState): FoodPreferenceCode {
  if (value.foodNeed === "Halal Food") return "halal";
  if (value.foodNeed === "Vegan") return "vegetarian";
  return "any";
}

export function toCompanionCode(value: AiPreferenceState): CompanionCode {
  if (value.companion === "Couple") return "couple";
  if (value.companion === "Friends") return "friends_colleagues";
  if (value.companion === "Family") return "family_parents";
  return "solo";
}

export function toScheduleDensityCode(
  pace: AiPreferenceState["pace"]
): ScheduleDensityCode {
  return pace === "Packed" ? "packed" : "relaxed";
}

export function toStyleCode(token: string): StyleCode {
  const normalized = token.toLowerCase();
  if (normalized.includes("food")) return "food_tour";
  if (normalized.includes("shopping")) return "shopping";
  if (normalized.includes("culture") || normalized.includes("history")) return "culture_history";
  if (normalized.includes("relaxation") || normalized.includes("wellness")) return "healing";
  if (normalized.includes("festival") || normalized.includes("event")) return "festival_event";
  if (normalized.includes("photo") || normalized.includes("aesthetic")) return "photo_aesthetic";
  if (normalized.includes("hot")) return "famous_attractions";
  return "activity";
}

export function toStyleCodes(styles: string[]): StyleCode[] {
  const unique = Array.from(new Set(styles.map(toStyleCode)));
  return unique.length > 0 ? unique : ["activity"];
}

export function toRecommendRequestV2(
  preferences: AiPreferenceState
): TourRecommendRequestV2 {
  const days = getAiPlanDayInputs(preferences);
  const styles = toStyleCodes(preferences.styles);

  return {
    travel_days: days.length,
    food_preference: toFoodPreferenceCode(preferences),
    days: days.map((day) => ({
      departure_cluster: day.departureCluster,
      arrival_cluster: day.arrivalCluster,
      additional_place_id: day.additionalPlaceId || null,
      transport: "public_transport",
      start_time: day.startTime,
      end_time: day.endTime,
      companion: toCompanionCode(preferences),
      budget_per_person_krw: Math.max(0, Math.round(preferences.budgetValue * 10000)),
      styles,
      schedule_density: toScheduleDensityCode(preferences.pace),
    })),
  };
}

export async function getTourRecommendationsV2(
  preferences: AiPreferenceState,
  timeoutMs = 120000
): Promise<TourRecommendResponseV2> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/tour/recommend`, {
      method: "POST",
      credentials: "include",
      signal: controller.signal,
      headers: {
        Authorization: TOUR_PLACES_AUTHORIZATION_BEARER,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(toRecommendRequestV2(preferences)),
    });

    if (!response.ok) {
      let detail = "Failed to load recommended tour plan.";

      try {
        const data = (await response.json()) as { detail?: unknown; message?: unknown };
        const message = data.detail || data.message;
        detail = typeof message === "string" ? message : detail;
      } catch {
        // Keep default message for non-JSON responses.
      }

      const error = new Error(detail) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }

    const data = (await response.json()) as Partial<TourRecommendResponseV2>;
    return {
      tour_plan: Array.isArray(data.tour_plan) ? data.tour_plan : [],
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

export function flattenRecommendedPlacesV2(
  response: TourRecommendResponseV2 | null
): PlaceDetailV2[] {
  const seen = new Set<string>();
  const places: PlaceDetailV2[] = [];

  response?.tour_plan.forEach((day) => {
    day.places.forEach((place) => {
      if (!seen.has(place.place_id)) {
        seen.add(place.place_id);
        places.push(place);
      }
    });
  });

  return places;
}

export function placeDetailToRouteStop(
  place: PlaceDetailV2,
  day: number,
  index: number
): AiRouteStop {
  return {
    id: place.place_id,
    name: place.display_name,
    category: place.category,
    summary: place.reason,
    address: place.address,
    latitude: place.location?.lat,
    longitude: place.location?.lng,
    keyword: place.category,
    day,
    order: index + 1,
    rating: place.rating,
    eventType: "place",
  };
}

export function tourPlanV2ToRouteStops(
  response: TourRecommendResponseV2 | null
): AiRouteStop[] {
  return response
    ? response.tour_plan.flatMap((day) =>
        day.places.map((place, index) => placeDetailToRouteStop(place, day.day, index))
      )
    : [];
}

export function formatKrw(value: number): string {
  if (!value) return "₩—";
  return `₩${value.toLocaleString()}`;
}

export function budgetCategoryFromValue(value: number): BudgetCategory {
  if (value <= 170) return "Low";
  if (value >= 335) return "High";
  return "Moderate";
}

export function budgetCategoryLabel(category: BudgetCategory): string {
  if (category === "Low") return "Low Budget";
  if (category === "High") return "High Budget";
  return "Moderate Budget";
}

export function budgetCategoryIcon(category: BudgetCategory): string {
  if (category === "Low") return "$";
  if (category === "High") return "$$$";
  return "$$";
}

export function formatBudgetValue(value: number): string {
  return (value * 10000).toLocaleString();
}

export function clonePreferences(
  value?: Partial<AiPreferenceState> | null
): AiPreferenceState {
  const budgetValue =
    typeof value?.budgetValue === "number"
      ? value.budgetValue
      : defaultPreferences.budgetValue;

  return {
    ...defaultPreferences,
    ...value,
    styles:
      Array.isArray(value?.styles) && value.styles.length > 0 ? value.styles : [],
    budgetValue,
    budgetCategory: budgetCategoryFromValue(budgetValue),
  };
}

export function loadPreferences(): AiPreferenceState {
  if (typeof window === "undefined") return defaultPreferences;

  try {
    const raw = window.localStorage.getItem(AI_PLAN_STORAGE_KEY);
    if (!raw) return defaultPreferences;
    return clonePreferences(JSON.parse(raw) as Partial<AiPreferenceState>);
  } catch {
    return defaultPreferences;
  }
}

export function savePreferences(value: AiPreferenceState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AI_PLAN_STORAGE_KEY, JSON.stringify(value));
}

export function clearPreferences(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AI_PLAN_STORAGE_KEY);
}

export function buildPlanTitle(mode: PlannerMode, seed?: string): string {
  const fallback = mode === "ai" ? "AI Trip Plan" : "Manual Trip Plan";
  const trimmed = seed?.trim();
  return trimmed ? trimmed : fallback;
}

export function loadSavedPlans(): SavedTripPlan[] {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(SAVED_PLANS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedTripPlan[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSavedPlans(plans: SavedTripPlan[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SAVED_PLANS_STORAGE_KEY, JSON.stringify(plans));
  window.dispatchEvent(new CustomEvent(SAVED_PLANS_EVENT));
}

export function getSavedPlanById(
  planId: string | null | undefined
): SavedTripPlan | null {
  if (!planId) return null;
  return loadSavedPlans().find((plan) => plan.id === planId) || null;
}

export function upsertSavedPlan(
  plan: Omit<SavedTripPlan, "id" | "updatedAt"> & { id?: string }
): SavedTripPlan {
  const currentPlans = loadSavedPlans();
  const nextPlan: SavedTripPlan = {
    ...plan,
    id: plan.id || createPlanId(plan.type),
    updatedAt: new Date().toISOString(),
  };

  const nextPlans = [
    nextPlan,
    ...currentPlans.filter((item) => item.id !== nextPlan.id),
  ];

  persistSavedPlans(nextPlans);
  return nextPlan;
}

export function removeSavedPlan(planId: string): void {
  const currentPlans = loadSavedPlans();
  persistSavedPlans(currentPlans.filter((plan) => plan.id !== planId));
}

export function createPlanId(mode: PlannerMode): string {
  return `${mode}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createAiSummary(
  preferences: AiPreferenceState,
  stopCount: number
): string {
  const activeStyles =
    preferences.styles.length > 0 ? preferences.styles.join(", ") : "no style selected";
  const budgetLabel = budgetCategoryLabel(preferences.budgetCategory);
  return `This is a ${budgetLabel.toLowerCase()} itinerary connecting ${stopCount} locations, based on ${activeStyles}`;
}

export function timeToMinutes(value: string): number {
  const [hours, minutes] = value.split(":").map(Number);
  return (Number.isFinite(hours) ? hours : 0) * 60 + (Number.isFinite(minutes) ? minutes : 0);
}

export function minutesToTime(totalMinutes: number): string {
  const normalized = Math.max(0, Math.min(23 * 60 + 59, Math.round(totalMinutes)));
  const hours = Math.floor(normalized / 60).toString().padStart(2, "0");
  const minutes = (normalized % 60).toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}

export function roundDownToUnit(minutes: number, unitMinutes: number): number {
  return Math.floor(minutes / unitMinutes) * unitMinutes;
}

export function roundUpToUnit(minutes: number, unitMinutes: number): number {
  return Math.ceil(minutes / unitMinutes) * unitMinutes;
}

export function toRecommendRequest(
  preferences: AiPreferenceState
): TourRecommendRequest {
  return {
    travel_days: Math.max(1, Math.min(3, preferences.durationDays || 1)),
    travel_style: toRecommendTravelStyle(preferences.styles),
    budget: toRecommendBudget(preferences.budgetCategory),
    companion_type: toRecommendCompanion(preferences.companion),
    schedule_density: toRecommendDensity(preferences.pace),
  };
}

export function toRecommendDensity(
  pace: AiPreferenceState["pace"]
): TourRecommendRequest["schedule_density"] {
  return pace === "Packed" ? "빽빽하게" : "널널하게";
}

export function getScheduleItemTargetCount(
  pace: AiPreferenceState["pace"]
): number {
  if (pace === "Packed") return 9;
  if (pace === "Balanced") return 7;
  return 5;
}

function toRecommendTravelStyle(
  styles: string[]
): TourRecommendRequest["travel_style"] {
  const normalized = styles.join(" ").toLowerCase();
  if (normalized.includes("food")) return "맛집 탐방";
  if (normalized.includes("shopping")) return "쇼핑";
  if (normalized.includes("culture") || normalized.includes("history")) return "문화/역사";
  if (normalized.includes("relaxation") || normalized.includes("nature")) return "자연/공원";
  return "카페";
}

function toRecommendBudget(
  budget: BudgetCategory
): TourRecommendRequest["budget"] {
  if (budget === "Low") return "저예산";
  if (budget === "High") return "고예산";
  return "중간";
}

function toRecommendCompanion(
  companion: AiPreferenceState["companion"]
): TourRecommendRequest["companion_type"] {
  if (companion === "Couple") return "연인";
  if (companion === "Friends") return "친구";
  if (companion === "Family") return "가족";
  return "혼자";
}

export async function getTourRecommendations(
  preferences: AiPreferenceState
): Promise<TourRecommendResponse> {
  return postTourRecommend(toRecommendRequest(preferences));
}

export async function postTourRecommend(
  payload: TourRecommendRequest
): Promise<TourRecommendResponse> {
  const response = await fetch(`${API_BASE_URL}/api/tour/recommend`, {
    method: "POST",
    credentials: "include",
    headers: {
      Authorization: TOUR_PLACES_AUTHORIZATION_BEARER,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = "Failed to load recommended tour plan.";

    try {
      const data = (await response.json()) as { detail?: unknown; message?: unknown };
      const message = data.detail || data.message;
      detail = typeof message === "string" ? message : detail;
    } catch {
      // Keep default message for non-JSON responses.
    }

    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  const data = (await response.json()) as unknown;
  const payloadData = data as Partial<TourRecommendResponse>;
  return {
    tour_plan: Array.isArray(payloadData.tour_plan) ? payloadData.tour_plan : [],
  };
}

export function flattenRecommendedPlaces(
  response: TourRecommendResponse
): TourRecommendPlace[] {
  return response.tour_plan.flatMap((day) =>
    Array.isArray(day.places) ? day.places : []
  );
}

export function normalizePlaceKey(value: string): string {
  return value.toLowerCase().replace(/\s+/g, "").trim();
}

export function inferExtraPlaceCategory(value: string): string | null {
  const normalized = normalizePlaceKey(value);
  if (normalized.includes("cafe") || normalized.includes("카페")) return "카페";
  if (normalized.includes("shopping") || normalized.includes("쇼핑")) return "쇼핑";
  if (normalized.includes("food") || normalized.includes("맛집")) return "맛집 탐방";
  if (normalized.includes("culture") || normalized.includes("history") || normalized.includes("문화") || normalized.includes("역사")) {
    return "문화/역사";
  }
  if (normalized.includes("park") || normalized.includes("nature") || normalized.includes("자연") || normalized.includes("공원")) {
    return "자연/공원";
  }
  return null;
}

let googleMapsPromise: Promise<typeof window.google | null> | null = null;

export async function loadGoogleMapsApi(): Promise<typeof window.google | null> {
  if (typeof window === "undefined") return null;
  if (window.google?.maps) return window.google;
  if (googleMapsPromise) return googleMapsPromise;

  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
  if (!apiKey) return null;

  googleMapsPromise = new Promise((resolve, reject) => {
    const callbackHost = window as unknown as Record<string, unknown>;
    const previousAuthFailure = callbackHost.gm_authFailure;
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-google-maps-sdk="true"]'
    );

    callbackHost.gm_authFailure = () => {
      if (typeof previousAuthFailure === "function") {
        previousAuthFailure();
      }
      reject(new Error("Google Maps API key is not authorized for this origin."));
    };

    if (existing) {
      if (window.google?.maps) {
        resolve(window.google);
        return;
      }

      const readyState = existing.dataset.loaded;
      if (readyState === "error") {
        reject(new Error("Google Maps SDK load failed"));
        return;
      }

      const onLoad = () => resolve(window.google || null);
      const onError = () => reject(new Error("Google Maps SDK load failed"));
      existing.addEventListener("load", onLoad, { once: true });
      existing.addEventListener("error", onError, { once: true });

      window.setTimeout(() => {
        if (window.google?.maps) {
          resolve(window.google);
        }
      }, 1500);
      return;
    }

    const callbackName = "__kripGoogleMapsInit";
    const script = document.createElement("script");
    script.async = true;
    script.defer = true;
    script.dataset.googleMapsSdk = "true";
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${apiKey}&v=weekly&loading=async&callback=${callbackName}`;

    callbackHost[callbackName] = () => {
      script.dataset.loaded = "true";
      resolve(window.google || null);
      delete callbackHost[callbackName];
      if (previousAuthFailure) {
        callbackHost.gm_authFailure = previousAuthFailure;
      } else {
        delete callbackHost.gm_authFailure;
      }
    };

    script.onerror = () => {
      script.dataset.loaded = "error";
      reject(new Error("Google Maps SDK load failed"));
      delete callbackHost[callbackName];
      if (previousAuthFailure) {
        callbackHost.gm_authFailure = previousAuthFailure;
      } else {
        delete callbackHost.gm_authFailure;
      }
    };

    document.head.appendChild(script);
  }).catch((error) => {
    googleMapsPromise = null;
    throw error;
  });

  return googleMapsPromise;
}




