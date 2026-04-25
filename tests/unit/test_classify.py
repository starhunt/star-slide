"""SAM 마스크 분류 로직 단위 테스트."""

from __future__ import annotations

import numpy as np

from star_slide.ocr.paddleocr_worker import OcrLine
from star_slide.segmentation.classify import MaskClass, classify_masks
from star_slide.segmentation.sam2_auto import Sam2Mask


def _make_mask(bbox: tuple[float, float, float, float], area: int | None = None) -> Sam2Mask:
    """테스트용 더미 SAM 마스크 (segmentation은 zero array)."""
    seg = np.zeros((100, 100), dtype=bool)
    return Sam2Mask(
        bbox=bbox,
        segmentation=seg,
        score=0.95,
        area=area if area is not None else int(bbox[2] * bbox[3]),
    )


def _make_ocr(bbox: tuple[float, float, float, float], text: str = "X") -> OcrLine:
    return OcrLine(
        text=text,
        confidence=0.9,
        bbox_quad=[],
        bbox=bbox,
    )


class TestClassifyMasks:
    def test_text_mask_inside_ocr_bbox(self) -> None:
        """SAM 마스크 bbox가 OCR bbox 안에 있으면 TEXT.

        realistic 1920x1080 slide. OCR text line ≈ 100x30px, char mask ≈ 30x30px.
        """
        ocr = [_make_ocr((100, 100, 300, 60))]
        masks = [_make_mask((150, 110, 30, 40))]  # 글자 한 칸 크기, OCR 안에
        result = classify_masks(masks, ocr, image_size=(1920, 1080))
        assert result.classified[0].cls == MaskClass.TEXT
        assert 0 in result.classified[0].matched_ocr_indices

    def test_shape_mask_outside_ocr(self) -> None:
        """OCR과 겹치지 않는 중간 크기 마스크는 SHAPE."""
        ocr = [_make_ocr((100, 100, 200, 60))]
        masks = [_make_mask((1000, 500, 200, 200))]  # 멀리 떨어진 도형
        result = classify_masks(masks, ocr, image_size=(1920, 1080))
        assert result.classified[0].cls == MaskClass.SHAPE

    def test_background_mask(self) -> None:
        """면적 80%+ 마스크는 BACKGROUND."""
        masks = [_make_mask((0, 0, 1900, 1000), area=1_900_000)]  # ~91% of 1920x1080
        result = classify_masks(masks, [], image_size=(1920, 1080))
        assert result.classified[0].cls == MaskClass.BACKGROUND

    def test_noise_mask_too_small(self) -> None:
        """면적 < 0.005% 슬라이드는 NOISE.

        1920*1080 ≈ 2.07M. 0.005% ≈ 100px. area=25 (5x5)이면 NOISE.
        """
        masks = [_make_mask((10, 10, 5, 5), area=25)]
        result = classify_masks(masks, [], image_size=(1920, 1080))
        assert result.classified[0].cls == MaskClass.NOISE

    def test_unmatched_ocr_returned(self) -> None:
        """SAM이 못 잡은 OCR 라인은 unmatched로 반환."""
        ocr = [
            _make_ocr((100, 100, 300, 60), "matched"),  # SAM 마스크에 들어감
            _make_ocr((1000, 800, 300, 60), "unmatched"),  # SAM 마스크 없음
        ]
        masks = [_make_mask((150, 110, 30, 40))]  # 첫 OCR 안에 있음
        result = classify_masks(masks, ocr, image_size=(1920, 1080))
        assert result.unmatched_ocr_indices == [1]

    def test_large_card_mask_not_text(self) -> None:
        """카드 배경처럼 OCR보다 훨씬 큰 마스크는 TEXT가 아니라 SHAPE."""
        ocr = [_make_ocr((100, 100, 80, 40))]  # 작은 텍스트
        # 마스크 bbox는 OCR보다 훨씬 큼 → 마스크가 OCR에 "들어가는" 비율 낮음
        masks = [_make_mask((50, 50, 600, 600))]
        result = classify_masks(masks, ocr, image_size=(1920, 1080))
        assert result.classified[0].cls == MaskClass.SHAPE

    def test_text_masks_property(self) -> None:
        """ClassificationResult.text_masks 헬퍼."""
        ocr = [_make_ocr((100, 100, 300, 60))]
        masks = [
            _make_mask((150, 110, 30, 40)),  # TEXT
            _make_mask((1000, 500, 200, 200)),  # SHAPE
        ]
        result = classify_masks(masks, ocr, image_size=(1920, 1080))
        assert len(result.text_masks) == 1
        assert len(result.shape_masks) == 1
