import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { API_BASE_URL, TOUR_PLACES_AUTHORIZATION_BEARER } from "../../api/auth/config";
import {
  ACCENT,
  BRAND,
  buildPlanTitle,
  budgetCategoryLabel,
  getSavedPlanById,
  loadGoogleMapsApi,
  upsertSavedPlan,
  type AiPreferenceState,
  type AiRouteStop,
} from "../../api/aiPlanShared";

declare global {
  interface Window {
    google?: {
      maps?: {
        Map: new (element: HTMLElement, options: Record<string, unknown>) => GoogleMap;
        Marker: new (options: Record<string, unknown>) => GoogleMarker;
        Polyline: new (options: Record<string, unknown>) => GooglePolyline;
        LatLngBounds: new () => GoogleLatLngBounds;
      };
    };
  }
}

interface GoogleMap {
  fitBounds: (bounds: GoogleLatLngBounds) => void;
}

interface GoogleMarker {
  setMap: (map: GoogleMap | null) => void;
}

interface GooglePolyline {
  setMap: (map: GoogleMap | null) => void;
}

interface GoogleLatLngBounds {
  extend: (position: { lat: number; lng: number }) => void;
}

interface AiPlanResultPageProps {
  preferences: AiPreferenceState;
  onBack: () => void;
  onEdit: () => void;
}

interface AiPlanDayInput {
  departureCluster: string;
  arrivalCluster: string;
  startTime: string;
  endTime: string;
  additionalPlaceId: string | null;
}

type AiPreferenceStateV2 = AiPreferenceState & {
  days?: AiPlanDayInput[];
  additionalPlaceId?: string | null;
  additionalPlaceName?: string;
};

type FoodPreference = "halal" | "vegetarian" | "any";
type StyleCode =
  | "activity"
  | "famous_attractions"
  | "healing"
  | "culture_history"
  | "shopping"
  | "food_tour"
  | "photo_aesthetic"
  | "festival_event";

type CompanionCode =
  | "solo"
  | "couple"
  | "spouse"
  | "friends_colleagues"
  | "family_parents"
  | "family_with_kids";

interface TourRecommendV2Request {
  travel_days: number;
  food_preference: FoodPreference;
  days: Array<{
    departure_cluster: string;
    arrival_cluster: string;
    additional_place_id: string | null;
    transport: "public_transport";
    start_time: string;
    end_time: string;
    companion: CompanionCode;
    budget_per_person_krw: number;
    styles: StyleCode[];
    schedule_density: "relaxed" | "packed";
  }>;
}

interface TimelineSlot {
  time: string;
  place_id: string;
  title: string;
}

interface PlaceDetail {
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

interface MovementHop {
  from_place: string;
  to_place: string;
  method: string;
}

interface BudgetItem {
  label: string;
  amount_krw: number;
}

interface TourDayResponse {
  day: number;
  timeline: TimelineSlot[];
  places: PlaceDetail[];
  movements: MovementHop[];
  budget_breakdown: BudgetItem[];
  budget_total_krw: number;
  summary: string;
}

interface TourRecommendV2Response {
  tour_plan: TourDayResponse[];
}

const DEFAULT_CLUSTER = "Myeongdong / Euljiro";

function readPlanId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("planId");
}

function toPlanValue(value: AiPreferenceState): AiPreferenceStateV2 {
  return value as AiPreferenceStateV2;
}

function getDayInputs(value: AiPreferenceStateV2): AiPlanDayInput[] {
  const travelDays = Math.max(1, Math.min(3, value.durationDays || 1));
  const existing = Array.isArray(value.days) ? value.days : [];

  return Array.from({ length: travelDays }, (_, index) => ({
    departureCluster:
      existing[index]?.departureCluster || value.departure || DEFAULT_CLUSTER,
    arrivalCluster:
      existing[index]?.arrivalCluster || value.arrival || DEFAULT_CLUSTER,
    startTime: existing[index]?.startTime || value.startTime || "10:00",
    endTime: existing[index]?.endTime || value.endTime || "21:00",
    additionalPlaceId:
      existing[index]?.additionalPlaceId ?? value.additionalPlaceId ?? null,
  }));
}

function mapFoodPreference(value: AiPreferenceState): FoodPreference {
  if (value.foodNeed === "Halal Food") return "halal";
  if (value.foodNeed === "Vegan") return "vegetarian";
  return "any";
}

function mapCompanion(value: AiPreferenceState): CompanionCode {
  if (value.companion === "Couple") return "couple";
  if (value.companion === "Friends") return "friends_colleagues";
  if (value.companion === "Family") return "family_parents";
  return "solo";
}

function mapStyle(token: string): StyleCode {
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

function uniqueStyles(styles: string[]): StyleCode[] {
  const mapped = styles.map(mapStyle);
  const unique = Array.from(new Set(mapped));
  return unique.length > 0 ? unique : ["activity"];
}

function buildRecommendRequest(preferences: AiPreferenceState): TourRecommendV2Request {
  const planValue = toPlanValue(preferences);
  const days = getDayInputs(planValue);
  const styles = uniqueStyles(preferences.styles);

  return {
    travel_days: days.length,
    food_preference: mapFoodPreference(preferences),
    days: days.map((day) => ({
      departure_cluster: day.departureCluster,
      arrival_cluster: day.arrivalCluster,
      additional_place_id: day.additionalPlaceId || null,
      transport: "public_transport",
      start_time: day.startTime,
      end_time: day.endTime,
      companion: mapCompanion(preferences),
      budget_per_person_krw: Math.max(0, Math.round(preferences.budgetValue * 10000)),
      styles,
      schedule_density: preferences.pace === "Packed" ? "packed" : "relaxed",
    })),
  };
}

async function getTourRecommendationsV2(
  preferences: AiPreferenceState
): Promise<TourRecommendV2Response> {
  const response = await fetch(`${API_BASE_URL}/api/tour/recommend`, {
      method: "POST",
      credentials: "include",
      headers: {
        Authorization: TOUR_PLACES_AUTHORIZATION_BEARER,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildRecommendRequest(preferences)),
    });

    if (!response.ok) {
      let detail = "Failed to load recommended tour plan.";
      try {
        const data = (await response.json()) as { detail?: unknown; message?: unknown };
        const message = data.detail || data.message;
        detail = typeof message === "string" ? message : detail;
      } catch {
        // Keep default message.
      }
      const error = new Error(detail) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }

    const payload = (await response.json()) as Partial<TourRecommendV2Response>;
    return {
      tour_plan: Array.isArray(payload.tour_plan) ? payload.tour_plan : [],
    };
}

function buildRouteTitle(preferences: AiPreferenceState): string {
  const planValue = toPlanValue(preferences);
  const days = getDayInputs(planValue);
  return buildPlanTitle(
    "ai",
    `${days[0]?.departureCluster || "Seoul"} to ${days[days.length - 1]?.arrivalCluster || "Seoul"}`
  );
}

function formatKrw(value: number): string {
  if (!value) return "₩—";
  return `₩${value.toLocaleString()}`;
}

function flattenPlaces(plan: TourRecommendV2Response | null): PlaceDetail[] {
  const seen = new Set<string>();
  const places: PlaceDetail[] = [];

  plan?.tour_plan.forEach((day) => {
    day.places.forEach((place) => {
      if (!seen.has(place.place_id)) {
        seen.add(place.place_id);
        places.push(place);
      }
    });
  });

  return places;
}

function placeToRouteStop(place: PlaceDetail, day: number, index: number): AiRouteStop {
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

function toRouteStops(plan: TourRecommendV2Response | null): AiRouteStop[] {
  return plan
    ? plan.tour_plan.flatMap((day) =>
        day.places.map((place, index) => placeToRouteStop(place, day.day, index))
      )
    : [];
}

function getPlaceMap(day: TourDayResponse): Map<string, PlaceDetail> {
  return new Map(day.places.map((place) => [place.place_id, place]));
}

function GoogleMapPreview({ places }: { places: PlaceDetail[] }) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");

  const positionedPlaces = useMemo(
    () =>
      places.filter(
        (place) =>
          typeof place.location?.lat === "number" &&
          typeof place.location?.lng === "number"
      ),
    [places]
  );

  useEffect(() => {
    let markers: GoogleMarker[] = [];
    let polyline: GooglePolyline | null = null;
    let cancelled = false;

    if (!mapRef.current || positionedPlaces.length === 0) {
      setMapReady(false);
      setMapError("");
      return undefined;
    }

    void loadGoogleMapsApi()
      .then((google) => {
        if (cancelled || !google?.maps || !mapRef.current) return;

        try {
          const map = new google.maps.Map(mapRef.current, {
            center: positionedPlaces[0].location,
            zoom: 12,
            disableDefaultUI: true,
            zoomControl: true,
            mapId: "d67e58693d403acacaa713aa",
          });

          const bounds = new google.maps.LatLngBounds();
          positionedPlaces.forEach((place, index) => {
            const position = place.location;
            bounds.extend(position);
            markers.push(
              new google.maps.Marker({
                position,
                map,
                label: String(index + 1),
                title: place.display_name,
              })
            );
          });

          if (positionedPlaces.length > 1) {
            polyline = new google.maps.Polyline({
              path: positionedPlaces.map((place) => place.location),
              geodesic: true,
              strokeColor: BRAND,
              strokeOpacity: 0.9,
              strokeWeight: 3,
              map,
            });
          }

          map.fitBounds(bounds);
          setMapReady(true);
          setMapError("");
        } catch (error) {
          setMapReady(false);
          setMapError(error instanceof Error ? error.message : "Google Map could not be rendered.");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setMapReady(false);
          setMapError(error instanceof Error ? error.message : "Google Maps failed to load.");
        }
      });

    return () => {
      cancelled = true;
      markers.forEach((marker) => marker.setMap(null));
      polyline?.setMap(null);
    };
  }, [positionedPlaces]);

  const hasApiKey = Boolean(import.meta.env.VITE_GOOGLE_MAPS_API_KEY);

  return (
    <div style={styles.mapCard}>
      <div style={styles.mapViewport}>
        <div style={styles.mapCanvasGoogle} ref={mapRef} />
        {positionedPlaces.length === 0 ? (
          <div style={styles.mapEmpty}>Location coordinates will appear here when the API returns them.</div>
        ) : !hasApiKey ? (
          <div style={styles.mapEmpty}>Add `VITE_GOOGLE_MAPS_API_KEY` to render the live map.</div>
        ) : mapError ? (
          <div style={styles.mapEmpty}>{mapError}</div>
        ) : !mapReady ? (
          <div style={styles.mapEmpty}>Loading Google Map...</div>
        ) : null}
      </div>
      <div style={styles.mapLegend}>
        {positionedPlaces.map((place, index) => (
          <div key={place.place_id} style={styles.mapLegendItem}>
            <span style={styles.mapLegendIndex}>{index + 1}</span>
            <span style={styles.mapLegendText}>{place.display_name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingPlanScreen({
  progress,
  step,
  seconds,
}: {
  progress: number;
  step: string;
  seconds: number;
}) {
  return (
    <div style={styles.loadingScreen}>
      <div style={styles.loadingHero}>
        <span style={styles.loadingBadge}>AI is planning</span>
        <h2 style={styles.loadingTitle}>Creating your route</h2>
        <p style={styles.loadingCopy}>
          Recommendation may take a little while because the itinerary is generated day by day.
        </p>
        <div style={styles.progressTrack}>
          <div style={{ ...styles.progressFill, width: `${progress}%` }} />
        </div>
        <div style={styles.progressMeta}>
          <span>{step}</span>
          <strong>{Math.round(progress)}%</strong>
        </div>
      </div>
      <div style={styles.loadingSteps}>
        <div style={styles.loadingStepItem}>Preferences checked</div>
        <div style={styles.loadingStepItem}>Places and movement requested</div>
        <div style={styles.loadingStepItem}>Budget and timeline composing</div>
      </div>
      <p style={styles.loadingFooter}>{seconds}s elapsed</p>
    </div>
  );
}
export default function AiPlanResultPage({
  preferences,
  onBack,
}: AiPlanResultPageProps) {
  const [plan, setPlan] = useState<TourRecommendV2Response | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [loadingSeconds, setLoadingSeconds] = useState(0);

  const planId = useMemo(() => readPlanId(), []);
  useEffect(() => {
    if (!isLoading) {
      setLoadingSeconds(0);
      return undefined;
    }

    const interval = window.setInterval(() => {
      setLoadingSeconds((current) => current + 1);
    }, 1000);

    return () => window.clearInterval(interval);
  }, [isLoading]);

  const loadingProgress = Math.min(95, 12 + loadingSeconds * 2.2);
  const loadingStep =
    loadingSeconds < 8
      ? "Reading your travel preferences"
      : loadingSeconds < 20
        ? "Finding places that match your route"
        : loadingSeconds < 40
          ? "Arranging timeline, movement, and budget"
          : "Finalizing your Seoul itinerary";

  useEffect(() => {
    const savedPlan = getSavedPlanById(planId);
    if (savedPlan?.type === "ai" && savedPlan.aiRouteStops) {
      setPlan({
        tour_plan: [
          {
            day: 1,
            timeline: savedPlan.aiRouteStops.map((stop) => ({
              time: stop.timeLabel || "--:--",
              place_id: stop.id,
              title: stop.name,
            })),
            places: savedPlan.aiRouteStops.map((stop) => ({
              place_id: stop.id,
              display_name: stop.name,
              category: stop.category,
              address: stop.address,
              location: {
                lat: stop.latitude || 0,
                lng: stop.longitude || 0,
              },
              rating: stop.rating ?? null,
              reason: stop.summary,
              estimated_cost_krw: 0,
              stay_minutes: 60,
            })),
            movements: [],
            budget_breakdown: [],
            budget_total_krw: 0,
            summary: savedPlan.summary,
          },
        ],
      });
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setErrorMessage("");

    void getTourRecommendationsV2(preferences)
      .then((result) => {
        if (cancelled) return;
        setPlan(result);
      })
      .catch((error) => {
        if (cancelled) return;
        setPlan(null);
        setErrorMessage(
          error instanceof Error ? error.message : "Failed to load recommended plan."
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [planId, preferences]);

  const allPlaces = useMemo(() => flattenPlaces(plan), [plan]);
  const routeStops = useMemo(() => toRouteStops(plan), [plan]);
  const budgetTotal = plan?.tour_plan.reduce(
    (sum, day) => sum + day.budget_total_krw,
    0
  ) || 0;
  const budgetLimit = Math.max(0, preferences.budgetValue * 10000);
  const isOverBudget = budgetLimit > 0 && budgetTotal > budgetLimit;
  const summary = plan?.tour_plan.map((day) => day.summary).filter(Boolean).join(" ") ||
    `This itinerary uses ${routeStops.length} places returned by the recommendation API.`;


  if (isLoading) {
    return (
      <div style={styles.page}>
        <div style={styles.phoneFrame}>
          <div style={styles.headerRow}>
            <button type="button" onClick={onBack} style={styles.iconButton}>
              {"<"}
            </button>
            <span style={styles.headerBadge}>AI Result</span>
          </div>

          <div style={styles.titleBlock}>
            <span style={styles.eyebrow}>Recommendation API V2</span>
            <h1 style={styles.title}>Creating your itinerary</h1>
            <p style={styles.copy}>
              We are waiting for the recommendation server to finish the route.
            </p>
          </div>

          <LoadingPlanScreen
            progress={loadingProgress}
            step={loadingStep}
            seconds={loadingSeconds}
          />
        </div>
      </div>
    );
  }
  const handleSave = () => {
    const saved = upsertSavedPlan({
      id: planId || undefined,
      type: "ai",
      title: buildRouteTitle(preferences),
      summary,
      aiPreferences: preferences,
      aiRouteStops: routeStops,
    });

    setSaveMessage(`Saved to My Page (${saved.title})`);
  };

  return (
    <div style={styles.page}>
      <div style={styles.phoneFrame}>
        <div style={styles.headerRow}>
          <button type="button" onClick={onBack} style={styles.iconButton}>
            {"<"}
          </button>
          <span style={styles.headerBadge}>AI Result</span>
        </div>

        <div style={styles.titleBlock}>
          <span style={styles.eyebrow}>Recommendation API V2</span>
          <h1 style={styles.title}>{buildRouteTitle(preferences)}</h1>
          <p style={styles.copy}>{summary}</p>
        </div>

        <div style={styles.summaryGrid}>
          <div style={styles.summaryCard}>
            <span style={styles.summaryLabel}>Travel Style</span>
            <strong style={styles.summaryValue}>
              {preferences.styles.length > 0
                ? preferences.styles.join(" + ")
                : "No style selected"}
            </strong>
          </div>
          <div style={styles.summaryCard}>
            <span style={styles.summaryLabel}>Budget</span>
            <strong style={styles.summaryValue}>
              {budgetCategoryLabel(preferences.budgetCategory)}
            </strong>
          </div>
          <div style={styles.summaryCard}>
            <span style={styles.summaryLabel}>Companion</span>
            <strong style={styles.summaryValue}>
              {preferences.companion || "Not selected"}
            </strong>
          </div>
        </div>

        <GoogleMapPreview places={allPlaces} />

        <section style={styles.timelineSection}>
          <div style={styles.timelineHeader}>
            <div>
              <h2 style={styles.timelineTitle}>Timeline</h2>
              <p style={styles.timelineRoute}>
                Timeline, movements, and budget are rendered directly from `/api/tour/recommend` V2.
              </p>
            </div>
            <span style={styles.timelineBadge}>Public Transit</span>
          </div>

          {errorMessage ? (
            <div style={styles.stateCard}>{errorMessage}</div>
          ) : !plan || plan.tour_plan.length === 0 ? (
            <div style={styles.stateCard}>No plan has been returned yet.</div>
          ) : (
            <div style={styles.timelineList}>
              {plan.tour_plan.map((day) => {
                const placeMap = getPlaceMap(day);
                return (
                  <section key={day.day} style={styles.dayRouteBlock}>
                    <div style={styles.dayRouteHeader}>
                      <strong style={styles.dayRouteTitle}>Day {day.day}</strong>
                      <span style={styles.dayRouteCluster}>{formatKrw(day.budget_total_krw)}</span>
                    </div>
                    {day.timeline.map((slot, index) => {
                      const place = placeMap.get(slot.place_id);
                      const movement = day.movements[index];
                      return (
                        <div key={`${day.day}-${slot.place_id}-${index}`}>
                          <div style={styles.timelineItem}>
                            <div style={styles.timelineTime}>{slot.time}</div>
                            <div style={styles.timelineDot}>{index + 1}</div>
                            <div style={styles.timelineCard}>
                              <div style={styles.timelineTitleRow}>
                                <strong style={styles.timelineItemTitle}>{slot.title}</strong>
                                {typeof place?.rating === "number" ? (
                                  <span style={styles.ratingBadge}>{place.rating.toFixed(1)}</span>
                                ) : null}
                              </div>
                              {place?.reason ? (
                                <p style={styles.timelineCopy}>{place.reason}</p>
                              ) : null}
                              {place?.address ? (
                                <p style={styles.poiAddress}>{place.address}</p>
                              ) : null}
                              {place ? (
                                <div style={styles.poiMetaRow}>
                                  <span>{place.category}</span>
                                  <span>{place.stay_minutes} min</span>
                                  <span>{formatKrw(place.estimated_cost_krw)}</span>
                                </div>
                              ) : null}
                            </div>
                          </div>
                          {movement ? (
                            <div style={styles.movementCard}>
                              {movement.from_place} to {movement.to_place}: {movement.method}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                    {day.summary ? <p style={styles.daySummary}>{day.summary}</p> : null}
                    {day.budget_breakdown.length > 0 ? (
                      <div style={styles.budgetList}>
                        {day.budget_breakdown.map((item) => (
                          <div key={`${day.day}-${item.label}`} style={styles.budgetItem}>
                            <span>{item.label}</span>
                            <strong>{formatKrw(item.amount_krw)}</strong>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          )}
        </section>

        {plan ? (
          <div style={{ ...styles.stateCard, ...(isOverBudget ? styles.warningCard : {}) }}>
            Total budget: {formatKrw(budgetTotal)}
            {isOverBudget ? " - Budget may be exceeded." : ""}
          </div>
        ) : null}

        <button
          type="button"
          onClick={handleSave}
          style={styles.primaryAction}
          disabled={!plan || routeStops.length === 0}
        >
          Save plan to My Page
        </button>

        {saveMessage ? <p style={styles.saveMessage}>{saveMessage}</p> : null}
      </div>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    padding: "20px 16px",
    background: "linear-gradient(180deg, #f7ffff 0%, #fefdf7 100%)",
    fontFamily: '"Nunito", "Apple SD Gothic Neo", sans-serif',
  },
  phoneFrame: {
    maxWidth: 430,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 18,
    paddingBottom: 28,
  },
  headerRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  iconButton: {
    width: 42,
    height: 42,
    borderRadius: 14,
    border: "1px solid #d6eeee",
    background: "#ffffff",
    color: "#204444",
    fontSize: 18,
    fontWeight: 800,
    cursor: "pointer",
  },
  headerBadge: {
    display: "inline-flex",
    alignItems: "center",
    padding: "8px 12px",
    borderRadius: 999,
    background: "rgba(1, 192, 192, 0.12)",
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
  titleBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: 0.4,
    color: BRAND,
  },
  title: {
    margin: 0,
    fontSize: 28,
    lineHeight: 1.15,
    color: "#102223",
  },
  copy: {
    margin: 0,
    color: "#486566",
    fontSize: 14,
    lineHeight: 1.6,
  },
  summaryGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 10,
  },
  summaryCard: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    padding: 16,
    borderRadius: 18,
    background: "#ffffff",
    border: "1px solid #d9eeee",
  },
  summaryLabel: {
    color: "#577171",
    fontSize: 12,
    fontWeight: 700,
  },
  summaryValue: {
    color: "#102223",
    fontSize: 14,
    lineHeight: 1.5,
  },
  mapCard: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    padding: 16,
    borderRadius: 22,
    background: "#ffffff",
    border: "1px solid #dceeee",
  },
  mapViewport: {
    position: "relative",
    minHeight: 220,
    borderRadius: 18,
    overflow: "hidden",
    background: "#eef7f7",
  },
  mapCanvasGoogle: {
    position: "absolute",
    inset: 0,
  },
  mapEmpty: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    textAlign: "center",
    color: "#537070",
    padding: "0 20px",
    lineHeight: 1.6,
    background: "#eef7f7",
    zIndex: 1,
  },
  mapLegend: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  mapLegendItem: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  mapLegendIndex: {
    width: 22,
    height: 22,
    borderRadius: "50%",
    background: "rgba(255,190,15,0.22)",
    color: "#7a5400",
    display: "grid",
    placeItems: "center",
    fontSize: 12,
    fontWeight: 800,
  },
  mapLegendText: {
    color: "#204444",
    fontSize: 13,
    fontWeight: 700,
  },
  timelineSection: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  timelineHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  timelineTitle: {
    margin: 0,
    color: "#102223",
    fontSize: 21,
  },
  timelineRoute: {
    margin: "6px 0 0",
    color: "#5d7576",
    fontSize: 13,
    lineHeight: 1.5,
  },
  timelineBadge: {
    padding: "8px 10px",
    borderRadius: 999,
    background: "rgba(255,190,15,0.18)",
    color: "#7a5400",
    fontSize: 12,
    fontWeight: 800,
  },
  timelineList: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  timelineItem: {
    display: "grid",
    gridTemplateColumns: "56px 26px 1fr",
    gap: 10,
    alignItems: "start",
  },
  timelineTime: {
    color: BRAND,
    fontSize: 12,
    fontWeight: 900,
    paddingTop: 14,
  },
  timelineDot: {
    width: 24,
    height: 24,
    borderRadius: "50%",
    background: ACCENT,
    color: "#533800",
    display: "grid",
    placeItems: "center",
    marginTop: 10,
    fontSize: 12,
    fontWeight: 900,
  },
  timelineCard: {
    padding: "14px 15px",
    borderRadius: 18,
    background: "#ffffff",
    border: "1px solid #dceeee",
    boxShadow: "0 10px 24px rgba(16, 34, 35, 0.05)",
  },
  timelineTitleRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  timelineItemTitle: {
    color: "#102223",
    fontSize: 14,
  },
  ratingBadge: {
    padding: "5px 8px",
    borderRadius: 999,
    background: "rgba(255,190,15,0.2)",
    color: "#7a5400",
    fontSize: 11,
    fontWeight: 900,
  },
  timelineCopy: {
    margin: "8px 0 0",
    color: "#557071",
    lineHeight: 1.6,
    fontSize: 13,
  },
  dayRouteBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  dayRouteHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "0 2px",
  },
  dayRouteTitle: {
    color: "#102223",
    fontSize: 16,
  },
  dayRouteCluster: {
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
  loadingScreen: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  loadingHero: {
    padding: 20,
    borderRadius: 22,
    background: "#ffffff",
    border: "1px solid #dceeee",
    boxShadow: "0 12px 30px rgba(16, 34, 35, 0.06)",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  loadingBadge: {
    width: "fit-content",
    padding: "7px 10px",
    borderRadius: 999,
    background: "rgba(1, 192, 192, 0.12)",
    color: BRAND,
    fontSize: 12,
    fontWeight: 900,
  },
  loadingTitle: {
    margin: 0,
    color: "#102223",
    fontSize: 22,
  },
  loadingCopy: {
    margin: 0,
    color: "#557071",
    fontSize: 13,
    lineHeight: 1.6,
  },
  progressTrack: {
    height: 12,
    borderRadius: 999,
    background: "#e8f6f6",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 999,
    background: `linear-gradient(90deg, ${BRAND} 0%, ${ACCENT} 100%)`,
    transition: "width 500ms ease",
  },
  progressMeta: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    color: "#486566",
    fontSize: 12,
    fontWeight: 800,
  },
  loadingSteps: {
    display: "grid",
    gap: 8,
  },
  loadingStepItem: {
    padding: "12px 14px",
    borderRadius: 16,
    background: "#ffffff",
    border: "1px solid #dceeee",
    color: "#204444",
    fontSize: 13,
    fontWeight: 800,
  },
  loadingFooter: {
    margin: 0,
    textAlign: "center",
    color: "#5d7576",
    fontSize: 12,
    fontWeight: 800,
  },  stateCard: {
    padding: 18,
    borderRadius: 18,
    background: "#ffffff",
    border: "1px solid #dceeee",
    color: "#516a6b",
    lineHeight: 1.6,
    fontSize: 13,
  },
  warningCard: {
    border: "1px solid rgba(255,190,15,0.65)",
    background: "rgba(255,190,15,0.12)",
    color: "#7a5400",
    fontWeight: 800,
  },
  poiAddress: {
    margin: "8px 0 0",
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
  poiMetaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 10,
    color: "#5d7576",
    fontSize: 12,
    fontWeight: 700,
  },
  movementCard: {
    margin: "8px 0 8px 92px",
    padding: "10px 12px",
    borderRadius: 14,
    background: "rgba(1,192,192,0.1)",
    color: "#0b6161",
    fontSize: 12,
    fontWeight: 800,
    lineHeight: 1.5,
  },
  daySummary: {
    margin: 0,
    padding: 14,
    borderRadius: 16,
    background: "#f6fcfc",
    color: "#486566",
    lineHeight: 1.6,
    fontSize: 13,
  },
  budgetList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    padding: 14,
    borderRadius: 16,
    background: "#ffffff",
    border: "1px solid #dceeee",
  },
  budgetItem: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    color: "#204444",
    fontSize: 13,
  },
  primaryAction: {
    minHeight: 56,
    border: "none",
    borderRadius: 18,
    background: `linear-gradient(135deg, ${BRAND} 0%, #11abab 100%)`,
    color: "#ffffff",
    fontSize: 15,
    fontWeight: 900,
    cursor: "pointer",
    boxShadow: "0 16px 30px rgba(1, 192, 192, 0.24)",
  },
  saveMessage: {
    margin: 0,
    textAlign: "center",
    color: BRAND,
    fontSize: 13,
    fontWeight: 800,
  },
};