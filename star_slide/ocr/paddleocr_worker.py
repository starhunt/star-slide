"""PaddleOCR PP-OCRv5 한국어 모델 래퍼.

PaddleOCR 3.x API는 2.x와 다름:
  ocr = PaddleOCR(lang='korean')
  result = ocr.predict(img)  # 또는 ocr.ocr(img)

ADR-002 채택. 1차 PaddleOCR + 2차 Surya 앙상블 (Surya는 P0-T05 후속).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image


@dataclass(frozen=True)
class OcrLine:
    """한 줄 OCR 결과.

    bbox_quad: 4점 다각형 [(x1,y1),(x2,y2),(x3,y3),(x4,y4)] — 회전 텍스트 표현 가능
    bbox: axis-aligned (x, y, w, h) — quad의 외접 사각형
    """

    text: str
    confidence: float
    bbox_quad: list[tuple[float, float]]
    bbox: tuple[float, float, float, float]


@lru_cache(maxsize=1)
def _get_ocr(lang: str = "korean") -> Any:
    """PaddleOCR 인스턴스 캐싱 (모델 로드 비용 감소).

    Args:
        lang: 'korean' | 'en' | 'ch' | 'japan' 등 (PaddleOCR 3.x 언어 코드)
    """
    from paddleocr import PaddleOCR

    return PaddleOCR(lang=lang, use_textline_orientation=True)


def _quad_to_bbox(
    quad: list[list[float]] | NDArray[Any],
) -> tuple[float, float, float, float]:
    arr = np.asarray(quad, dtype=float)
    x_min, y_min = arr[:, 0].min(), arr[:, 1].min()
    x_max, y_max = arr[:, 0].max(), arr[:, 1].max()
    return (float(x_min), float(y_min), float(x_max - x_min), float(y_max - y_min))


def run_ocr(
    image: Path | NDArray[np.uint8] | Image.Image,
    lang: str = "korean",
) -> list[OcrLine]:
    """이미지에 OCR 실행 → OcrLine 리스트.

    Args:
        image: 파일 경로 또는 numpy 배열 또는 PIL Image
        lang: PaddleOCR 언어 코드

    Returns:
        라인 단위 OCR 결과 (좌→우, 위→아래 정렬은 PaddleOCR 출력 순서 그대로)
    """
    ocr = _get_ocr(lang=lang)

    if isinstance(image, Path):
        arr = np.array(Image.open(image).convert("RGB"))
    elif isinstance(image, Image.Image):
        arr = np.array(image.convert("RGB"))
    else:
        arr = image

    result = ocr.predict(arr)
    if not result:
        return []

    # PaddleOCR 3.x predict() 반환: list[OCRResult] (배치 입력 대응).
    # 단일 이미지면 첫 결과만 사용.
    page = result[0]

    # OCRResult dict-like: rec_texts, rec_scores, rec_polys (또는 dt_polys)
    texts: list[str] = page.get("rec_texts") or []
    scores: list[float] = page.get("rec_scores") or []
    polys = page.get("rec_polys") or page.get("dt_polys") or []

    lines: list[OcrLine] = []
    for text, score, poly in zip(texts, scores, polys, strict=False):
        if not text:
            continue
        quad = [(float(p[0]), float(p[1])) for p in poly]
        lines.append(
            OcrLine(
                text=text,
                confidence=float(score),
                bbox_quad=quad,
                bbox=_quad_to_bbox(poly),
            )
        )
    return lines


def lines_to_text(lines: list[OcrLine]) -> str:
    """OcrLine 리스트 → 줄바꿈으로 합친 단일 텍스트.

    PaddleOCR 출력 순서 유지 (위→아래, 좌→우 근사).
    """
    return "\n".join(line.text for line in lines)
