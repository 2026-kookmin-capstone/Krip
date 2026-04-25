import type { CSSProperties } from "react";
import {
  BRAND,
  budgetCategoryIcon,
  budgetCategoryFromValue,
  budgetCategoryLabel,
  formatBudgetValue,
  companionOptions,
  durationOptions,
  foodNeeds,
  paceOptions,
  transportOptions,
  styleTokens,
  type AiPreferenceState,
} from "../team/api/aiPlanShared";

interface AiPlanDesignPageProps {
  value: AiPreferenceState;
  onBack: () => void;
  onChange: (next: AiPreferenceState) => void;
  onSubmit: () => void;
  isGenerating: boolean;
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
  const setField = <K extends keyof AiPreferenceState>(
    field: K,
    fieldValue: AiPreferenceState[K]
  ) => {
    onChange({ ...value, [field]: fieldValue });
  };

  const toggleStyle = (token: string) => {
    const nextStyles = value.styles.includes(token)
      ? value.styles.filter((item) => item !== token)
      : [...value.styles, token];

    onChange({
      ...value,
      styles: nextStyles.slice(0, 4),
    });
  };

  const handleBudgetChange = (nextValue: number) => {
    onChange({
      ...value,
      budgetValue: nextValue,
      budgetCategory: budgetCategoryFromValue(nextValue),
    });
  };

  const canGenerate = Boolean(
    value.departure.trim() &&
      value.arrival.trim() &&
      value.styles.length > 0 &&
      value.pace &&
      value.transport &&
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
          <span style={styles.eyebrow}>Preference Tokens</span>
          <h1 style={styles.title}>Tell AI how you want to travel</h1>
          <p style={styles.copy}>
            No tokens are preselected. Choose only the signals you want the AI planner to use.
          </p>
        </div>

        <div style={styles.panel}>
          <label style={styles.fieldLabel}>
            Departure
            <input
              value={value.departure}
              onChange={(event) => setField("departure", event.target.value)}
              style={styles.textInput}
              placeholder="Enter a place"
            />
          </label>

          <label style={styles.fieldLabel}>
            Arrival
            <input
              value={value.arrival}
              onChange={(event) => setField("arrival", event.target.value)}
              style={styles.textInput}
              placeholder="Enter a place"
            />
          </label>

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
            <span style={styles.fieldLegend}>Pace</span>
            <div style={styles.segmentedWrap}>
              {paceOptions.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setField("pace", option)}
                  style={{
                    ...styles.segmentButton,
                    ...(value.pace === option ? styles.segmentButtonActive : {}),
                  }}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          <label style={styles.fieldLabel}>
            Extra Place
            <input
              value={value.extraPlace}
              onChange={(event) => setField("extraPlace", event.target.value)}
              style={styles.textInput}
              placeholder="Enter a place"
            />
          </label>

          <div style={styles.twoColumn}>
            <div style={styles.fieldBlock}>
              <span style={styles.fieldLegend}>Transport</span>
              <div style={styles.chipGrid}>
                {transportOptions.map((option) => (
                  <ChipButton
                    key={option}
                    active={value.transport === option}
                    label={option}
                    onClick={() => setField("transport", option)}
                  />
                ))}
              </div>
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

          <div style={styles.twoColumn}>
            <label style={styles.fieldLabel}>
              Start Time
              <input
                type="time"
                value={value.startTime}
                onChange={(event) => setField("startTime", event.target.value)}
                style={styles.textInput}
              />
            </label>
            <label style={styles.fieldLabel}>
              End Time
              <input
                type="time"
                value={value.endTime}
                onChange={(event) => setField("endTime", event.target.value)}
                style={styles.textInput}
              />
            </label>
          </div>

          <div style={styles.fieldBlock}>
            <div style={styles.budgetHeader}>
              <span style={styles.fieldLegend}>Budget</span>
              <span style={styles.budgetBadge}>
                <span style={styles.budgetIcon}>
                  {budgetCategoryIcon(value.budgetCategory)}
                </span>
                {budgetCategoryLabel(value.budgetCategory)} {formatBudgetValue(value.budgetValue)}
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
              <span>Low</span>
              <span>Moderate</span>
              <span>High</span>
            </div>
          </div>

          <div style={styles.fieldBlock}>
            <span style={styles.fieldLegend}>Food Need</span>
            <div style={styles.chipGrid}>
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
            <span style={styles.fieldLegend}>Duration</span>
            <div style={styles.segmentedWrap}>
              {durationOptions.map((days) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => setField("durationDays", days)}
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
