from typing import List

from app.core.ai.menu_translator.v1.model import MenuTranslatorModel


class MenuTranslator:
    """메뉴 번역 — 영어 메뉴명을 한국어로 번역합니다."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def load(self) -> None:
        """서버 시작 시 한 번 호출된다."""
        if self._initialized:
            return
        self._model = MenuTranslatorModel()
        self._model.load_weights()
        self._initialized = True

    def invoke(self, english_menus: List[str]) -> List[str]:
        """
        추론 요청의 단일 진입점.

        Args:
            english_menus: 번역할 영어 메뉴명 리스트
                e.g. ["Pork belly", "Cold noodles"]

        Returns:
            한국어 번역 결과 리스트
                e.g. ["삼겹살", "냉면"]
        """
        if not self._initialized:
            raise RuntimeError("모델이 로드되지 않았습니다.")
        return self._model.predict(english_menus)
