from typing import List

import torch
from transformers import NllbTokenizerFast, AutoModelForSeq2SeqLM

from app.core.logger import get_logger


logger = get_logger("menu_translator")

HF_REPO_ID = "kyr778/krip-menu-translator-v3"


class MenuTranslatorModel:
    """NLLB 기반 메뉴 번역 모델 — 영어 메뉴명을 한국어로 번역합니다."""

    def __init__(self, repo_id: str = HF_REPO_ID):
        self._repo_id = repo_id
        self._device: torch.device | None = None
        self._tokenizer: NllbTokenizerFast | None = None
        self._model: AutoModelForSeq2SeqLM | None = None


    def _resolve_device(self) -> torch.device:
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")


    def load_weights(self) -> None:
        """모델과 토크나이저를 메모리에 로드합니다."""
        self._device = self._resolve_device()
        logger.info(
            "모델 로드 시작: repo={}, device={}",
            self._repo_id, self._device,
        )

        self._tokenizer = NllbTokenizerFast.from_pretrained(self._repo_id)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self._repo_id)
        self._model.to(self._device)
        self._model.eval()

        logger.info("모델 로드 완료: {}", self._repo_id)


    def predict(self, english_menus: List[str]) -> List[str]:
        """
        영어 메뉴명 리스트를 한국어로 번역합니다.

        Args:
            english_menus: 번역할 영어 메뉴명 리스트
                e.g. ["Pork belly", "Cold noodles"]

        Returns:
            한국어 번역 결과 리스트
                e.g. ["삼겹살", "냉면"]
        """
        if not english_menus:
            return []

        self._tokenizer.src_lang = "eng_Latn"
        inputs = self._tokenizer(
            english_menus, return_tensors="pt", padding=True,
        ).to(self._device)

        kor_token_id = self._tokenizer.convert_tokens_to_ids("kor_Hang")

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                forced_bos_token_id=kor_token_id,
                max_length=128,
                num_beams=5,
            )

        return [
            self._tokenizer.decode(seq, skip_special_tokens=True)
            for seq in outputs
        ]
