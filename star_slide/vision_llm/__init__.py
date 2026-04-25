"""Vision LLM 통합 — 슬라이드 PNG → 구조화 JSON.

cliproxy (localhost:8300/v1) 사용. 자세한 사용법은 schema.py / extractor.py.
"""

from star_slide.vision_llm.extractor import VisionExtractor
from star_slide.vision_llm.schema import VisionElement, VisionSlide

__all__ = ["VisionElement", "VisionExtractor", "VisionSlide"]
