"""텍스트 시각 속성 추출 — 색상 / 폰트 크기.

원본 PowerPoint 슬라이드 품질 보존 위해 OCR 텍스트 콘텐츠뿐 아니라
폰트 색상과 크기도 정밀하게 추정한다.

전략:
  - **색상**: SAM 3 정밀 마스크가 잡은 ink 픽셀의 dark mode (luminance < 100)
    주된 색을 mode로 추출. 안티앨리어싱 평균이 아닌 mode → 더 정확한 hex.
  - **폰트 크기 (pt)**: 마스크 height x cap-height-to-emsize 비율 x 72/96 dpi.
    한글은 글자 높이가 거의 em-size이므로 비율 ~0.85 가정. 96 dpi 슬라이드 렌더 기준.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image

# 슬라이드 렌더 기본 dpi (PowerPoint 표준 96 dpi)
SLIDE_DPI = 96.0
PT_PER_INCH = 72.0
# 한글 글자 높이가 em-size에 차지하는 비율 (mask height 기준)
HANGUL_HEIGHT_TO_EMSIZE = 0.85
# 영문은 cap-height ≈ 0.7 x em
LATIN_HEIGHT_TO_EMSIZE = 0.7


def estimate_font_color(
    image: Image.Image,
    mask: NDArray[np.bool_],
    luminance_threshold: int = 130,
) -> str | None:
    """SAM 3 마스크의 ink 픽셀 → mode 색상 hex.

    Args:
        image: 슬라이드 PNG (RGB)
        mask: 글자 영역 bool 마스크
        luminance_threshold: 이 값 미만 luminance 픽셀만 ink로 간주 (dark text)

    Returns:
        '#RRGGBB' 또는 None (마스크 비었거나 ink 픽셀 없음)
    """
    arr = np.asarray(image.convert("RGB"))
    h, w = arr.shape[:2]
    if mask.shape != (h, w) or not mask.any():
        return None

    pixels = arr[mask]  # (N, 3)
    if pixels.size == 0:
        return None

    # luminance 0.299R + 0.587G + 0.114B
    lum = (
        0.299 * pixels[:, 0].astype(np.float32)
        + 0.587 * pixels[:, 1].astype(np.float32)
        + 0.114 * pixels[:, 2].astype(np.float32)
    )
    ink = pixels[lum < luminance_threshold]
    if len(ink) == 0:
        # dark text 가정 실패 — 대비가 낮거나 흰 글자. mask 전체 평균으로 fallback.
        ink = pixels

    # mode: 8단계로 양자화 후 빈도 최대 색상
    quant = (ink // 32) * 32 + 16
    # 행 단위 unique
    view = np.ascontiguousarray(quant).view([("", quant.dtype)] * 3)
    _, idx, counts = np.unique(view, return_index=True, return_counts=True)
    if len(counts) == 0:
        return None
    mode_idx = int(idx[counts.argmax()])
    r, g, b = (int(c) for c in quant[mode_idx])
    return f"#{r:02X}{g:02X}{b:02X}"


def estimate_font_size_pt(
    mask_height_px: float,
    *,
    is_korean: bool = True,
    dpi: float = SLIDE_DPI,
) -> float:
    """마스크 height(px) → 폰트 크기(pt).

    em-size = mask_height / height_to_em_ratio
    pt = em-size x 72 / dpi
    """
    if mask_height_px <= 0:
        return 0.0
    ratio = HANGUL_HEIGHT_TO_EMSIZE if is_korean else LATIN_HEIGHT_TO_EMSIZE
    em_px = mask_height_px / ratio
    return float(em_px * PT_PER_INCH / dpi)


def detect_korean(text: str) -> bool:
    """텍스트에 한글이 포함됐는가 (폰트 크기 비율 결정용)."""
    for ch in text:
        if "가" <= ch <= "힣":  # 한글 음절
            return True
        if "ᄀ" <= ch <= "ᇿ":  # 한글 자모
            return True
    return False
