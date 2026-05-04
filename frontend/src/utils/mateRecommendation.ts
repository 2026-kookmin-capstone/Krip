export type RecommendationCandidate = {
  user_id: string;
  user_name: string;
  profile_image_url: string | null;
  travel_styles: string[];
  nationality: string;
  [key: string]: unknown;
};

export type RecommendedTraveler = RecommendationCandidate & {
  similarity_score: number;
};

const TRAVEL_STYLE_KEYS = [
  "activity",
  "relaxation",
  "tourism",
  "shopping",
  "food",
] as const;

export function recommendTravelers(
  currentUser: {
    user_id?: string | null;
    travel_styles?: string[];
    nationality?: string;
  },
  candidates: RecommendationCandidate[],
  topN = 10
): RecommendedTraveler[] {
  const myVector = toTravelStyleVector(currentUser.travel_styles ?? []);

  return candidates
    .filter((candidate) => candidate.user_id !== currentUser.user_id)
    .filter((candidate) => candidate.travel_styles.length > 0)
    .map((candidate) => {
      const styleScore = cosineSimilarity(
        myVector,
        toTravelStyleVector(candidate.travel_styles)
      );
      const nationalityBonus =
        currentUser.nationality && candidate.nationality === currentUser.nationality
          ? 0.05
          : 0;

      return {
        ...candidate,
        similarity_score: Math.min(1, styleScore + nationalityBonus),
      };
    })
    .sort((a, b) => b.similarity_score - a.similarity_score)
    .slice(0, topN);
}

function toTravelStyleVector(travelStyles: string[]): number[] {
  return TRAVEL_STYLE_KEYS.map((style) => (travelStyles.includes(style) ? 1 : 0));
}

function cosineSimilarity(a: number[], b: number[]): number {
  const dot = a.reduce((sum, value, index) => sum + value * b[index], 0);
  const normA = Math.sqrt(a.reduce((sum, value) => sum + value * value, 0));
  const normB = Math.sqrt(b.reduce((sum, value) => sum + value * value, 0));

  if (normA === 0 || normB === 0) return 0;

  return dot / (normA * normB);
}
