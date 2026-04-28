export const BRAND = "#01C0C0";
export const ACCENT = "#FFBE0F";
export const AI_PLAN_STORAGE_KEY = "krip-ai-trip-preferences";
export const SAVED_PLANS_STORAGE_KEY = "krip-saved-trip-plans";
export const SAVED_PLANS_EVENT = "krip:saved-plans-updated";
export const DEFAULT_MAP_CENTER = { lat: 37.5665, lng: 126.978 };

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

export const paceOptions: PaceOption[] = ["Slow", "Balanced", "Packed"];
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
export const foodNeeds = [
  "Halal Food",
  "Vegan",
];
export const durationOptions = [1, 2, 3];

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
  if (typeof window === "undefined") {
    return defaultPreferences;
  }

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

export function distributeTimeLabels(
  startTime: string,
  endTime: string,
  itemCount: number
): string[] {
  if (itemCount <= 0) return [];

  const [startHours, startMinutes] = startTime.split(":").map(Number);
  const [endHours, endMinutes] = endTime.split(":").map(Number);

  const startTotal = (startHours || 0) * 60 + (startMinutes || 0);
  const endTotal = (endHours || 0) * 60 + (endMinutes || 0);
  const usableEnd = endTotal > startTotal ? endTotal : startTotal + 60;
  const step = itemCount === 1 ? 0 : (usableEnd - startTotal) / (itemCount - 1);

  return Array.from({ length: itemCount }, (_, index) => {
    const totalMinutes = Math.round(startTotal + step * index);
    const hours = Math.floor(totalMinutes / 60)
      .toString()
      .padStart(2, "0");
    const minutes = (totalMinutes % 60).toString().padStart(2, "0");
    return `${hours}:${minutes}`;
  });
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
