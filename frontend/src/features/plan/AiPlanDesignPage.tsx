import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { getTourPlaces, type TourPlaceApiItem } from "../../api/auth/auth";
import {
  BRAND,
  budgetCategoryIcon,
  budgetCategoryFromValue,
  budgetCategoryLabel,
  formatBudgetValue,
  companionOptions,
  durationOptions,
  foodNeeds,
  styleTokens,
  type AiPreferenceState,
} from "../../api/aiPlanShared";

interface AiPlanDesignPageProps {
  value: AiPreferenceState;
  onBack: () => void;
  onChange: (next: AiPreferenceState) => void;
  onSubmit: () => void;
  isGenerating: boolean;
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

interface ExtraPlaceOption {
  placeId: string;
  name: string;
  address: string;
  category: string;
}

const CLUSTERS = [
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

const paceOptions = [
  { value: "Slow", label: "Relaxed" },
  { value: "Packed", label: "Packed" },
] as const;

function toPlanValue(value: AiPreferenceState): AiPreferenceStateV2 {
  return value as AiPreferenceStateV2;
}

function getDayInputs(value: AiPreferenceStateV2): AiPlanDayInput[] {
  const travelDays = Math.max(1, Math.min(3, value.durationDays || 1));
  const existing = Array.isArray(value.days) ? value.days : [];

  return Array.from({ length: travelDays }, (_, index) => ({
    departureCluster:
      existing[index]?.departureCluster || value.departure || CLUSTERS[0],
    arrivalCluster:
      existing[index]?.arrivalCluster || value.arrival || CLUSTERS[0],
    startTime: existing[index]?.startTime || value.startTime || "10:00",
    endTime: existing[index]?.endTime || value.endTime || "21:00",
    additionalPlaceId:
      existing[index]?.additionalPlaceId ?? value.additionalPlaceId ?? null,
  }));
}

function normalizePlace(item: TourPlaceApiItem): ExtraPlaceOption | null {
  const placeId = String(item.place_id || item.id || "");
  const name = String(item.display_name || item.name || item.title || "");
  if (!placeId || !name) return null;

  return {
    placeId,
    name,
    address: String(item.short_address || item.address || ""),
    category: String(item.category || item.type || item.place_type || "Place"),
  };
}

function ChipButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: active ? `1px solid ${BRAND}` : "1px solid #d7ecec",
        background: active ? "rgba(1, 192, 192, 0.12)" : "#ffffff",
        color: active ? "#0b6161" : "#365657",
        padding: "11px 14px",
        borderRadius: 14,
        fontSize: 13,
        fontWeight: 700,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}

export default function AiPlanDesignPage({
  value,
  onBack,
  onChange,
  onSubmit,
  isGenerating,
}: AiPlanDesignPageProps) {
  const planValue = toPlanValue(value);
  const dayInputs = useMemo(() => getDayInputs(planValue), [planValue]);
  const [extraResults, setExtraResults] = useState<ExtraPlaceOption[]>([]);
  const [isSearchingExtra, setIsSearchingExtra] = useState(false);
  const [extraSearchMessage, setExtraSearchMessage] = useState("");

  const emitChange = (next: AiPreferenceStateV2) => {
    onChange(next as AiPreferenceState);
  };

  const setField = <K extends keyof AiPreferenceState>(
    field: K,
    fieldValue: AiPreferenceState[K]
  ) => {
    emitChange({ ...planValue, [field]: fieldValue });
  };

  const setDayField = <K extends keyof AiPlanDayInput>(
    index: number,
    field: K,
    fieldValue: AiPlanDayInput[K]
  ) => {
    const nextDays = dayInputs.map((day, dayIndex) =>
      dayIndex === index ? { ...day, [field]: fieldValue } : day
    );

    emitChange({
      ...planValue,
      departure: nextDays[0]?.departureCluster || "",
      arrival: nextDays[nextDays.length - 1]?.arrivalCluster || "",
      startTime: nextDays[0]?.startTime || planValue.startTime,
      endTime: nextDays[nextDays.length - 1]?.endTime || planValue.endTime,
      days: nextDays,
    });
  };

  const setDuration = (durationDays: number) => {
    const currentDays = getDayInputs({ ...planValue, durationDays });
    emitChange({
      ...planValue,
      durationDays,
      days: currentDays,
      departure: currentDays[0]?.departureCluster || "",
      arrival: currentDays[currentDays.length - 1]?.arrivalCluster || "",
    });
  };

  const toggleStyle = (token: string) => {
    const nextStyles = value.styles.includes(token)
      ? value.styles.filter((item) => item !== token)
      : [...value.styles, token];

    emitChange({
      ...planValue,
      styles: nextStyles,
    });
  };

  const handleBudgetChange = (nextValue: number) => {
    emitChange({
      ...planValue,
      budgetValue: nextValue,
      budgetCategory: budgetCategoryFromValue(nextValue),
    });
  };

  const searchExtraPlace = () => {
    const keyword = planValue.extraPlace.trim();
    setExtraResults([]);
    setExtraSearchMessage("");

    if (!keyword) {
      setExtraSearchMessage("Enter a place keyword first.");
      return;
    }

    setIsSearchingExtra(true);
    void getTourPlaces({ keyword })
      .then((response) => {
        const places = response.items
          .map(normalizePlace)
          .filter((item): item is ExtraPlaceOption => Boolean(item));
        setExtraResults(places);
        setExtraSearchMessage(
          places.length > 0
            ? "Select one result to include it in the itinerary."
            : "No matching place was found."
        );
      })
      .catch((error) => {
        setExtraResults([]);
        setExtraSearchMessage(
          error instanceof Error ? error.message : "Failed to search places."
        );
      })
      .finally(() => setIsSearchingExtra(false));
  };

  const selectExtraPlace = (place: ExtraPlaceOption) => {
    const nextDays = dayInputs.map((day) => ({
      ...day,
      additionalPlaceId: place.placeId,
    }));

    emitChange({
      ...planValue,
      extraPlace: place.name,
      additionalPlaceId: place.placeId,
      additionalPlaceName: place.name,
      days: nextDays,
    });
    setExtraSearchMessage(`${place.name} will be included in the recommendation.`);
  };

  const clearExtraPlace = () => {
    const nextDays = dayInputs.map((day) => ({
      ...day,
      additionalPlaceId: null,
    }));
    emitChange({
      ...planValue,
      extraPlace: "",
      additionalPlaceId: null,
      additionalPlaceName: "",
      days: nextDays,
    });
    setExtraResults([]);
    setExtraSearchMessage("");
  };

  const hasInvalidTime = dayInputs.some((day) => day.startTime >= day.endTime);
  const canGenerate = Boolean(
    dayInputs.length === value.durationDays &&
      dayInputs.every(
        (day) =>
          day.departureCluster &&
          day.arrivalCluster &&
          day.startTime &&
          day.endTime &&
          day.startTime < day.endTime
      ) &&
      value.styles.length > 0 &&
      value.pace &&
      value.companion
  );

  return (
    <div style={styles.page}>
      <div style={styles.phoneFrame}>
        <div style={styles.headerRow}>
          <button type="button" onClick={onBack} style={styles.iconButton}>
            {"<"}
          </button>
          <span style={styles.headerBadge}>AI Planner</span>
        </div>

        <div style={styles.titleBlock}>
          <span style={styles.eyebrow}>Recommendation API V2</span>
          <h1 style={styles.title}>Build a day-by-day Seoul route</h1>
          <p style={styles.copy}>
            Select exact Seoul clusters and daily time windows. The same end time rule is used for airport arrival planning.
          </p>
        </div>

        <div style={styles.panel}>
          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Duration</span>
            <div style={styles.segmentedWrap}>
              {durationOptions.map((days) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => setDuration(days)}
                  style={{
                    ...styles.segmentButton,
                    ...(value.durationDays === days ? styles.segmentButtonActive : {}),
                  }}
                >
                  {days} day{days > 1 ? "s" : ""}
                </button>
              ))}
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Daily route settings</span>
            <div style={styles.dayStack}>
              {dayInputs.map((day, index) => (
                <section key={`day-${index + 1}`} style={styles.dayPanel}>
                  <div style={styles.dayHeader}>
                    <strong>Day {index + 1}</strong>
                    <span style={styles.dayBadge}>Cluster + time</span>
                  </div>
                  <label style={styles.fieldLabel}>
                    Departure cluster
                    <select
                      value={day.departureCluster}
                      onChange={(event) =>
                        setDayField(index, "departureCluster", event.target.value)
                      }
                      style={styles.textInput}
                    >
                      {CLUSTERS.map((cluster) => (
                        <option key={cluster} value={cluster}>
                          {cluster}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label style={styles.fieldLabel}>
                    Arrival cluster
                    <select
                      value={day.arrivalCluster}
                      onChange={(event) =>
                        setDayField(index, "arrivalCluster", event.target.value)
                      }
                      style={styles.textInput}
                    >
                      {CLUSTERS.map((cluster) => (
                        <option key={cluster} value={cluster}>
                          {cluster}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div style={styles.twoColumn}>
                    <label style={styles.fieldLabel}>
                      Start time
                      <input
                        type="time"
                        value={day.startTime}
                        onChange={(event) =>
                          setDayField(index, "startTime", event.target.value)
                        }
                        style={styles.textInput}
                      />
                    </label>
                    <label style={styles.fieldLabel}>
                      End time
                      <input
                        type="time"
                        value={day.endTime}
                        onChange={(event) =>
                          setDayField(index, "endTime", event.target.value)
                        }
                        style={styles.textInput}
                      />
                    </label>
                  </div>
                </section>
              ))}
            </div>
            {hasInvalidTime ? (
              <p style={styles.errorText}>Each day needs start time earlier than end time.</p>
            ) : null}
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Travel Style</span>
            <div style={styles.chipGrid}>
              {styleTokens.map((token) => (
                <ChipButton
                  key={token}
                  active={value.styles.includes(token)}
                  label={token}
                  onClick={() => toggleStyle(token)}
                />
              ))}
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Schedule density</span>
            <div style={styles.segmentedWrapTwo}>
              {paceOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setField("pace", option.value)}
                  style={{
                    ...styles.segmentButton,
                    ...(value.pace === option.value ? styles.segmentButtonActive : {}),
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div style={styles.twoColumn}>
            <div style={styles.fieldBlock}>
              <span style={styles.fieldLegend}>Transport</span>
              <ChipButton
                active
                label="Public Transit"
                onClick={() => setField("transport", "Public Transit")}
              />
            </div>

            <div style={styles.fieldBlock}>
              <span style={styles.fieldLegend}>Companion</span>
              <div style={styles.chipGrid}>
                {companionOptions.map((option) => (
                  <ChipButton
                    key={option}
                    active={value.companion === option}
                    label={option}
                    onClick={() => setField("companion", option)}
                  />
                ))}
              </div>
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <div style={styles.budgetHeader}>
              <span style={styles.fieldLegend}>Budget per person</span>
              <span style={styles.budgetBadge}>
                <span style={styles.budgetIcon}>
                  {budgetCategoryIcon(value.budgetCategory)}
                </span>
                {budgetCategoryLabel(value.budgetCategory)} ₩{formatBudgetValue(value.budgetValue)}
              </span>
            </div>
            <input
              type="range"
              min={5}
              max={500}
              step={5}
              value={value.budgetValue}
              onChange={(event) => handleBudgetChange(Number(event.target.value))}
              style={styles.rangeInput}
            />
            <div style={styles.rangeLabels}>
              <span>₩50,000</span>
              <span>₩5,000,000</span>
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Food preference</span>
            <div style={styles.chipGrid}>
              <ChipButton
                active={!value.foodNeed}
                label="Any"
                onClick={() => setField("foodNeed", "")}
              />
              {foodNeeds.map((item) => (
                <ChipButton
                  key={item}
                  active={value.foodNeed === item}
                  label={item}
                  onClick={() =>
                    setField("foodNeed", value.foodNeed === item ? "" : item)
                  }
                />
              ))}
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Extra Place</span>
            <div style={styles.searchRow}>
              <input
                value={value.extraPlace}
                onChange={(event) => {
                  emitChange({
                    ...planValue,
                    extraPlace: event.target.value,
                    additionalPlaceId: null,
                    additionalPlaceName: "",
                    days: dayInputs.map((day) => ({
                      ...day,
                      additionalPlaceId: null,
                    })),
                  });
                }}
                style={styles.textInput}
                placeholder="Search a place and select one result"
              />
              <button
                type="button"
                onClick={searchExtraPlace}
                style={styles.searchButton}
                disabled={isSearchingExtra}
              >
                {isSearchingExtra ? "..." : "Search"}
              </button>
            </div>
            {planValue.additionalPlaceId ? (
              <div style={styles.selectedPlaceRow}>
                <span>{planValue.additionalPlaceName || value.extraPlace}</span>
                <button type="button" onClick={clearExtraPlace} style={styles.clearButton}>
                  Clear
                </button>
              </div>
            ) : null}
            {extraSearchMessage ? (
              <p style={styles.helperText}>{extraSearchMessage}</p>
            ) : null}
            {extraResults.length > 0 ? (
              <div style={styles.extraResults}>
                {extraResults.map((place) => (
                  <button
                    key={place.placeId}
                    type="button"
                    onClick={() => selectExtraPlace(place)}
                    style={styles.extraResultCard}
                  >
                    <strong>{place.name}</strong>
                    <span>{place.address || place.category}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <button
          type="button"
          onClick={onSubmit}
          style={{
            ...styles.primaryAction,
            ...(canGenerate ? null : styles.primaryActionDisabled),
          }}
          disabled={!canGenerate || isGenerating}
        >
          {isGenerating ? "Generating plan..." : "Generate AI itinerary"}
        </button>
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
  panel: {
    display: "flex",
    flexDirection: "column",
    gap: 18,
    padding: 20,
    borderRadius: 24,
    background: "#ffffff",
    border: "1px solid #dceeee",
    boxShadow: "0 12px 30px rgba(16, 34, 35, 0.06)",
  },
  fieldLabel: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    color: "#204444",
    fontSize: 13,
    fontWeight: 800,
  },
  fieldBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  fieldLegend: {
    color: "#204444",
    fontSize: 13,
    fontWeight: 800,
  },
  textInput: {
    width: "100%",
    minHeight: 48,
    borderRadius: 14,
    border: "1px solid #d7ecec",
    background: "#fcffff",
    padding: "0 14px",
    fontSize: 14,
    color: "#183536",
    boxSizing: "border-box",
  },
  chipGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  segmentedWrap: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 8,
  },
  segmentedWrapTwo: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 8,
  },
  segmentButton: {
    minHeight: 46,
    borderRadius: 14,
    border: "1px solid #d7ecec",
    background: "#ffffff",
    color: "#365657",
    fontSize: 13,
    fontWeight: 800,
    cursor: "pointer",
  },
  segmentButtonActive: {
    border: `1px solid ${BRAND}`,
    background: "rgba(1, 192, 192, 0.12)",
    color: "#0b6161",
  },
  dayStack: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  dayPanel: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    padding: 14,
    borderRadius: 18,
    background: "#fbffff",
    border: "1px solid #dceeee",
  },
  dayHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    color: "#102223",
    fontSize: 14,
  },
  dayBadge: {
    color: BRAND,
    fontSize: 12,
    fontWeight: 800,
  },
  twoColumn: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  budgetHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  budgetBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "7px 10px",
    borderRadius: 999,
    background: "rgba(255,190,15,0.18)",
    color: "#7a5400",
    fontSize: 12,
    fontWeight: 800,
  },
  budgetIcon: {
    minWidth: 24,
    textAlign: "center",
    fontSize: 11,
    fontWeight: 900,
  },
  rangeInput: {
    width: "100%",
    accentColor: BRAND,
  },
  rangeLabels: {
    display: "flex",
    justifyContent: "space-between",
    color: "#5f7b7b",
    fontSize: 12,
    fontWeight: 700,
  },
  searchRow: {
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 10,
  },
  searchButton: {
    minWidth: 78,
    minHeight: 48,
    border: "none",
    borderRadius: 14,
    background: "#FFBE0F",
    color: "#533800",
    padding: "0 14px",
    fontSize: 13,
    fontWeight: 900,
    cursor: "pointer",
  },
  selectedPlaceRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    padding: "10px 12px",
    borderRadius: 14,
    background: "rgba(1, 192, 192, 0.1)",
    color: "#204444",
    fontSize: 13,
    fontWeight: 800,
  },
  clearButton: {
    border: "none",
    borderRadius: 999,
    padding: "7px 10px",
    background: "#ffffff",
    color: "#7a5400",
    fontSize: 12,
    fontWeight: 800,
    cursor: "pointer",
  },
  helperText: {
    margin: 0,
    color: "#5f7b7b",
    fontSize: 12,
    lineHeight: 1.5,
  },
  errorText: {
    margin: 0,
    color: "#b33b3b",
    fontSize: 12,
    fontWeight: 800,
  },
  extraResults: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  extraResultCard: {
    border: "1px solid #dceeee",
    borderRadius: 14,
    background: "#ffffff",
    padding: 12,
    textAlign: "left",
    display: "flex",
    flexDirection: "column",
    gap: 5,
    color: "#204444",
    cursor: "pointer",
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
  primaryActionDisabled: {
    opacity: 0.45,
    cursor: "not-allowed",
    boxShadow: "none",
  },
};
