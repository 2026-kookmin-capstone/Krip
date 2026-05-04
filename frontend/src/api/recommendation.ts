import client from "./client";
import type { RecommendationCandidate } from "../utils/mateRecommendation";

export interface RecommendationCandidatesResponse {
  items: RecommendationCandidate[];
}

export async function getRecommendationCandidates(): Promise<RecommendationCandidatesResponse> {
  const { data } = await client.get<
    | RecommendationCandidate[]
    | RecommendationCandidatesResponse
    | { users?: RecommendationCandidate[]; profiles?: RecommendationCandidate[] }
  >("/api/auth/profile/all");

  if (Array.isArray(data)) {
    return { items: normalizeRecommendationCandidates(data) };
  }

  return {
    items: normalizeRecommendationCandidates(
      data.items ?? data.users ?? data.profiles ?? []
    ),
  };
}

function normalizeRecommendationCandidates(
  candidates: RecommendationCandidate[]
): RecommendationCandidate[] {
  return candidates
    .filter((candidate) => candidate.user_id && candidate.user_name)
    .map((candidate) => ({
      ...candidate,
      user_id: candidate.user_id,
      user_name: candidate.user_name,
      profile_image_url: candidate.profile_image_url ?? null,
      travel_styles: Array.isArray(candidate.travel_styles)
        ? candidate.travel_styles
        : [],
      nationality: candidate.nationality ?? "",
    }));
}
