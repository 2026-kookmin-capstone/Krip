from typing import List
from dataclasses import dataclass


@dataclass
class MenuData:
    """메뉴 항목 DTO"""
    original_name: str
    english_name: str
    description: str
    price: int


@dataclass
class MenuOcrData:
    """메뉴 OCR 결과 DTO"""
    menus: List[MenuData]


@dataclass
class MenuOcrBatchData:
    """메뉴 OCR 배치 결과 DTO"""
    results: List[MenuOcrData]
