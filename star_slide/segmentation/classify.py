"""SAM 마스크를 OCR 결과와 매칭해 TEXT/SHAPE/BACKGROUND/NOISE로 분류.

핵심 휴리스틱 (PRD §10.1, FR-023):
  - SAM 마스크 bbox가 OCR bbox 안에 70% 이상 들어가면 → TEXT (글자 모양 마스크)
  - 면적 > 80% slide → BACKGROUND
  - 면적 < 0.05% slide → NOISE
  - 그 외 → SHAPE (P1-T08 vtracer 입력)

OCR이 검출했지만 어떤 SAM TEXT 마스크와도 매칭되지 않은 라인은
인페인팅 fallback (사각 bbox + padding)으로 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from star_slide.ocr.paddleocr_worker import OcrLine
from star_slide.segmentation.iou import Bbox, bbox_iou
from star_slide.segmentation.sam2_auto import Sam2Mask


class MaskClass(StrEnum):
    """SAM 마스크 분류."""

    TEXT = "text"
    SHAPE = "shape"
    BACKGROUND = "background"
    NOISE = "noise"


@dataclass(frozen=True)
class ClassifiedMask:
    """분류된 SAM 마스크."""

    mask: Sam2Mask
    cls: MaskClass
    matched_ocr_indices: tuple[int, ...] = ()


@dataclass
class ClassificationResult:
    """슬라이드 단위 분류 결과."""

    classified: list[ClassifiedMask] = field(default_factory=list)
    unmatched_ocr_indices: list[int] = field(default_factory=list)

    @property
    def text_masks(self) -> list[Sam2Mask]:
        return [c.mask for c in self.classified if c.cls == MaskClass.TEXT]

    @property
    def shape_masks(self) -> list[Sam2Mask]:
        return [c.mask for c in self.classified if c.cls == MaskClass.SHAPE]


def _bbox_inside_ratio(inner: Bbox, outer: Bbox) -> float:
    """inner bbox 면적 중 outer bbox와 겹치는 부분의 비율 (0~1).

    inner ⊂ outer 정도를 측정. inner.area = 0이면 0.
    """
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    if iw <= 0 or ih <= 0:
        return 0.0
    x1 = max(ix, ox)
    y1 = max(iy, oy)
    x2 = min(ix + iw, ox + ow)
    y2 = min(iy + ih, oy + oh)
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter = inter_w * inter_h
    inner_area = iw * ih
    if inner_area <= 0:
        return 0.0
    return float(inter / inner_area)


def classify_masks(
    masks: list[Sam2Mask],
    ocr_lines: list[OcrLine],
    image_size: tuple[int, int],
    *,
    text_containment_threshold: float = 0.7,
    background_area_ratio: float = 0.8,
    noise_area_ratio: float = 0.00005,
    fallback_match_iou: float = 0.1,
) -> ClassificationResult:
    """SAM 마스크들을 OCR과 매칭해 분류.

    Args:
        masks: SAM 자동 마스크 리스트
        ocr_lines: OCR 결과 (PaddleOCR)
        image_size: (width, height) 픽셀
        text_containment_threshold: SAM bbox가 OCR bbox 안에 들어가는 비율 임계
        background_area_ratio: 슬라이드 면적 대비 BACKGROUND 임계
        noise_area_ratio: 슬라이드 면적 대비 NOISE 임계
        fallback_match_iou: OCR이 SAM TEXT와 "매칭됐다"고 보는 최소 bbox-IoU
            (이 값을 못 넘는 OCR 라인은 인페인팅 fallback으로 처리)
    """
    w, h = image_size
    slide_area = float(w * h) if w > 0 and h > 0 else 1.0

    classified: list[ClassifiedMask] = []
    matched_ocr_indices_set: set[int] = set()

    for m in masks:
        area_ratio = m.area / slide_area
        if area_ratio > background_area_ratio:
            classified.append(ClassifiedMask(mask=m, cls=MaskClass.BACKGROUND))
            continue
        if area_ratio < noise_area_ratio:
            classified.append(ClassifiedMask(mask=m, cls=MaskClass.NOISE))
            continue

        # OCR과의 매칭: SAM mask bbox가 어떤 OCR bbox 안에 들어가는가?
        best_inside = 0.0
        best_ocr_indices: list[int] = []
        for i, line in enumerate(ocr_lines):
            inside = _bbox_inside_ratio(m.bbox, line.bbox)
            if inside > best_inside:
                best_inside = inside
                best_ocr_indices = [i]
            elif inside >= text_containment_threshold and inside == best_inside:
                best_ocr_indices.append(i)

        if best_inside >= text_containment_threshold:
            classified.append(
                ClassifiedMask(
                    mask=m,
                    cls=MaskClass.TEXT,
                    matched_ocr_indices=tuple(best_ocr_indices),
                )
            )
            for idx in best_ocr_indices:
                matched_ocr_indices_set.add(idx)
        else:
            classified.append(ClassifiedMask(mask=m, cls=MaskClass.SHAPE))

    # OCR fallback 판정: 어떤 TEXT SAM 마스크와도 IoU가 임계 이상이면 매칭됐다고 봄
    text_masks = [c.mask for c in classified if c.cls == MaskClass.TEXT]
    unmatched: list[int] = []
    for i, line in enumerate(ocr_lines):
        if i in matched_ocr_indices_set:
            continue
        # 이미 set에 들어있지 않더라도, IoU가 충분히 높은 TEXT 마스크가 있으면 OK
        covered = False
        for tm in text_masks:
            if bbox_iou(tm.bbox, line.bbox) >= fallback_match_iou:
                covered = True
                break
        if not covered:
            unmatched.append(i)

    return ClassificationResult(classified=classified, unmatched_ocr_indices=unmatched)
