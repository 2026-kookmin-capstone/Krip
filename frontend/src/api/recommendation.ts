import client from "./client";
import type { RecommendationCandidate } from "../utils/mateRecommendation";

interface RecommendationCandidatesResponse {
  items?: RecommendationCandidate[];
  candidates?: RecommendationCandidate[];
}

export async function getRecommendationCandidates(): Promise<RecommendationCandidate[]> {
  const { data } = await client.get<RecommendationCandidatesResponse | RecommendationCandidate[]>(
    "/api/friend/recommendations"
  );

  if (Array.isArray(data)) return data;
  return data.items ?? data.candidates ?? [];
}
