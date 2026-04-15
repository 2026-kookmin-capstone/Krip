import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties, MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  addTourPlaceFavorite,
  deleteTourSearchHistoryOne,
  getTourPlaceFavorites,
  getTourSearchHistory,
  getMyProfile,
  getTourPlaces,
  logoutUser,
  removeTourPlaceFavorite,
  type FavoritePlaceApiItem,
  type SearchHistoryItem,
  type TourPlaceApiItem,
  type TourPlacesParams,
  type UserProfile,
} from "../api/auth/auth";

const DEFAULT_LOCATION = { lat: 37.5665, lng: 126.978 };
const DEFAULT_LOCATION_LABEL = "Central Seoul";
const CURRENT_LOCATION_LABEL = "Using your current location";
const SEARCH_SUGGESTION_LIMIT = 8;

const CATEGORY_FILTERS = ["All", "Attractions", "Food", "Activities"] as const;
const SORT_FILTERS = ["Nearest", "Top Rated", "Most Reviewed", "Favorites"] as const;

type CategoryFilter = (typeof CATEGORY_FILTERS)[number];
type SortFilter = (typeof SORT_FILTERS)[number];
type PlaceCategory = Exclude<CategoryFilter, "All">;
type PlaceTag = "Indoor" | "Outdoor" | "Crowded" | "Quiet";

interface Place {
  id: string;
  favoriteId?: string;
  favoriteCreatedAt?: string;
  initialIsFavorite?: boolean;
  name: string;
  category: PlaceCategory;
  raw: TourPlaceApiItem;
  tags: PlaceTag[];
  description: string;
  reviewCount: number;
  rating?: number;
  rawDistanceMeters?: number;
  address?: string;
  shortAddress?: string;
  phone?: string;
  phoneInternational?: string;
  website?: string;
  googleMapsUrl?: string;
  googleMapReviewLink?: string;
  openingHours: string[];
  services: string[];
  payment: string[];
  accessibility: string[];
  parking: string[];
  priceLevel?: string;
  priceRange?: {
    min?: string;
    max?: string;
  };
  reviews: Array<{
    author: string;
    rating?: number;
    relativeTime?: string;
    text?: string;
  }>;
  coords: {
    lat: number;
    lng: number;
  };
  thumbnail: {
    colors: readonly [string, string] | readonly string[];
    label: string;
  };
}

interface PlaceWithMeta extends Place {
  isFavorite: boolean;
  distanceKm: number;
}

function formatDistance(distanceKm: number): string {
  if (!Number.isFinite(distanceKm)) return "Checking distance";
  if (distanceKm < 1) return `${Math.round(distanceKm * 1000)}m`;
  return `${distanceKm.toFixed(1)}km`;
}

function formatRating(rating?: number, reviewCount?: number): string {
  if (!Number.isFinite(rating)) return "No rating available";
  if (!Number.isFinite(reviewCount)) return `Rating ${rating?.toFixed(1)}`;
  return `Rating ${rating?.toFixed(1)} · ${reviewCount?.toLocaleString()} reviews`;
}

function formatPriceRange(
  priceLevel?: string,
  priceRange?: { min?: string; max?: string }
): string {
  if (priceLevel) return priceLevel;
  if (priceRange?.min || priceRange?.max) {
    return [priceRange.min, priceRange.max].filter(Boolean).join(" ~ ");
  }
  return "No price information";
}

function haversineDistance(
  from: { lat: number; lng: number },
  to: { lat: number; lng: number }
): number {
  const earthRadiusKm = 6371;
  const latDelta = ((to.lat - from.lat) * Math.PI) / 180;
  const lngDelta = ((to.lng - from.lng) * Math.PI) / 180;
  const startLat = (from.lat * Math.PI) / 180;
  const endLat = (to.lat * Math.PI) / 180;

  const a =
    Math.sin(latDelta / 2) ** 2 +
    Math.cos(startLat) * Math.cos(endLat) * Math.sin(lngDelta / 2) ** 2;

  return earthRadiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function toPlaceCategory(value: unknown, types: unknown): PlaceCategory {
  const normalized = String(value || "").trim().toLowerCase();
  const normalizedTypes = Array.isArray(types)
    ? types.map((item) => String(item).trim().toLowerCase())
    : [];

  const restaurantKeywords = [
    "식당",
    "음식점",
    "맛집",
    "레스토랑",
    "카페",
    "커피",
    "바",
    "주점",
    "restaurant",
    "food",
    "cafe",
    "coffee",
    "bar",
    "bakery",
    "meal",
  ];

  const activityKeywords = [
    "액티비티",
    "체험",
    "공원",
    "쇼핑",
    "전시",
    "공연",
    "놀이",
    "게임",
    "테마파크",
    "영화관",
    "activity",
    "amusement",
    "shopping",
    "museum",
    "park",
    "stadium",
    "movie_theater",
    "bowling",
    "spa",
    "gym",
  ];

  const matchesKeyword = (keywords: string[]) =>
    keywords.some(
      (keyword) =>
        normalized.includes(keyword) ||
        normalizedTypes.some((type) => type.includes(keyword))
    );

  if (matchesKeyword(restaurantKeywords)) {
    return "Food";
  }

  if (matchesKeyword(activityKeywords)) {
    return "Activities";
  }

  return "Attractions";
}

function sanitizeTags(value: unknown): PlaceTag[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const tagMap: Record<string, PlaceTag> = {
    실내: "Indoor",
    indoor: "Indoor",
    실외: "Outdoor",
    outdoor: "Outdoor",
    관광객많음: "Crowded",
    crowded: "Crowded",
    관광객적은: "Quiet",
    quiet: "Quiet",
  };

  return value
    .map((item) => tagMap[String(item).trim().toLowerCase()] || tagMap[String(item).trim()] || null)
    .filter((item): item is PlaceTag => Boolean(item));
}

function toNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function mapTourPlace(item: TourPlaceApiItem): Place {
  const location = item.location || {};
  const description =
    item.description ||
    item.review_summary ||
    item.generative_summary ||
    item.editorial_summary ||
    item.short_address ||
    item.address ||
    item.summary ||
    "No description available yet.";

  return {
    id: String(item.id || item.place_id || crypto.randomUUID()),
    initialIsFavorite: item.is_favorite === true,
    name: String(item.display_name || item.name || item.title || "Unnamed place"),
    category: toPlaceCategory(
      item.category || item.type || item.place_type,
      item.types
    ),
    raw: item,
    tags: sanitizeTags(item.tags),
    description: String(description),
    reviewCount: toNumber(
      item.review_count ?? item.reviewCount ?? item.rating_count,
      0
    ),
    rating: Number.isFinite(Number(item.rating)) ? Number(item.rating) : undefined,
    rawDistanceMeters: toNumber(item.distance, Number.NaN),
    address: item.address ? String(item.address) : undefined,
    shortAddress: item.short_address ? String(item.short_address) : undefined,
    phone: item.phone ? String(item.phone) : undefined,
    phoneInternational: item.phone_international
      ? String(item.phone_international)
      : undefined,
    website: item.website ? String(item.website) : undefined,
    googleMapsUrl: item.google_maps_url ? String(item.google_maps_url) : undefined,
    googleMapReviewLink: item.google_map_review_link
      ? String(item.google_map_review_link)
      : undefined,
    openingHours: Array.isArray(item.opening_hours)
      ? item.opening_hours.map((value) => String(value))
      : [],
    services: Array.isArray(item.services)
      ? item.services.map((value) => String(value))
      : [],
    payment: Array.isArray(item.payment)
      ? item.payment.map((value) => String(value))
      : [],
    accessibility: Array.isArray(item.accessibility)
      ? item.accessibility.map((value) => String(value))
      : [],
    parking: Array.isArray(item.parking)
      ? item.parking.map((value) => String(value))
      : [],
    priceLevel: item.price_level ? String(item.price_level) : undefined,
    priceRange:
      item.price_range && typeof item.price_range === "object"
        ? {
            min: item.price_range.min ? String(item.price_range.min) : undefined,
            max: item.price_range.max ? String(item.price_range.max) : undefined,
          }
        : undefined,
    reviews: Array.isArray(item.reviews)
      ? item.reviews.map((review) => ({
          author: String(review?.author || "Anonymous"),
          rating: Number.isFinite(Number(review?.rating))
            ? Number(review?.rating)
            : undefined,
          relativeTime: review?.relative_time
            ? String(review.relative_time)
            : undefined,
          text: review?.text ? String(review.text) : undefined,
        }))
      : [],
    coords: {
      lat: toNumber(item.latitude ?? item.lat ?? location.lat, DEFAULT_LOCATION.lat),
      lng: toNumber(item.longitude ?? item.lng ?? location.lng, DEFAULT_LOCATION.lng),
    },
    thumbnail: {
      colors: ["#e9e9e9", "#d9d9d9"],
      label: "PLACE",
    },
  };
}

function mapFavoritePlace(item: FavoritePlaceApiItem): Place | null {
  if (!item.place) {
    return null;
  }

  const mappedPlace = mapTourPlace({
    ...item.place,
    is_favorite: true,
  });

  return {
    ...mappedPlace,
    favoriteId: item.favorite_id ? String(item.favorite_id) : undefined,
    favoriteCreatedAt: item.created_at ? String(item.created_at) : undefined,
    initialIsFavorite: true,
  };
}

export default function HomePage() {
  const navigate = useNavigate();
  const observerRef = useRef<HTMLDivElement | null>(null);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isProfileLoading, setIsProfileLoading] = useState(true);
  const [placesSource, setPlacesSource] = useState<Place[]>([]);
  const [favoritePlaces, setFavoritePlaces] = useState<Place[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const deferredSearch = useDeferredValue(searchInput.trim().toLowerCase());
  const [searchDraft, setSearchDraft] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [activeCategory, setActiveCategory] =
    useState<CategoryFilter>("All");
  const [activeSort, setActiveSort] = useState<SortFilter>("Nearest");
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const [favoriteActionIds, setFavoriteActionIds] = useState<string[]>([]);
  const [recentSearches, setRecentSearches] = useState<SearchHistoryItem[]>([]);
  const [locationLabel, setLocationLabel] = useState(DEFAULT_LOCATION_LABEL);
  const [selectedPlace, setSelectedPlace] = useState<PlaceWithMeta | null>(null);
  const [placesError, setPlacesError] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [currentLocation, setCurrentLocation] = useState(DEFAULT_LOCATION);

  useEffect(() => {
    getMyProfile()
      .then((profile) => {
        setUser(
          profile || {
            email: "",
            user_name: "Traveler",
          }
        );
      })
      .catch((error: { status?: number }) => {
        if (error.status === 403 || error.status === 404) {
          navigate("/register");
          return;
        }
        setUser({
          email: "",
          user_name: "Traveler",
        });
      })
      .finally(() => {
        setIsProfileLoading(false);
      });
  }, [navigate]);

  useEffect(() => {
    if (!navigator.geolocation) return undefined;

    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setCurrentLocation({
          lat: coords.latitude,
          lng: coords.longitude,
        });
        setLocationLabel(CURRENT_LOCATION_LABEL);
      },
      () => {
        setLocationLabel(DEFAULT_LOCATION_LABEL);
      },
      {
        enableHighAccuracy: true,
        timeout: 6000,
      }
    );

    return undefined;
  }, []);

  async function fetchPlaces(
    options: {
      cursor?: string;
      append?: boolean;
    } = {}
  ): Promise<void> {
    const params: TourPlacesParams = {
      lat: currentLocation.lat,
      lng: currentLocation.lng,
      keyword: searchInput || undefined,
      cursor: options.cursor,
    };

    const response = await getTourPlaces(params);
    const mappedItems = response.items.map(mapTourPlace);

    setPlacesSource((current) =>
      options.append ? [...current, ...mappedItems] : mappedItems
    );
    setNextCursor(response.nextCursor || null);
    setPlacesError("");

    if (!options.cursor && searchInput.trim()) {
      fetchSearchHistory().catch(() => {
        // Keep the places UI usable even if history refresh fails.
      });
    }
  }

  async function fetchFavoritePlaces(): Promise<void> {
    const response = await getTourPlaceFavorites();
    const mappedItems = response.favorites
      .map(mapFavoritePlace)
      .filter((place): place is Place => Boolean(place));

    setFavoritePlaces(mappedItems);
  }

  async function fetchSearchHistory(): Promise<void> {
    const response = await getTourSearchHistory();
    setRecentSearches(response.histories);
  }

  useEffect(() => {
    setIsFetchingMore(false);
    setNextCursor(null);

    fetchPlaces()
      .catch((error) => {
        const message =
          error instanceof Error ? error.message : "Failed to load places.";
        setPlacesError(message);
        setPlacesSource([]);
      });
  }, [currentLocation.lat, currentLocation.lng, searchInput]);

  useEffect(() => {
    fetchFavoritePlaces().catch((error) => {
      const message =
        error instanceof Error ? error.message : "Failed to load favorites.";
      setPlacesError(message);
      setFavoritePlaces([]);
    });
  }, []);

  useEffect(() => {
    fetchSearchHistory().catch(() => {
      setRecentSearches([]);
    });
  }, []);

  const favoriteIds = useMemo(
    () => new Set(favoritePlaces.map((place) => place.id)),
    [favoritePlaces]
  );

  const places = useMemo<PlaceWithMeta[]>(
    () =>
      placesSource.map((place) => ({
        ...place,
        isFavorite: place.initialIsFavorite || favoriteIds.has(place.id),
        distanceKm: Number.isFinite(place.rawDistanceMeters)
          ? (place.rawDistanceMeters as number) / 1000
          : haversineDistance(currentLocation, place.coords),
      })),
    [currentLocation, favoriteIds, placesSource]
  );

  const favoritePlacesWithMeta = useMemo<PlaceWithMeta[]>(
    () =>
      favoritePlaces.map((place) => ({
        ...place,
        isFavorite: true,
        distanceKm: Number.isFinite(place.rawDistanceMeters)
          ? (place.rawDistanceMeters as number) / 1000
          : haversineDistance(currentLocation, place.coords),
      })),
    [currentLocation, favoritePlaces]
  );

  const filteredPlaces = useMemo<PlaceWithMeta[]>(() => {
    const source = activeSort === "Favorites" ? favoritePlacesWithMeta : places;

    const nextPlaces = source.filter((place) => {
      const matchesCategory =
        activeCategory === "All" || place.category === activeCategory;

      const matchesSearch =
        !deferredSearch ||
        place.name.toLowerCase().includes(deferredSearch) ||
        place.description.toLowerCase().includes(deferredSearch) ||
        place.category.toLowerCase().includes(deferredSearch);

      const matchesFavorite =
        activeSort !== "Favorites" || place.isFavorite;

      return matchesCategory && matchesSearch && matchesFavorite;
    });

    nextPlaces.sort((left, right) => {
      if (activeSort === "Favorites") {
        return (
          new Date(right.favoriteCreatedAt || 0).getTime() -
          new Date(left.favoriteCreatedAt || 0).getTime()
        );
      }

      if (activeSort === "Top Rated") {
        return (right.rating || 0) - (left.rating || 0);
      }

      if (activeSort === "Most Reviewed") {
        return right.reviewCount - left.reviewCount;
      }

      return left.distanceKm - right.distanceKm;
    });

    return nextPlaces;
  }, [activeCategory, activeSort, deferredSearch, favoritePlacesWithMeta, places]);

  const visiblePlaces = filteredPlaces;
  const hasMore = activeSort !== "Favorites" && Boolean(nextCursor);
  const sentinelText = isFetchingMore ? "Loading..." : "";

  const suggestionPool = useMemo(() => {
    return Array.from(
      new Set(
        placesSource.flatMap((place) => [place.name, place.category, ...place.tags])
      )
    );
  }, [placesSource]);

  const relatedSuggestions = useMemo(() => {
    const keyword = searchDraft.trim().toLowerCase();
    const matched = suggestionPool.filter((item) =>
      !keyword ? true : item.toLowerCase().includes(keyword)
    );
    return matched.slice(0, SEARCH_SUGGESTION_LIMIT);
  }, [searchDraft, suggestionPool]);

  const recentSearchKeywords = useMemo(
    () => recentSearches.map((item) => item.search_name),
    [recentSearches]
  );

  useEffect(() => {
    if (!hasMore) return undefined;

    const target = observerRef.current;
    if (!target) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && nextCursor && !isFetchingMore) {
          setIsFetchingMore(true);
          fetchPlaces({ cursor: nextCursor, append: true })
            .catch((error) => {
              const message =
                error instanceof Error ? error.message : "Failed to load places.";
              setPlacesError(message);
            })
            .finally(() => {
              setIsFetchingMore(false);
            });
        }
      },
      { rootMargin: "220px 0px" }
    );

    observer.observe(target);

    return () => observer.disconnect();
  }, [hasMore, isFetchingMore, nextCursor, currentLocation.lat, currentLocation.lng, searchInput]);

  async function handleLogout(): Promise<void> {
    try {
      await logoutUser();
    } finally {
      navigate("/login");
    }
  }

  function syncPlaceFavoriteState(placeId: string, isFavorite: boolean): void {
    setPlacesSource((current) =>
      current.map((item) =>
        item.id === placeId ? { ...item, initialIsFavorite: isFavorite } : item
      )
    );
    setFavoritePlaces((current) =>
      isFavorite
        ? current
        : current.filter((item) => item.id !== placeId)
    );
    setSelectedPlace((current) =>
      current && current.id === placeId
        ? { ...current, isFavorite }
        : current
    );
  }

  async function toggleFavorite(place: PlaceWithMeta): Promise<void> {
    if (favoriteActionIds.includes(place.id)) {
      return;
    }

    setFavoriteActionIds((current) => [...current, place.id]);
    setPlacesError("");

    try {
      if (place.isFavorite) {
        await removeTourPlaceFavorite(place.id);
        syncPlaceFavoriteState(place.id, false);
      } else {
        await addTourPlaceFavorite(place.id);
        syncPlaceFavoriteState(place.id, true);
        await fetchFavoritePlaces();
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to update favorite place.";
      setPlacesError(message);
    } finally {
      setFavoriteActionIds((current) => current.filter((item) => item !== place.id));
    }
  }

  function openPlaceDetail(place: PlaceWithMeta): void {
    setSelectedPlace(place);
  }

  function closePlaceDetail(): void {
    setSelectedPlace(null);
  }

  function openSearchSheet(): void {
    setSearchDraft(searchInput);
    setIsSearchOpen(true);
  }

  function closeSearchSheet(): void {
    setIsSearchOpen(false);
  }

  function submitSearch(nextValue: string = searchDraft): void {
    const normalized = nextValue.trim();
    setSearchInput(normalized);
    closeSearchSheet();
  }

  async function removeRecentSearch(keyword: string): Promise<void> {
    try {
      await deleteTourSearchHistoryOne(keyword);
      setRecentSearches((current) =>
        current.filter((item) => item.search_name !== keyword)
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete search history.";
      setPlacesError(message);
    }
  }

  if (isProfileLoading) {
    return (
      <div style={styles.loading}>
        <div style={styles.loadingShell}>
          <span style={styles.spinner} />
          <p style={styles.loadingText}>Preparing your home screen</p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <header style={styles.header}>
          <div>
            <p style={styles.eyebrow}>Trip Finder</p>
            <h1 style={styles.headerTitle}>Explore Nearby Places</h1>
            <p style={styles.headerCopy}>
              Places, restaurants, and activities curated for {user.user_name}.
            </p>
          </div>
          <button style={styles.logoutButton} onClick={handleLogout}>
            Log Out
          </button>
        </header>

        <section style={styles.searchPanel}>
          <div style={styles.searchRow}>
            <label style={styles.searchWrap}>
              <SearchIcon />
              <input
                value={searchInput}
                onClick={openSearchSheet}
                onFocus={(event) => {
                  event.target.blur();
                  openSearchSheet();
                }}
                placeholder="Search attractions, food, or activities"
                style={styles.searchInput}
                readOnly
              />
            </label>
            <button
              type="button"
              style={styles.searchAction}
              aria-label="Search"
              onClick={openSearchSheet}
            >
              <SearchIcon />
            </button>
          </div>

          <div style={styles.locationBar}>
            <span style={styles.locationBadge}>{locationLabel}</span>
            <span style={styles.locationHint}>
              Viewing {filteredPlaces.length} places sorted by {activeSort.toLowerCase()}
            </span>
          </div>
        </section>

        <section style={styles.filtersSection}>
          <div style={styles.filterGroup}>
            {CATEGORY_FILTERS.map((category) => {
              const isActive = activeCategory === category;
              return (
                <button
                  key={category}
                  style={{
                    ...styles.filterChip,
                    ...(isActive ? styles.filterChipActive : {}),
                  }}
                  onClick={() => setActiveCategory(category)}
                >
                  {category}
                </button>
              );
            })}
          </div>

          <div style={styles.filterGroup}>
            {SORT_FILTERS.map((sort) => {
              const isActive = activeSort === sort;
              return (
                <button
                  key={sort}
                  style={{
                    ...styles.secondaryChip,
                    ...(isActive ? styles.secondaryChipActive : {}),
                  }}
                  onClick={() => setActiveSort(sort)}
                >
                  {sort}
                </button>
              );
            })}
          </div>
        </section>

        <section style={styles.listSection}>
          {visiblePlaces.length > 0 ? (
            visiblePlaces.map((place) => (
              <article
                key={place.id}
                className="interactive-card"
                style={styles.card}
                onClick={() => openPlaceDetail(place)}
              >
                <div style={styles.thumbnail}>
                  <span style={styles.thumbnailLabel}>{place.thumbnail.label}</span>
                </div>

                <div style={styles.cardBody}>
                  <div style={styles.cardTop}>
                    <div>
                      <p style={styles.cardCategory}>{place.category}</p>
                      <h2 style={styles.cardTitle}>{place.name}</h2>
                    </div>
                    <button
                      type="button"
                      style={{
                        ...styles.favoriteButton,
                        ...(favoriteActionIds.includes(place.id)
                          ? styles.favoriteButtonPending
                          : {}),
                      }}
                      onClick={(event: MouseEvent<HTMLButtonElement>) => {
                        event.stopPropagation();
                        void toggleFavorite(place);
                      }}
                      aria-label={`Toggle favorite for ${place.name}`}
                      disabled={favoriteActionIds.includes(place.id)}
                    >
                      <StarIcon filled={place.isFavorite} />
                    </button>
                  </div>

                  <p style={styles.cardDescription}>{place.description}</p>

                  <div style={styles.cardMeta}>
                    <div style={styles.inlineTags}>
                      {place.tags.map((tag) => (
                        <span key={tag} style={styles.inlineTag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                    <div style={styles.metaRight}>
                      <span style={styles.reviewText}>
                        {formatRating(place.rating, place.reviewCount)}
                      </span>
                      <span style={styles.distance}>
                        {formatDistance(place.distanceKm)}
                      </span>
                    </div>
                  </div>
                </div>
              </article>
            ))
          ) : (
            <div style={styles.emptyState}>
              <p style={styles.emptyTitle}>
                {placesError ||
                  (activeSort === "Favorites"
                    ? "No favorite places yet."
                    : "No places available yet.")}
              </p>
              <p style={styles.emptyCopy}>
                {activeSort === "Favorites"
                  ? "Add a place to favorites and it will appear here in latest-added order."
                  : "Search again or adjust your filters to find nearby places."}
              </p>
            </div>
          )}

          <div ref={observerRef} style={styles.scrollSentinel}>
            {sentinelText}
          </div>
        </section>
      </div>

      {selectedPlace ? (
        <div style={styles.modalOverlay} onClick={closePlaceDetail}>
          <div style={styles.modalCard} onClick={(event) => event.stopPropagation()}>
            <div style={styles.modalHero}>
              <div style={styles.modalHeroTop}>
                <span style={styles.modalCategory}>{selectedPlace.category}</span>
                <button
                  type="button"
                  style={styles.modalCloseButton}
                  onClick={closePlaceDetail}
                  aria-label="Close details"
                >
                  ×
                </button>
              </div>
              <div>
                <h2 style={styles.modalTitle}>{selectedPlace.name}</h2>
                <p style={styles.modalDistance}>
                  {locationLabel} · {formatDistance(selectedPlace.distanceKm)}
                </p>
              </div>
            </div>

            <div style={styles.modalBody}>
              <p style={styles.modalDescription}>{selectedPlace.description}</p>

              <div style={styles.detailStack}>
                <DetailRow
                  label="Address"
                  value={selectedPlace.shortAddress || selectedPlace.address}
                />
                <DetailRow
                  label="Rating"
                  value={formatRating(selectedPlace.rating, selectedPlace.reviewCount)}
                />
                <DetailRow
                  label="Price"
                  value={formatPriceRange(
                    selectedPlace.priceLevel,
                    selectedPlace.priceRange
                  )}
                />
                <DetailRow label="Phone" value={selectedPlace.phone} />
                <DetailRow
                  label="International Phone"
                  value={selectedPlace.phoneInternational}
                />
              </div>

              <div style={styles.modalInfoGrid}>
                <div style={styles.modalInfoCard}>
                  <span style={styles.modalInfoLabel}>Reviews</span>
                  <strong style={styles.modalInfoValue}>
                    {selectedPlace.reviewCount.toLocaleString()}
                  </strong>
                </div>
                <div style={styles.modalInfoCard}>
                  <span style={styles.modalInfoLabel}>Opening Hours</span>
                  <strong style={styles.modalInfoValue}>
                    {selectedPlace.openingHours[0] || "Not available"}
                  </strong>
                </div>
              </div>

              {selectedPlace.services.length > 0 ? (
                <DetailChipSection label="Services" items={selectedPlace.services} />
              ) : null}

              {selectedPlace.payment.length > 0 ? (
                <DetailChipSection label="Payment" items={selectedPlace.payment} />
              ) : null}

              {selectedPlace.accessibility.length > 0 ? (
                <DetailChipSection label="Accessibility" items={selectedPlace.accessibility} />
              ) : null}

              {selectedPlace.parking.length > 0 ? (
                <DetailChipSection label="Parking" items={selectedPlace.parking} />
              ) : null}

              <div style={styles.detailLinkRow}>
                {selectedPlace.website ? (
                  <a
                    href={selectedPlace.website}
                    target="_blank"
                    rel="noreferrer"
                    style={styles.detailLink}
                  >
                    Website
                  </a>
                ) : null}
                {selectedPlace.googleMapsUrl ? (
                  <a
                    href={selectedPlace.googleMapsUrl}
                    target="_blank"
                    rel="noreferrer"
                    style={styles.detailLink}
                  >
                    Open Map
                  </a>
                ) : null}
                {selectedPlace.googleMapReviewLink ? (
                  <a
                    href={selectedPlace.googleMapReviewLink}
                    target="_blank"
                    rel="noreferrer"
                    style={styles.detailLink}
                  >
                    View Reviews
                  </a>
                ) : null}
              </div>

              {selectedPlace.reviews.length > 0 ? (
                <div style={styles.reviewSection}>
                  <p style={styles.sectionLabel}>Reviews</p>
                  {selectedPlace.reviews.slice(0, 3).map((review, index) => (
                    <div key={`${review.author}-${index}`} style={styles.reviewCard}>
                      <div style={styles.reviewHeader}>
                        <strong>{review.author}</strong>
                        <span>
                          {[review.rating ? `${review.rating}` : null, review.relativeTime]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </div>
                      <p style={styles.reviewBody}>
                        {review.text || "No review text"}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}

              <button
                type="button"
                style={{
                  ...styles.modalFavoriteButton,
                  ...(favoriteActionIds.includes(selectedPlace.id)
                    ? styles.favoriteButtonPending
                    : {}),
                }}
                onClick={() => void toggleFavorite(selectedPlace)}
                disabled={favoriteActionIds.includes(selectedPlace.id)}
              >
                {selectedPlace.isFavorite ? "Remove Favorite" : "Add to Favorites"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {isSearchOpen ? (
        <div style={styles.modalOverlay} onClick={closeSearchSheet}>
          <div style={styles.searchSheet} onClick={(event) => event.stopPropagation()}>
            <div style={styles.searchSheetHandle} />
            <div style={styles.searchSheetHeader}>
              <label style={styles.searchSheetInputWrap}>
                <SearchIcon />
                <input
                  autoFocus
                  value={searchDraft}
                  onChange={(event) => setSearchDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      submitSearch();
                    }
                  }}
                  placeholder="Search attractions, food, or activities"
                  style={styles.searchSheetInput}
                />
              </label>
              <button
                type="button"
                style={styles.searchSheetClose}
                onClick={closeSearchSheet}
              >
                Cancel
              </button>
            </div>

            <div style={styles.searchSheetSection}>
              <div style={styles.searchSheetLabelRow}>
                <p style={styles.searchSheetTitle}>Suggested Searches</p>
                <button
                  type="button"
                  style={styles.linkButton}
                  onClick={() => submitSearch()}
                >
                  Search
                </button>
              </div>
              <div style={styles.searchSuggestionGrid}>
                {relatedSuggestions.length > 0 ? (
                  relatedSuggestions.map((keyword) => (
                    <button
                      key={keyword}
                      type="button"
                      style={styles.searchKeywordChip}
                      onClick={() => submitSearch(keyword)}
                    >
                      {keyword}
                    </button>
                  ))
                ) : (
                  <p style={styles.searchEmpty}>No suggestions yet.</p>
                )}
              </div>
            </div>

            <div style={styles.searchSheetSection}>
              <div style={styles.searchSheetLabelRow}>
                <p style={styles.searchSheetTitle}>Recent Searches</p>
              </div>
              {recentSearches.length > 0 ? (
                <div style={styles.recentList}>
                  {recentSearchKeywords.map((keyword) => (
                    <div key={keyword} style={styles.recentItem}>
                      <button
                        type="button"
                        style={styles.recentKeywordButton}
                        onClick={() => submitSearch(keyword)}
                      >
                        {keyword}
                      </button>
                      <button
                        type="button"
                        style={styles.recentDeleteButton}
                        onClick={() => void removeRecentSearch(keyword)}
                        aria-label={`Delete ${keyword}`}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={styles.searchEmpty}>No recent searches yet.</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M10.5 18a7.5 7.5 0 1 1 5.303-12.803A7.5 7.5 0 0 1 10.5 18Zm0-13a5.5 5.5 0 1 0 0 11a5.5 5.5 0 0 0 0-11Zm10 15l-4.35-4.35"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="m12 3.75l2.547 5.163l5.697.828l-4.122 4.018l.973 5.674L12 16.756l-5.095 2.677l.973-5.674L3.756 9.74l5.697-.828L12 3.75Z"
        fill={filled ? "#9f9f9f" : "transparent"}
        stroke="#6f6f6f"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DetailRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;

  return (
    <div style={styles.detailRow}>
      <span style={styles.detailLabel}>{label}</span>
      <span style={styles.detailValue}>{value}</span>
    </div>
  );
}

function DetailChipSection({
  label,
  items,
}: {
  label: string;
  items: string[];
}) {
  return (
    <div style={styles.detailSection}>
      <p style={styles.sectionLabel}>{label}</p>
      <div style={styles.inlineTags}>
        {items.map((item) => (
          <span key={item} style={styles.inlineTag}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  loading: {
    minHeight: "100dvh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#ffffff",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  loadingShell: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 16,
    color: "#444444",
  },
  loadingText: {
    margin: 0,
    fontSize: "0.95rem",
    color: "#777777",
  },
  spinner: {
    display: "block",
    width: 42,
    height: 42,
    borderRadius: "50%",
    border: "4px solid rgba(180, 180, 180, 0.28)",
    borderTop: "4px solid #8c8c8c",
    animation: "spin 0.8s linear infinite",
  },
  page: {
    minHeight: "100dvh",
    padding: "24px 16px 40px",
    background: "#ffffff",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  shell: {
    width: "100%",
    maxWidth: 760,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 18,
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    paddingTop: 8,
  },
  eyebrow: {
    margin: 0,
    color: "#8a8a8a",
    fontSize: "0.78rem",
    fontWeight: 800,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
  },
  headerTitle: {
    margin: "6px 0 8px",
    fontSize: "clamp(1.9rem, 5vw, 2.4rem)",
    lineHeight: 1.05,
    color: "#222222",
  },
  headerCopy: {
    maxWidth: 440,
    margin: 0,
    fontSize: "0.95rem",
    lineHeight: 1.5,
    color: "#777777",
  },
  logoutButton: {
    border: "1px solid #dfdfdf",
    borderRadius: 999,
    padding: "12px 16px",
    background: "#f2f2f2",
    color: "#444444",
    fontWeight: 700,
    cursor: "pointer",
    boxShadow: "0 8px 18px rgba(0, 0, 0, 0.05)",
  },
  searchPanel: {
    padding: 20,
    borderRadius: 28,
    background: "#f7f7f7",
    border: "1px solid #ececec",
    boxShadow: "0 10px 24px rgba(0, 0, 0, 0.05)",
  },
  searchRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  searchWrap: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "0 14px",
    minHeight: 56,
    borderRadius: 20,
    border: "1.5px solid #dfdfdf",
    background: "#ffffff",
    color: "#666666",
  },
  searchInput: {
    width: "100%",
    border: "none",
    outline: "none",
    background: "transparent",
    fontSize: "1rem",
    color: "#222222",
    fontFamily: "inherit",
  },
  searchAction: {
    width: 54,
    height: 54,
    borderRadius: "50%",
    border: "1px solid #d8d8d8",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#d9d9d9",
    color: "#333333",
    boxShadow: "0 8px 18px rgba(0, 0, 0, 0.07)",
    flexShrink: 0,
    cursor: "pointer",
  },
  locationBar: {
    marginTop: 14,
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    alignItems: "center",
  },
  locationBadge: {
    padding: "8px 12px",
    borderRadius: 999,
    background: "#ebebeb",
    color: "#555555",
    fontSize: "0.82rem",
    fontWeight: 700,
  },
  locationHint: {
    color: "#7a7a7a",
    fontSize: "0.86rem",
  },
  filtersSection: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  filterGroup: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    justifyContent: "center",
  },
  filterChip: {
    border: "1px solid #dfdfdf",
    borderRadius: 999,
    padding: "12px 18px",
    background: "#f3f3f3",
    color: "#555555",
    fontWeight: 800,
    fontSize: "0.98rem",
    cursor: "pointer",
  },
  filterChipActive: {
    background: "#d9d9d9",
    color: "#222222",
    boxShadow: "0 8px 18px rgba(0, 0, 0, 0.05)",
  },
  secondaryChip: {
    border: "1px solid #dfdfdf",
    borderRadius: 999,
    padding: "10px 16px",
    background: "#f3f3f3",
    color: "#666666",
    fontWeight: 700,
    cursor: "pointer",
  },
  secondaryChipActive: {
    background: "#d9d9d9",
    color: "#222222",
  },
  listSection: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  card: {
    display: "grid",
    gridTemplateColumns: "116px 1fr",
    gap: 16,
    padding: 16,
    borderRadius: 28,
    background: "#fbfbfb",
    border: "1px solid #ececec",
    boxShadow: "0 8px 18px rgba(0, 0, 0, 0.04)",
    cursor: "pointer",
  },
  thumbnail: {
    minHeight: 116,
    borderRadius: 22,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "flex-start",
    padding: 12,
    boxSizing: "border-box",
    background: "#e9e9e9",
  },
  thumbnailLabel: {
    padding: "6px 10px",
    borderRadius: 999,
    background: "#d3d3d3",
    color: "#444444",
    fontSize: "0.75rem",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  cardBody: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
    minWidth: 0,
  },
  cardTop: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    alignItems: "flex-start",
  },
  cardCategory: {
    margin: 0,
    color: "#777777",
    fontSize: "0.82rem",
    fontWeight: 800,
  },
  cardTitle: {
    margin: "2px 0 0",
    color: "#222222",
    fontSize: "1.35rem",
    fontWeight: 800,
    lineHeight: 1.08,
  },
  favoriteButton: {
    width: 40,
    height: 40,
    borderRadius: "50%",
    border: "1px solid #dfdfdf",
    display: "grid",
    placeItems: "center",
    background: "#efefef",
    cursor: "pointer",
    flexShrink: 0,
  },
  favoriteButtonPending: {
    opacity: 0.55,
    cursor: "wait",
  },
  cardDescription: {
    margin: 0,
    color: "#666666",
    lineHeight: 1.5,
    fontSize: "0.95rem",
  },
  cardMeta: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    alignItems: "flex-end",
    flexWrap: "wrap",
  },
  inlineTags: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  inlineTag: {
    padding: "7px 10px",
    borderRadius: 999,
    background: "#ededed",
    color: "#5c5c5c",
    fontSize: "0.78rem",
    fontWeight: 700,
  },
  metaRight: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: 4,
  },
  distance: {
    color: "#222222",
    fontWeight: 800,
    fontSize: "0.96rem",
  },
  reviewText: {
    color: "#7a7a7a",
    fontSize: "0.8rem",
  },
  emptyState: {
    padding: "48px 20px",
    textAlign: "center",
    borderRadius: 28,
    background: "#f7f7f7",
    color: "#777777",
    border: "1px solid #ececec",
  },
  emptyTitle: {
    margin: 0,
    fontSize: "1.05rem",
    fontWeight: 800,
    color: "#333333",
  },
  emptyCopy: {
    margin: "8px 0 0",
    lineHeight: 1.5,
  },
  scrollSentinel: {
    minHeight: 28,
    padding: "12px 0 4px",
    textAlign: "center",
    color: "#888888",
    fontSize: "0.9rem",
    fontWeight: 700,
  },
  modalOverlay: {
    position: "fixed",
    inset: 0,
    padding: "16px 16px 0",
    background: "rgba(0, 0, 0, 0.4)",
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
    zIndex: 20,
    animation: "fadeInOverlay 220ms ease-out",
  },
  modalCard: {
    width: "100%",
    maxWidth: 760,
    minHeight: "78dvh",
    maxHeight: "88dvh",
    overflowY: "auto",
    borderRadius: "32px 32px 0 0",
    background: "#ffffff",
    boxShadow: "0 24px 64px rgba(0, 0, 0, 0.16)",
    animation: "slideUpModal 280ms cubic-bezier(0.22, 1, 0.36, 1)",
  },
  modalHero: {
    padding: 22,
    minHeight: 220,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    borderRadius: "32px 32px 0 0",
    background: "#d9d9d9",
  },
  modalHeroTop: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  modalCategory: {
    padding: "8px 12px",
    borderRadius: 999,
    background: "rgba(255,255,255,0.42)",
    fontSize: "0.8rem",
    fontWeight: 800,
    color: "#444444",
  },
  modalCloseButton: {
    width: 38,
    height: 38,
    border: "1px solid rgba(255,255,255,0.4)",
    borderRadius: "50%",
    background: "rgba(255,255,255,0.54)",
    color: "#444444",
    fontSize: "1.5rem",
    lineHeight: 1,
    cursor: "pointer",
  },
  modalTitle: {
    margin: 0,
    fontSize: "2rem",
    fontWeight: 800,
    lineHeight: 1.05,
    color: "#222222",
  },
  modalDistance: {
    marginTop: 10,
    fontSize: "0.92rem",
    color: "#555555",
  },
  modalBody: {
    padding: 22,
    display: "flex",
    flexDirection: "column",
    gap: 18,
  },
  modalDescription: {
    margin: 0,
    color: "#555555",
    lineHeight: 1.65,
    fontSize: "0.98rem",
  },
  detailStack: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  detailRow: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "flex-start",
  },
  detailLabel: {
    flexShrink: 0,
    color: "#7a7a7a",
    fontSize: "0.85rem",
    fontWeight: 700,
  },
  detailValue: {
    color: "#333333",
    fontSize: "0.9rem",
    textAlign: "right",
    lineHeight: 1.5,
  },
  modalInfoGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  modalInfoCard: {
    padding: 16,
    borderRadius: 20,
    background: "#f3f3f3",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  modalInfoLabel: {
    color: "#777777",
    fontSize: "0.82rem",
    fontWeight: 700,
  },
  modalInfoValue: {
    color: "#333333",
    fontSize: "0.98rem",
  },
  detailSection: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  sectionLabel: {
    margin: 0,
    color: "#666666",
    fontSize: "0.86rem",
    fontWeight: 800,
  },
  detailLinkRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
  },
  detailLink: {
    color: "#333333",
    textDecoration: "none",
    fontWeight: 700,
    fontSize: "0.92rem",
  },
  reviewSection: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  reviewCard: {
    padding: "14px 16px",
    borderRadius: 18,
    background: "#f3f3f3",
  },
  reviewHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 8,
    color: "#666666",
    fontSize: "0.82rem",
  },
  reviewBody: {
    margin: 0,
    color: "#3f3f3f",
    lineHeight: 1.6,
    fontSize: "0.9rem",
  },
  modalFavoriteButton: {
    width: "100%",
    border: "1px solid #d8d8d8",
    borderRadius: 18,
    padding: "15px 18px",
    background: "#d9d9d9",
    color: "#222222",
    fontWeight: 800,
    fontSize: "1rem",
    cursor: "pointer",
  },
  searchSheet: {
    width: "100%",
    maxWidth: 760,
    minHeight: "56dvh",
    borderRadius: "30px 30px 0 0",
    background: "#ffffff",
    boxShadow: "0 24px 64px rgba(0, 0, 0, 0.16)",
    padding: "10px 18px 26px",
    animation: "slideUpModal 280ms cubic-bezier(0.22, 1, 0.36, 1)",
  },
  searchSheetHandle: {
    width: 56,
    height: 6,
    borderRadius: 999,
    background: "#d8d8d8",
    margin: "4px auto 16px",
  },
  searchSheetHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  searchSheetInputWrap: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "0 14px",
    minHeight: 54,
    borderRadius: 18,
    background: "#f3f3f3",
    color: "#666666",
  },
  searchSheetInput: {
    width: "100%",
    border: "none",
    outline: "none",
    background: "transparent",
    color: "#222222",
    fontSize: "1rem",
  },
  searchSheetClose: {
    border: "none",
    background: "transparent",
    color: "#666666",
    fontWeight: 700,
    cursor: "pointer",
    padding: "10px 4px",
  },
  searchSheetSection: {
    marginTop: 24,
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  searchSheetLabelRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  searchSheetTitle: {
    margin: 0,
    color: "#444444",
    fontWeight: 800,
    fontSize: "0.96rem",
  },
  linkButton: {
    border: "none",
    background: "transparent",
    color: "#555555",
    fontWeight: 800,
    cursor: "pointer",
    padding: 0,
  },
  searchSuggestionGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  searchKeywordChip: {
    border: "1px solid #dfdfdf",
    borderRadius: 999,
    padding: "11px 14px",
    background: "#efefef",
    color: "#444444",
    fontWeight: 700,
    cursor: "pointer",
  },
  recentList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  recentItem: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "12px 14px",
    borderRadius: 16,
    background: "#f7f7f7",
    border: "1px solid #ececec",
  },
  recentKeywordButton: {
    border: "none",
    background: "transparent",
    color: "#333333",
    fontWeight: 700,
    padding: 0,
    cursor: "pointer",
  },
  recentDeleteButton: {
    width: 28,
    height: 28,
    border: "none",
    borderRadius: "50%",
    background: "#e3e3e3",
    color: "#666666",
    fontSize: "1rem",
    lineHeight: 1,
    cursor: "pointer",
  },
  searchEmpty: {
    margin: 0,
    color: "#777777",
    lineHeight: 1.5,
  },
};
