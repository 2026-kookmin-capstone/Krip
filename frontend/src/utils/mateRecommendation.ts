export interface RecommendationProfile {
  user_id?: string | null;
  user_name?: string | null;
  nationality?: string | null;
  travel_styles?: string[] | null;
  preferred_gender?: string | null;
  preferred_age_min?: number | null;
  preferred_age_max?: number | null;
}

export interface RecommendationCandidate extends RecommendationProfile {
  profile_image_url?: string | null;
  age?: number | null;
  gender?: string | null;
  status_message?: string | null;
  friendship_status?: string | null;
}

export interface RecommendedTraveler extends RecommendationCandidate {
  user_id: string;
  user_name: string;
  similarity_score: number;
}

export function recommendTravelers(
  profile: RecommendationProfile,
  candidates: RecommendationCandidate[],
  limit = 10
): RecommendedTraveler[] {
  const myId = profile.user_id ?? "";

  return candidates
    .filter((candidate): candidate is RecommendationCandidate & { user_id: string } =>
      Boolean(candidate.user_id && candidate.user_id !== myId)
    )
    .map((candidate) => ({
      ...candidate,
      user_name: candidate.user_name || "Unknown",
      similarity_score: scoreCandidate(profile, candidate),
    }))
    .sort((left, right) => right.similarity_score - left.similarity_score)
    .slice(0, limit);
}

function scoreCandidate(
  profile: RecommendationProfile,
  candidate: RecommendationCandidate
): number {
  let score = 0;
  let weight = 0;

  const styleScore = overlapScore(profile.travel_styles, candidate.travel_styles);
  score += styleScore * 0.6;
  weight += 0.6;

  if (profile.nationality && candidate.nationality) {
    score += (profile.nationality === candidate.nationality ? 1 : 0.35) * 0.2;
    weight += 0.2;
  }

  if (
    typeof candidate.age === "number" &&
    typeof profile.preferred_age_min === "number" &&
    typeof profile.preferred_age_max === "number"
  ) {
    const inRange =
      candidate.age >= profile.preferred_age_min && candidate.age <= profile.preferred_age_max;
    score += (inRange ? 1 : 0.45) * 0.2;
    weight += 0.2;
  }

  if (weight <= 0) return 0;
  return Math.max(0, Math.min(1, score / weight));
}

function overlapScore(left?: string[] | null, right?: string[] | null): number {
  if (!left?.length || !right?.length) return 0;

  const leftSet = new Set(left.map((item) => item.toLowerCase()));
  const rightSet = new Set(right.map((item) => item.toLowerCase()));
  const intersection = [...leftSet].filter((item) => rightSet.has(item)).length;
  const union = new Set([...leftSet, ...rightSet]).size;

  return union > 0 ? intersection / union : 0;
}
