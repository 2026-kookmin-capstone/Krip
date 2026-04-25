import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { getTourPlaces, type TourPlaceApiItem } from "../api/auth/auth";
import {
  ACCENT,
  BRAND,
  DEFAULT_MAP_CENTER,
  buildPlanTitle,
  budgetCategoryLabel,
  createAiSummary,
  distributeTimeLabels,
  getSavedPlanById,
  upsertSavedPlan,
  type AiPreferenceState,
  type AiRouteStop,
} from "../team/api/aiPlanShared";

interface AiPlanResultPageProps {
  preferences: AiPreferenceState;
  onBack: () => void;
  onEdit: () => void;
}

interface RouteFetchState {
  routeStops: AiRouteStop[];
  unmatchedKeywords: string[];
}

function normalizeItem(item: TourPlaceApiItem, keyword: string): AiRouteStop | null {
  const latitude = Number(item.latitude ?? item.lat ?? item.location?.lat);
  const longitude = Number(item.longitude ?? item.lng ?? item.location?.lng);

  const id = String(item.place_id || item.id || "");
  const name = String(item.display_name || item.name || item.title || "");
  if (!id || !name) {
    return null;
  }

  return {
    id,
    name,
    category: String(item.category || item.type || item.place_type || "Place"),
    summary: String(
      item.summary ||
        item.description ||
        item.review_summary ||
        item.generative_summary ||
        item.editorial_summary ||
        ""
    ),
    address: String(item.short_address || item.address || ""),
    latitude: Number.isFinite(latitude) ? latitude : undefined,
    longitude: Number.isFinite(longitude) ? longitude : undefined,
    keyword,
  };
}

async function fetchRouteStops(
  preferences: AiPreferenceState
): Promise<RouteFetchState> {
  const rawKeywords = [
    preferences.departure,
    ...preferences.styles,
    preferences.extraPlace,
    preferences.arrival,
    preferences.foodNeed,
  ];

  const keywords = rawKeywords
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index);

  const routeStops: AiRouteStop[] = [];
  const unmatchedKeywords: string[] = [];
  const usedIds = new Set<string>();

  for (const keyword of keywords) {
    try {
      const response = await getTourPlaces({
        lat: DEFAULT_MAP_CENTER.lat,
        lng: DEFAULT_MAP_CENTER.lng,
        keyword,
      });

      const matched = response.items
        .map((item) => normalizeItem(item, keyword))
        .find((item) => item && !usedIds.has(item.id));

      if (!matched) {
        unmatchedKeywords.push(keyword);
        continue;
      }

      usedIds.add(matched.id);
      routeStops.push(matched);
    } catch {
      unmatchedKeywords.push(keyword);
    }
  }

  const timeLabels = distributeTimeLabels(
    preferences.startTime,
    preferences.endTime,
    routeStops.length
  );

  return {
    routeStops: routeStops.map((stop, index) => ({
      ...stop,
      timeLabel: timeLabels[index],
    })),
    unmatchedKeywords,
  };
}

function readPlanId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("planId");
}

function buildRouteTitle(preferences: AiPreferenceState): string {
  return buildPlanTitle(
    "ai",
    `${preferences.departure || "Start"} to ${preferences.arrival || "End"}`
  );
}

function MapPreview({ routeStops }: { routeStops: AiRouteStop[] }) {
  const positionedStops = routeStops.filter(
    (stop): stop is AiRouteStop & { latitude: number; longitude: number } =>
      typeof stop.latitude === "number" && typeof stop.longitude === "number"
  );

  const latitudes = positionedStops.map((stop) => stop.latitude);
  const longitudes = positionedStops.map((stop) => stop.longitude);
  const latMin = latitudes.length ? Math.min(...latitudes) : DEFAULT_MAP_CENTER.lat - 0.01;
  const latMax = latitudes.length ? Math.max(...latitudes) : DEFAULT_MAP_CENTER.lat + 0.01;
  const lngMin = longitudes.length ? Math.min(...longitudes) : DEFAULT_MAP_CENTER.lng - 0.01;
  const lngMax = longitudes.length ? Math.max(...longitudes) : DEFAULT_MAP_CENTER.lng + 0.01;
  const latRange = latMax - latMin || 0.02;
  const lngRange = lngMax - lngMin || 0.02;

  return (
    <div style={styles.mapCard}>
      <div style={styles.mapCanvas}>
        <div style={styles.mapRoadHorizontalA} />
        <div style={styles.mapRoadHorizontalB} />
        <div style={styles.mapRoadVerticalA} />
        <div style={styles.mapRoadVerticalB} />
        {positionedStops.length > 0 ? (
          positionedStops.map((stop, index) => {
            const left = ((stop.longitude - lngMin) / lngRange) * 100;
            const top = 100 - ((stop.latitude - latMin) / latRange) * 100;
            return (
              <div
                key={stop.id}
                style={{
                  ...styles.mapPin,
                  left: `${Math.max(8, Math.min(92, left))}%`,
                  top: `${Math.max(8, Math.min(88, top))}%`,
                }}
              >
                {index + 1}
              </div>
            );
          })
        ) : (
          <div style={styles.mapEmpty}>Location coordinates will appear here when the API returns them.</div>
        )}
      </div>
      <div style={styles.mapLegend}>
        {routeStops.map((stop, index) => (
          <div key={stop.id} style={styles.mapLegendItem}>
            <span style={styles.mapLegendIndex}>{index + 1}</span>
            <span style={styles.mapLegendText}>{stop.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AiPlanResultPage({
  preferences,
  onBack,
  onEdit,
}: AiPlanResultPageProps) {
  const [routeStops, setRouteStops] = useState<AiRouteStop[]>([]);
  const [unmatchedKeywords, setUnmatchedKeywords] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [saveMessage, setSaveMessage] = useState("");

  const planId = useMemo(() => readPlanId(), []);

  useEffect(() => {
    const savedPlan = getSavedPlanById(planId);
    if (savedPlan?.type === "ai" && savedPlan.aiRouteStops) {
      setRouteStops(savedPlan.aiRouteStops);
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    void fetchRouteStops(preferences)
      .then((result) => {
        if (cancelled) return;
        setRouteStops(result.routeStops);
        setUnmatchedKeywords(result.unmatchedKeywords);
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [planId, preferences]);

  const summary = useMemo(
    () => createAiSummary(preferences, routeStops.length),
    [preferences, routeStops.length]
  );

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
          <span style={styles.eyebrow}>Generated Plan</span>
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

        <MapPreview routeStops={routeStops} />

        <section style={styles.timelineSection}>
          <div style={styles.timelineHeader}>
            <div>
              <h2 style={styles.timelineTitle}>API-based route</h2>
              <p style={styles.timelineRoute}>
                Stops are composed from the current API response and your selected tokens.
              </p>
            </div>
            <span style={styles.timelineBadge}>
              {preferences.transport || "Transport not selected"}
            </span>
          </div>

          {isLoading ? (
            <div style={styles.stateCard}>Loading place data...</div>
          ) : routeStops.length === 0 ? (
            <div style={styles.stateCard}>
              No matching places have been returned yet. Once the API provides results, this screen will render them automatically.
            </div>
          ) : (
            <div style={styles.timelineList}>
              {routeStops.map((stop, index) => (
                <div key={stop.id} style={styles.timelineItem}>
                  <div style={styles.timelineTime}>{stop.timeLabel || "--:--"}</div>
                  <div style={styles.timelineDot}>{index + 1}</div>
                  <div style={styles.timelineCard}>
                    <strong style={styles.timelineItemTitle}>{stop.name}</strong>
                    <p style={styles.timelineCopy}>
                      {stop.summary || "Summary will appear when the API returns it."}
                    </p>
                    <p style={styles.poiAddress}>
                      {stop.address || "Address will appear when the API returns it."}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <button
          type="button"
          onClick={handleSave}
          style={styles.primaryAction}
          disabled={routeStops.length === 0}
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
  mapCanvas: {
    position: "relative",
    minHeight: 180,
    borderRadius: 18,
    background:
      "linear-gradient(145deg, #edf8f8 0%, #fff6dd 100%)",
    overflow: "hidden",
  },
  mapRoadHorizontalA: {
    position: "absolute",
    left: "-8%",
    right: "-8%",
    top: "24%",
    height: 16,
    borderRadius: 999,
    background: "rgba(255,255,255,0.75)",
    transform: "rotate(-7deg)",
  },
  mapRoadHorizontalB: {
    position: "absolute",
    left: "-6%",
    right: "-6%",
    top: "62%",
    height: 18,
    borderRadius: 999,
    background: "rgba(255,255,255,0.72)",
    transform: "rotate(5deg)",
  },
  mapRoadVerticalA: {
    position: "absolute",
    top: "-8%",
    bottom: "-8%",
    left: "28%",
    width: 16,
    borderRadius: 999,
    background: "rgba(255,255,255,0.7)",
    transform: "rotate(8deg)",
  },
  mapRoadVerticalB: {
    position: "absolute",
    top: "-10%",
    bottom: "-10%",
    right: "24%",
    width: 14,
    borderRadius: 999,
    background: "rgba(255,255,255,0.68)",
    transform: "rotate(-10deg)",
  },
  mapPin: {
    position: "absolute",
    width: 26,
    height: 26,
    marginLeft: -13,
    marginTop: -13,
    borderRadius: "50%",
    background: ACCENT,
    color: "#533800",
    display: "grid",
    placeItems: "center",
    fontSize: 12,
    fontWeight: 900,
    boxShadow: "0 8px 16px rgba(255,190,15,0.28)",
  },
  mapEmpty: {
    height: "100%",
    display: "grid",
    placeItems: "center",
    textAlign: "center",
    color: "#537070",
    padding: "0 20px",
    lineHeight: 1.6,
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
  timelineItemTitle: {
    color: "#102223",
    fontSize: 14,
  },
  timelineCopy: {
    margin: "8px 0 0",
    color: "#557071",
    lineHeight: 1.6,
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
  stateCard: {
    padding: 18,
    borderRadius: 18,
    background: "#ffffff",
    border: "1px solid #dceeee",
    color: "#516a6b",
    lineHeight: 1.6,
    fontSize: 13,
  },
  poiAddress: {
    margin: "8px 0 0",
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
};
