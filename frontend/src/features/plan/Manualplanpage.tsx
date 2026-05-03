import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { getTourPlaces, type TourPlaceApiItem } from "../../api/auth/auth";
import {
  ACCENT,
  BRAND,
  DEFAULT_MAP_CENTER,
  buildPlanTitle,
  createPlanId,
  flattenRecommendedPlaces,
  getSavedPlanById,
  loadGoogleMapsApi,
  normalizePlaceKey,
  postTourRecommend,
  upsertSavedPlan,
  type SavedManualStop,
  type TourRecommendPlace,
  type TourRecommendRequest,
} from "../../api/aiPlanShared";

type ShareTarget = "kakao" | "link" | "mail" | "message";

interface ManualPlanPageProps {
  onBack?: () => void;
}

interface TourPlace {
  id: string;
  name: string;
  category: string;
  summary: string;
  address: string;
  rating?: number;
  latitude?: number;
  longitude?: number;
}

interface PlannedStop extends TourPlace {
  plannedId: string;
  visitDate: string;
  visitTime: string;
  durationMinutes: number;
  note: string;
}

declare global {
  interface Window {
    Kakao?: {
      isInitialized?: () => boolean;
      init: (key: string) => void;
      Share?: {
        sendDefault: (options: unknown) => void;
      };
    };
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

const DEFAULT_START_DATE = new Date().toISOString().slice(0, 10);

function readPlanId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("planId");
}

function formatDateLabel(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function enumerateTripDates(startDate: string, endDate: string): string[] {
  const days: string[] = [];
  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(`${endDate}T00:00:00`);

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) {
    return days;
  }

  const cursor = new Date(start);
  while (cursor <= end) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setDate(cursor.getDate() + 1);
  }

  return days;
}

function normalizePlaces(payload: TourPlaceApiItem[]): TourPlace[] {
  const normalized: Array<TourPlace | null> = payload.map((item) => {
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
      rating: Number.isFinite(Number(item.rating)) ? Number(item.rating) : undefined,
      latitude: Number.isFinite(latitude) ? latitude : undefined,
      longitude: Number.isFinite(longitude) ? longitude : undefined,
    };
  });

  return normalized.filter((item): item is TourPlace => Boolean(item));
}

function mergeRecommendedDescriptions(
  places: TourPlace[],
  recommendedPlaces: TourRecommendPlace[]
): TourPlace[] {
  const byId = new Map(
    recommendedPlaces.map((place) => [String(place.place_id), place])
  );
  const byName = new Map(
    recommendedPlaces.map((place) => [
      normalizePlaceKey(place.display_name || ""),
      place,
    ])
  );

  return places.map((place) => {
    const recommended =
      byId.get(place.id) || byName.get(normalizePlaceKey(place.name));

    if (!recommended) return place;

    const latitude = Number(recommended.location?.lat);
    const longitude = Number(recommended.location?.lng);

    return {
      ...place,
      category: recommended.category || place.category,
      summary: recommended.description || place.summary,
      address: recommended.address || place.address,
      rating:
        typeof recommended.rating === "number"
          ? recommended.rating
          : place.rating,
      latitude: Number.isFinite(latitude) ? latitude : place.latitude,
      longitude: Number.isFinite(longitude) ? longitude : place.longitude,
    };
  });
}

async function fetchManualRecommendationPool(): Promise<TourRecommendPlace[]> {
  const baseRequest: Omit<TourRecommendRequest, "travel_style"> = {
    travel_days: 1,
    budget: "중간",
    companion_type: "친구",
    schedule_density: "널널하게",
  };
  const styles: TourRecommendRequest["travel_style"][] = [
    "맛집 탐방",
    "쇼핑",
    "문화/역사",
    "카페",
    "자연/공원",
  ];

  const responses = await Promise.allSettled(
    styles.map((travelStyle) =>
      postTourRecommend({
        ...baseRequest,
        travel_style: travelStyle,
      })
    )
  );

  return responses.flatMap((result) =>
    result.status === "fulfilled"
      ? flattenRecommendedPlaces(result.value)
      : []
  );
}

async function fetchPlaces(query: string): Promise<TourPlace[]> {
  if (!query.trim()) return [];

  const response = await getTourPlaces({
    lat: DEFAULT_MAP_CENTER.lat,
    lng: DEFAULT_MAP_CENTER.lng,
    keyword: query.trim(),
  });

  const places = normalizePlaces(response.items);
  const recommendedPlaces = await fetchManualRecommendationPool();
  return mergeRecommendedDescriptions(places, recommendedPlaces);
}

async function loadKakaoSdk(): Promise<typeof window.Kakao | null> {
  if (typeof window === "undefined") return null;
  if (window.Kakao) return window.Kakao;

  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-kakao-sdk="true"]'
    );

    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("SDK load failed")), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.src = "https://developers.kakao.com/sdk/js/kakao.min.js";
    script.async = true;
    script.dataset.kakaoSdk = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("SDK load failed"));
    document.head.appendChild(script);
  });

  return window.Kakao || null;
}

function createShareLink(): string {
  if (typeof window === "undefined") {
    return "https://example.com/trip/manual";
  }
  return window.location.href;
}

function ShareSheet({ onClose }: { onClose: () => void }) {
  const shareLink = createShareLink();

  const handleShare = async (target: ShareTarget) => {
    if (target === "kakao") {
      const kakao = await loadKakaoSdk().catch(() => null);
      const kakaoKey = import.meta.env.VITE_KAKAO_JS_KEY;

      if (!kakao || !kakaoKey) {
        window.alert("Add VITE_KAKAO_JS_KEY to enable KakaoTalk sharing.");
        onClose();
        return;
      }

      if (!kakao.isInitialized?.()) {
        kakao.init(kakaoKey);
      }

      kakao.Share?.sendDefault({
        objectType: "feed",
        content: {
          title: "Trip plan invite",
          description: "Join my trip plan and edit it together.",
          imageUrl:
            "https://developers.kakao.com/tool/resource/static/img/button/kakaolink_btn_small.png",
          link: {
            mobileWebUrl: shareLink,
            webUrl: shareLink,
          },
        },
        buttons: [
          {
            title: "Open Plan",
            link: {
              mobileWebUrl: shareLink,
              webUrl: shareLink,
            },
          },
        ],
      });
      onClose();
      return;
    }

    if (target === "link") {
      try {
        await navigator.clipboard.writeText(shareLink);
      } catch {
        window.prompt("Copy this link", shareLink);
      }
      onClose();
      return;
    }

    if (target === "mail") {
      window.location.assign(
        `mailto:?subject=Trip plan invite&body=Join my trip plan: ${shareLink}`
      );
      onClose();
      return;
    }

    window.location.assign(`sms:?body=Join my trip plan ${shareLink}`);
    onClose();
  };

  const shareButtons: Array<{
    id: ShareTarget;
    title: string;
    subtitle: string;
    color: string;
  }> = [
    { id: "kakao", title: "KakaoTalk", subtitle: "SDK share", color: "#fee500" },
    { id: "link", title: "Copy Link", subtitle: "Share URL", color: "#dffafa" },
    { id: "mail", title: "Email", subtitle: "Send invite", color: "#eef3ff" },
    { id: "message", title: "Message", subtitle: "Open SMS", color: "#f3fff0" },
  ];

  return (
    <div style={styles.overlay}>
      <button
        type="button"
        onClick={onClose}
        style={styles.overlayBackdrop}
        aria-label="Close share sheet"
      />
      <div style={styles.sheet}>
        <div style={styles.sheetHandle} />
        <h2 style={styles.sheetTitle}>Invite friends</h2>
        <p style={styles.sheetCopy}>
          Share this planning link so your friends can join and work on the itinerary together.
        </p>
        <div style={styles.shareGrid}>
          {shareButtons.map((button) => (
            <button
              key={button.id}
              type="button"
              onClick={() => void handleShare(button.id)}
              style={{ ...styles.shareCard, background: button.color }}
            >
              <strong style={styles.shareTitle}>{button.title}</strong>
              <span style={styles.shareSubtitle}>{button.subtitle}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function MapPreview({ stops }: { stops: PlannedStop[] }) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");

  const positionedStops = useMemo(
    () =>
      stops.filter(
        (stop): stop is PlannedStop & { latitude: number; longitude: number } =>
          typeof stop.latitude === "number" && typeof stop.longitude === "number"
      ),
    [stops]
  );

  useEffect(() => {
    let markers: GoogleMarker[] = [];
    let polyline: GooglePolyline | null = null;
    let cancelled = false;

    if (!mapRef.current || positionedStops.length === 0) {
      setMapReady(false);
      setMapError("");
      return undefined;
    }

    void loadGoogleMapsApi()
      .then((google) => {
        if (cancelled || !google?.maps || !mapRef.current) return;

        try {
          const map = new google.maps.Map(mapRef.current, {
            center: {
              lat: positionedStops[0].latitude,
              lng: positionedStops[0].longitude,
            },
            zoom: 12,
            disableDefaultUI: true,
            zoomControl: true,
            mapId: "d67e58693d403acacaa713aa"
          });

          const bounds = new google.maps.LatLngBounds();
          positionedStops.forEach((stop, index) => {
            const position = { lat: stop.latitude, lng: stop.longitude };
            bounds.extend(position);
            markers.push(
              new google.maps.Marker({
                position,
                map,
                label: String(index + 1),
                title: stop.name,
              })
            );
          });

          if (positionedStops.length > 1) {
            polyline = new google.maps.Polyline({
              path: positionedStops.map((stop) => ({
                lat: stop.latitude,
                lng: stop.longitude,
              })),
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
  }, [mapRef, positionedStops]);

  const hasApiKey = Boolean(import.meta.env.VITE_GOOGLE_MAPS_API_KEY);

  return (
    <div style={styles.mapBox}>
      <div style={styles.mapViewport}>
        <div style={styles.mapCanvasGoogle} ref={mapRef} />
        {positionedStops.length === 0 ? (
          <div style={styles.mapEmpty}>
            Search and add places with coordinates to display them on the map.
          </div>
        ) : !hasApiKey ? (
          <div style={styles.mapEmpty}>Add `VITE_GOOGLE_MAPS_API_KEY` to render the live map.</div>
        ) : mapError ? (
          <div style={styles.mapEmpty}>{mapError}</div>
        ) : !mapReady ? (
          <div style={styles.mapEmpty}>Loading Google Map...</div>
        ) : null}
      </div>
      {positionedStops.length > 0 ? (
        <div style={styles.mapLegendInline}>
          {positionedStops.map((stop, index) => (
            <div key={stop.plannedId} style={styles.mapLegendChip}>
              <span style={styles.mapLegendIndex}>{index + 1}</span>
              <span style={styles.mapLegendLabel}>{stop.name}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function ManualPlanPage({ onBack }: ManualPlanPageProps) {
  const [tripTitle, setTripTitle] = useState("Manual Trip Plan");
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE);
  const [endDate, setEndDate] = useState(DEFAULT_START_DATE);
  const [activeDate, setActiveDate] = useState(DEFAULT_START_DATE);
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [searchResults, setSearchResults] = useState<TourPlace[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [tripStops, setTripStops] = useState<PlannedStop[]>([]);
  const [editingStopId, setEditingStopId] = useState<string | null>(null);
  const [showShare, setShowShare] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  const planId = useMemo(() => readPlanId(), []);
  const tripDates = useMemo(
    () => enumerateTripDates(startDate, endDate),
    [startDate, endDate]
  );

  useEffect(() => {
    const savedPlan = getSavedPlanById(planId);
    if (!savedPlan || savedPlan.type !== "manual") {
      return;
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTripTitle(savedPlan.title || "Manual Trip Plan");
    setStartDate(savedPlan.manualStartDate || DEFAULT_START_DATE);
    setEndDate(savedPlan.manualEndDate || savedPlan.manualStartDate || DEFAULT_START_DATE);
    setActiveDate(savedPlan.manualStartDate || DEFAULT_START_DATE);
    setTripStops(savedPlan.manualStops || []);
  }, [planId]);

  useEffect(() => {
    if (!tripDates.includes(activeDate) && tripDates.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveDate(tripDates[0]);
    }
  }, [activeDate, tripDates]);

  const activeStops = tripStops.filter((stop) => stop.visitDate === activeDate);

  const handleSearch = () => {
    const nextQuery = query.trim();
    setSubmittedQuery(nextQuery);
    setErrorMessage("");

    if (!nextQuery) {
      setSearchResults([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    void fetchPlaces(nextQuery)
      .then((places) => {
        setSearchResults(places);
      })
      .catch((error) => {
        setSearchResults([]);
        setErrorMessage(
          error instanceof Error ? error.message : "Failed to search places."
        );
      })
      .finally(() => {
        setIsLoading(false);
      });
  };

  const getNextVisitTime = (targetDate: string) => {
    const sameDayStops = tripStops
      .filter((stop) => stop.visitDate === targetDate)
      .sort((left, right) => left.visitTime.localeCompare(right.visitTime));

    const lastStop = sameDayStops[sameDayStops.length - 1];
    if (!lastStop) return "10:00";

    const [hours, minutes] = lastStop.visitTime.split(":").map(Number);
    const totalMinutes = hours * 60 + minutes + 60;
    const nextHours = Math.floor(totalMinutes / 60)
      .toString()
      .padStart(2, "0");
    const nextMinutes = (totalMinutes % 60).toString().padStart(2, "0");
    return `${nextHours}:${nextMinutes}`;
  };

  const addPlaceToPlan = (place: TourPlace) => {
    const targetDate = activeDate || startDate;
    setTripStops((current) => [
      ...current,
      {
        ...place,
        plannedId: createPlanId("manual"),
        visitDate: targetDate,
        visitTime: getNextVisitTime(targetDate),
        durationMinutes: 90,
        note: "",
      },
    ]);
  };

  const updateStop = (plannedId: string, patch: Partial<PlannedStop>) => {
    setTripStops((current) =>
      current.map((stop) => (stop.plannedId === plannedId ? { ...stop, ...patch } : stop))
    );
  };

  const removeStop = (plannedId: string) => {
    setTripStops((current) => current.filter((stop) => stop.plannedId !== plannedId));
  };

  const handleSave = () => {
    const manualStops: SavedManualStop[] = tripStops.map((stop) => ({ ...stop }));
    const saved = upsertSavedPlan({
      id: planId || undefined,
      type: "manual",
      title: buildPlanTitle("manual", tripTitle),
      summary: `${tripDates.length} day plan with ${tripStops.length} saved stops`,
      manualStartDate: startDate,
      manualEndDate: endDate,
      manualStops,
    });

    setSaveMessage(`Saved to My Page (${saved.title})`);
  };

  return (
    <div style={styles.page}>
      <div style={styles.phoneFrame}>
        <div style={styles.topBar}>
          <button type="button" onClick={onBack} style={styles.iconButton}>
            {"<"}
          </button>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={styles.badge}>Manual Planner</span>
            <strong style={styles.title}>Build the itinerary yourself</strong>
          </div>
          <button type="button" onClick={() => setShowShare(true)} style={styles.shareButton}>
            Invite
          </button>
        </div>

        <label style={styles.fieldLabel}>
          Trip Title
          <input
            value={tripTitle}
            onChange={(event) => setTripTitle(event.target.value)}
            style={styles.input}
            placeholder="Manual Trip Plan"
          />
        </label>

        <section style={styles.card}>
          <div style={styles.sectionHeaderRow}>
            <div>
              <h1 style={styles.sectionTitle}>Trip dates</h1>
              <p style={styles.sectionCopy}>Select when the trip starts and ends before adding places.</p>
            </div>
            <span style={styles.dayCount}>
              {tripDates.length} day{tripDates.length > 1 ? "s" : ""}
            </span>
          </div>

          <div style={styles.twoColumn}>
            <label style={styles.fieldLabel}>
              Start date
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} style={styles.input} />
            </label>
            <label style={styles.fieldLabel}>
              End date
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} style={styles.input} />
            </label>
          </div>

          <div style={styles.dayTabs}>
            {tripDates.map((date, index) => (
              <button key={date} type="button" onClick={() => setActiveDate(date)} style={{ ...styles.dayTab, ...(date === activeDate ? styles.dayTabActive : {}) }}>
                <span style={styles.dayTabLabel}>Day {index + 1}</span>
                <span style={styles.dayTabDate}>{formatDateLabel(date)}</span>
              </button>
            ))}
          </div>
        </section>

        <section style={styles.card}>
          <div style={styles.sectionHeaderRow}>
            <div>
              <h2 style={styles.sectionTitle}>Map search</h2>
              <p style={styles.sectionCopy}>Nothing is shown until you search. Added places are plotted on a live map and connected in order.</p>
            </div>
          </div>

          <MapPreview stops={activeStops} />

          <label style={styles.searchWrap}>
            <span style={styles.searchLabel}>Place search</span>
            <div style={styles.searchRow}>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    handleSearch();
                  }
                }}
                style={styles.input}
                placeholder="Examples: Bukchon, cafe, Myeongdong Gyoja"
              />
              <button
                type="button"
                onClick={handleSearch}
                style={styles.searchButton}
                disabled={isLoading}
              >
                Search
              </button>
            </div>
          </label>

          <div style={styles.resultsList}>
            {!submittedQuery ? (
              <div style={styles.emptyState}>Enter a keyword and press Search to load places.</div>
            ) : isLoading ? (
              <div style={styles.emptyState}>Loading places...</div>
            ) : errorMessage ? (
              <div style={styles.emptyState}>{errorMessage}</div>
            ) : searchResults.length === 0 ? (
              <div style={styles.emptyState}>No places found for this keyword.</div>
            ) : (
              searchResults.map((place) => (
                <article key={place.id} style={styles.placeCard}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={styles.placeTopRow}>
                      <strong style={styles.placeName}>{place.name}</strong>
                      <div style={styles.placeBadgeRow}>
                        {typeof place.rating === "number" ? (
                          <span style={styles.ratingBadge}>{place.rating.toFixed(1)}</span>
                        ) : null}
                        <span style={styles.placeCategory}>{place.category}</span>
                      </div>
                    </div>
                    {place.summary ? (
                      <p style={styles.placeSummary}>{place.summary}</p>
                    ) : null}
                    {place.address ? (
                      <span style={styles.placeAddress}>{place.address}</span>
                    ) : null}
                  </div>
                  <button type="button" onClick={() => addPlaceToPlan(place)} style={styles.addButton}>
                    Add
                  </button>
                </article>
              ))
            )}
          </div>
        </section>

        <section style={styles.card}>
          <div style={styles.sectionHeaderRow}>
            <div>
              <h2 style={styles.sectionTitle}>Itinerary editor</h2>
              <p style={styles.sectionCopy}>Added places are spaced by one hour by default. Use Edit to change the day or time.</p>
            </div>
            <span style={styles.dayCount}>
              {activeStops.length} stop{activeStops.length > 1 ? "s" : ""}
            </span>
          </div>

          {activeStops.length === 0 ? (
            <div style={styles.emptyState}>No stops added for this day yet.</div>
          ) : (
            <div style={styles.timelineList}>
              {activeStops.map((stop, index) => (
                <article key={stop.plannedId} style={styles.stopCard}>
                  <div style={styles.stopIndex}>{index + 1}</div>
                  <div style={styles.stopBody}>
                    <div style={styles.placeTopRow}>
                      <strong style={styles.placeName}>{stop.name}</strong>
                      <div style={styles.stopActionRow}>
                        {typeof stop.rating === "number" ? (
                          <span style={styles.ratingBadge}>{stop.rating.toFixed(1)}</span>
                        ) : null}
                        <button type="button" onClick={() => setEditingStopId((current) => (current === stop.plannedId ? null : stop.plannedId))} style={styles.editButton}>
                          Edit
                        </button>
                        <button type="button" onClick={() => removeStop(stop.plannedId)} style={styles.deleteButton}>
                          Delete
                        </button>
                      </div>
                    </div>
                    {stop.summary ? (
                      <p style={styles.placeSummary}>{stop.summary}</p>
                    ) : null}
                    {stop.address ? (
                      <span style={styles.placeAddress}>{stop.address}</span>
                    ) : null}
                    {editingStopId === stop.plannedId ? (
                      <>
                        <div style={styles.stopEditors}>
                          <label style={styles.fieldLabel}>
                            Day
                            <select value={stop.visitDate} onChange={(event) => updateStop(stop.plannedId, { visitDate: event.target.value })} style={styles.input}>
                              {tripDates.map((date) => (
                                <option key={date} value={date}>
                                  {formatDateLabel(date)}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label style={styles.fieldLabel}>
                            Time
                            <input type="time" value={stop.visitTime} onChange={(event) => updateStop(stop.plannedId, { visitTime: event.target.value })} style={styles.input} />
                          </label>
                        </div>
                        <div style={styles.stopEditors}>
                          <label style={styles.fieldLabel}>
                            Duration
                            <input type="number" min={30} step={30} value={stop.durationMinutes} onChange={(event) => updateStop(stop.plannedId, { durationMinutes: Number(event.target.value) || 30 })} style={styles.input} />
                          </label>
                          <label style={styles.fieldLabel}>
                            Note
                            <input value={stop.note} onChange={(event) => updateStop(stop.plannedId, { note: event.target.value })} style={styles.input} placeholder="Add note" />
                          </label>
                        </div>
                      </>
                    ) : (
                      <div style={styles.stopMetaRow}>
                        <span>{formatDateLabel(stop.visitDate)}</span>
                        <span>{stop.visitTime}</span>
                        <span>{stop.durationMinutes} min</span>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <button type="button" onClick={handleSave} style={styles.primaryAction} disabled={tripStops.length === 0}>
          Save plan to My Page
        </button>

        {saveMessage ? <p style={styles.saveMessage}>{saveMessage}</p> : null}
      </div>

      {showShare ? <ShareSheet onClose={() => setShowShare(false)} /> : null}
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
    gap: 16,
    paddingBottom: 26,
  },
  topBar: {
    display: "grid",
    gridTemplateColumns: "42px 1fr auto",
    gap: 12,
    alignItems: "center",
  },
  iconButton: {
    width: 42,
    height: 42,
    borderRadius: 14,
    border: "1px solid #d7ecec",
    background: "#ffffff",
    color: "#204444",
    fontSize: 18,
    fontWeight: 800,
    cursor: "pointer",
  },
  shareButton: {
    minHeight: 42,
    border: "none",
    borderRadius: 14,
    background: ACCENT,
    color: "#533800",
    padding: "0 14px",
    fontSize: 13,
    fontWeight: 900,
    cursor: "pointer",
  },
  badge: {
    display: "inline-flex",
    width: "fit-content",
    padding: "7px 10px",
    borderRadius: 999,
    background: "rgba(1,192,192,0.12)",
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
  title: {
    color: "#102223",
    fontSize: 22,
  },
  card: {
    padding: 18,
    borderRadius: 24,
    background: "#ffffff",
    border: "1px solid #dceeee",
    boxShadow: "0 12px 30px rgba(16, 34, 35, 0.06)",
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  sectionHeaderRow: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  sectionTitle: {
    margin: 0,
    color: "#102223",
    fontSize: 20,
  },
  sectionCopy: {
    margin: "6px 0 0",
    color: "#577071",
    lineHeight: 1.6,
    fontSize: 13,
    maxWidth: 260,
  },
  dayCount: {
    padding: "8px 10px",
    borderRadius: 999,
    background: "rgba(255,190,15,0.18)",
    color: "#7a5400",
    fontSize: 12,
    fontWeight: 800,
  },
  twoColumn: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  fieldLabel: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    fontSize: 12,
    fontWeight: 800,
    color: "#204444",
  },
  input: {
    width: "100%",
    minHeight: 46,
    borderRadius: 14,
    border: "1px solid #d7ecec",
    background: "#fcffff",
    color: "#183536",
    padding: "0 14px",
    fontSize: 14,
    boxSizing: "border-box",
  },
  dayTabs: {
    display: "flex",
    gap: 8,
    overflowX: "auto",
    paddingBottom: 2,
  },
  dayTab: {
    minWidth: 96,
    border: "1px solid #d7ecec",
    borderRadius: 16,
    background: "#ffffff",
    padding: "12px 14px",
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 4,
    cursor: "pointer",
  },
  dayTabActive: {
    border: `1px solid ${BRAND}`,
    background: "rgba(1,192,192,0.12)",
  },
  dayTabLabel: {
    color: "#204444",
    fontSize: 12,
    fontWeight: 800,
  },
  dayTabDate: {
    color: BRAND,
    fontSize: 12,
    fontWeight: 700,
  },
  mapBox: {
    padding: 12,
    borderRadius: 20,
    background: "linear-gradient(145deg, #eafafa 0%, #fdf8e8 100%)",
    border: "1px solid #dceeee",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  mapViewport: {
    position: "relative",
    minHeight: 220,
    borderRadius: 16,
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
    color: "#577071",
    padding: "0 20px",
    lineHeight: 1.6,
    background: "#eef7f7",
    zIndex: 1,
  },
  mapLegendInline: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  mapLegendChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    minWidth: 0,
    padding: "8px 10px",
    borderRadius: 999,
    background: "#ffffff",
    border: "1px solid #dceeee",
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
    flexShrink: 0,
  },
  mapLegendLabel: {
    color: "#204444",
    fontSize: 12,
    fontWeight: 700,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  searchWrap: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  searchLabel: {
    color: "#204444",
    fontSize: 12,
    fontWeight: 800,
  },
  searchRow: {
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 10,
    alignItems: "center",
  },
  searchButton: {
    minWidth: 82,
    minHeight: 46,
    border: "none",
    borderRadius: 14,
    background: ACCENT,
    color: "#533800",
    padding: "0 14px",
    fontSize: 13,
    fontWeight: 900,
    cursor: "pointer",
  },
  resultsList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  placeCard: {
    padding: 14,
    borderRadius: 18,
    border: "1px solid #dceeee",
    background: "#fbffff",
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 12,
    alignItems: "center",
  },
  placeTopRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  placeName: {
    color: "#102223",
    fontSize: 15,
  },
  placeCategory: {
    padding: "6px 10px",
    borderRadius: 999,
    background: "rgba(1,192,192,0.1)",
    color: BRAND,
    fontSize: 11,
    fontWeight: 800,
  },
  placeBadgeRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 6,
    flexWrap: "wrap",
  },
  ratingBadge: {
    padding: "6px 9px",
    borderRadius: 999,
    background: "rgba(255,190,15,0.2)",
    color: "#7a5400",
    fontSize: 11,
    fontWeight: 900,
  },
  placeSummary: {
    margin: 0,
    color: "#577071",
    lineHeight: 1.6,
    fontSize: 13,
  },
  placeAddress: {
    color: BRAND,
    fontSize: 12,
    fontWeight: 700,
  },
  addButton: {
    minWidth: 66,
    minHeight: 40,
    border: "none",
    borderRadius: 14,
    background: BRAND,
    color: "#ffffff",
    fontSize: 13,
    fontWeight: 900,
    cursor: "pointer",
  },
  emptyState: {
    padding: "24px 16px",
    borderRadius: 18,
    background: "#f6fcfc",
    color: "#577071",
    textAlign: "center",
    fontSize: 14,
  },
  timelineList: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  stopCard: {
    display: "grid",
    gridTemplateColumns: "34px 1fr",
    gap: 12,
    alignItems: "start",
  },
  stopIndex: {
    width: 34,
    height: 34,
    borderRadius: 12,
    background: BRAND,
    color: "#ffffff",
    display: "grid",
    placeItems: "center",
    fontSize: 13,
    fontWeight: 900,
  },
  stopBody: {
    padding: 14,
    borderRadius: 18,
    border: "1px solid #dceeee",
    background: "#fbffff",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  stopEditors: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 10,
  },
  stopActionRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  editButton: {
    border: "none",
    borderRadius: 12,
    background: "rgba(1,192,192,0.14)",
    color: "#0b6161",
    padding: "8px 10px",
    fontSize: 12,
    fontWeight: 800,
    cursor: "pointer",
  },
  deleteButton: {
    border: "none",
    borderRadius: 12,
    background: "rgba(255, 190, 15, 0.18)",
    color: "#7a5400",
    padding: "8px 10px",
    fontSize: 12,
    fontWeight: 800,
    cursor: "pointer",
  },
  stopMetaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    color: "#5d7576",
    fontSize: 12,
    fontWeight: 700,
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
  overlay: {
    position: "fixed",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    justifyContent: "flex-end",
    zIndex: 30,
  },
  overlayBackdrop: {
    flex: 1,
    border: "none",
    background: "rgba(16, 34, 35, 0.42)",
    cursor: "pointer",
  },
  sheet: {
    padding: "18px 18px 28px",
    borderRadius: "28px 28px 0 0",
    background: "#ffffff",
    boxShadow: "0 -16px 36px rgba(16, 34, 35, 0.12)",
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  sheetHandle: {
    width: 56,
    height: 6,
    borderRadius: 999,
    background: "#d7ecec",
    alignSelf: "center",
  },
  sheetTitle: {
    margin: 0,
    color: "#102223",
    fontSize: 22,
  },
  sheetCopy: {
    margin: 0,
    color: "#577071",
    lineHeight: 1.6,
    fontSize: 14,
  },
  shareGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 10,
  },
  shareCard: {
    border: "none",
    borderRadius: 18,
    padding: "18px 14px",
    textAlign: "left",
    display: "flex",
    flexDirection: "column",
    gap: 6,
    cursor: "pointer",
  },
  shareTitle: {
    color: "#102223",
    fontSize: 14,
  },
  shareSubtitle: {
    color: "#577071",
    fontSize: 12,
  },
};
