from fastapi import APIRouter, Depends, HTTPException
from dependency_injector.wiring import Provide, inject

from app.container import Container
from app.core.logger import get_logger
from app.domain.tour.schema.recommend import (
    TourRecommendRequest,
    TourRecommendResponse,
)
from app.domain.tour.service.recommend import RecommendService


router = APIRouter(prefix="/recommend", tags=["여행 추천"])
logger = get_logger("tour.recommend")


@router.post("", status_code=200)
@inject
async def recommend_tour(
    body: TourRecommendRequest,
    recommend_service: RecommendService = Depends(Provide[Container.recommend_service]),
) -> TourRecommendResponse:
    """사용자 맞춤 서울 여행 코스 추천 (v2)

    - 일자별 출발/도착 권역, 추가 장소(최대 1개, 강제 포함), 시간/예산/스타일을 받아 시간 기반 코스 생성
    - 음식 옵션(halal/vegetarian)은 식당 선정 시 강제 적용
    """
    try:
        return await recommend_service.recommend(body)
    except ValueError as e:
        # 추가 장소 미존재 등 입력 검증 실패
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("여행 추천 실패: {}", e)
        raise HTTPException(status_code=500, detail="Failed to generate tour recommendation.")
