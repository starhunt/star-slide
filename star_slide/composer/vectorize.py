"""SAM SHAPE 마스크 → vtracer → custGeom 변환 통합 모듈.

orchestrator에서 호출되는 단일 진입점 `vectorize_shape()`.

흐름:
  1. 원본 슬라이드 PNG에서 SAM 마스크 영역만 isolate (외부 = 흰색).
  2. mask bbox로 크롭 → 임시 PNG.
  3. vtracer BW 모드로 트레이스 → 가장 큰 path 선택.
  4. svg_path_to_custgeom으로 OOXML XML 생성.
  5. mask 영역 dominant color 추출 → fill 색.
  6. ShapePayload 반환.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from star_slide.composer.svg2custgeom import CustGeomResult, svg_path_to_custgeom
from star_slide.composer.vtracer_wrapper import TracedPath, dominant_hex_color, trace_image
from star_slide.schema.layer import ShapePayload
from star_slide.segmentation.iou import Bbox


@dataclass(frozen=True)
class VectorizedShape:
    """vectorize_shape 결과 — orchestrator에서 ShapePayload로 변환됨."""

    payload: ShapePayload
    bbox: Bbox  # 원본 슬라이드 좌표 (vtracer 입력 크롭 위치)
    n_segments: int


def _isolate_mask(
    image: Image.Image,
    mask: NDArray[np.bool_],
    bg_color: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """원본 이미지에서 mask 영역만 남기고 나머지를 bg_color로 채운 이미지 반환.

    BW 모드 vtracer에 입력하면 mask 형태 윤곽이 단일 path로 트레이스됨.
    """
    arr = np.asarray(image.convert("RGB")).copy()
    h_img, w_img = arr.shape[:2]
    if mask.shape != (h_img, w_img):
        # 크기 불일치는 에러 (호출자 책임)
        raise ValueError(f"mask shape {mask.shape} != image {(h_img, w_img)}")
    arr[~mask] = bg_color
    return Image.fromarray(arr, mode="RGB")


def _dominant_color_in_mask(image: Image.Image, mask: NDArray[np.bool_]) -> str:
    """mask 영역 픽셀들의 최빈색을 hex로 반환."""
    arr = np.asarray(image.convert("RGB"))
    h_img, w_img = arr.shape[:2]
    if mask.shape != (h_img, w_img):
        return "#808080"
    pixels = arr[mask]
    if pixels.size == 0:
        return "#808080"
    # 픽셀 분포가 큼 → 16색으로 양자화 후 최빈색
    masked_img = Image.fromarray(pixels.reshape(-1, 1, 3), mode="RGB")
    return dominant_hex_color(masked_img)


def _largest_path(paths: list[TracedPath]) -> TracedPath | None:
    """trace_image 결과 중 bbox 면적 최대 path를 반환."""
    if not paths:
        return None
    return max(paths, key=lambda p: p.bbox[2] * p.bbox[3])


def vectorize_shape(
    slide_image: Image.Image,
    mask: NDArray[np.bool_],
    *,
    crop_padding_px: int = 4,
    target_w: int = 1_000_000,
    target_h: int = 1_000_000,
) -> VectorizedShape | None:
    """SAM 마스크 1개를 vtracer로 트레이스 → custGeom XML 포함 ShapePayload.

    Args:
        slide_image: 원본 슬라이드 PNG (RGB)
        mask: 슬라이드와 같은 (h, w) 크기 bool 마스크
        crop_padding_px: 크롭 시 bbox 외부 여유 (px)
        target_w/h: custGeom path[w, h] 좌표계 해상도

    Returns:
        VectorizedShape 또는 None (트레이스 실패 시)
    """
    h_img, w_img = mask.shape
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x_min = max(0, int(xs.min()) - crop_padding_px)
    y_min = max(0, int(ys.min()) - crop_padding_px)
    x_max = min(w_img, int(xs.max()) + 1 + crop_padding_px)
    y_max = min(h_img, int(ys.max()) + 1 + crop_padding_px)
    if x_max <= x_min or y_max <= y_min:
        return None

    isolated = _isolate_mask(slide_image, mask)
    crop = isolated.crop((x_min, y_min, x_max, y_max))

    fill = _dominant_color_in_mask(slide_image, mask)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        crop.save(tmp_path)
        try:
            paths = trace_image(tmp_path, color_mode="bw")
        except Exception:
            return None
    finally:
        tmp_path.unlink(missing_ok=True)

    chosen = _largest_path(paths)
    if chosen is None:
        return None

    try:
        cust: CustGeomResult = svg_path_to_custgeom(chosen.d, target_w=target_w, target_h=target_h)
    except (ValueError, NotImplementedError):
        return None

    payload = ShapePayload(
        geom_type="custGeom",
        svg_path_d=chosen.d,
        custgeom_xml=cust.xml,
        fill=fill,
        stroke=None,
        stroke_width_pt=0.0,
    )

    bbox: Bbox = (
        float(x_min),
        float(y_min),
        float(x_max - x_min),
        float(y_max - y_min),
    )
    return VectorizedShape(payload=payload, bbox=bbox, n_segments=cust.n_segments)
