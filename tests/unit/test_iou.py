"""IoU 유틸 단위 테스트."""

from __future__ import annotations

import numpy as np

from star_slide.segmentation.iou import (
    bbox_iou,
    best_match_iou,
    mask_iou,
    mask_to_bbox,
)


class TestBboxIou:
    def test_identical(self) -> None:
        assert bbox_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0

    def test_disjoint(self) -> None:
        assert bbox_iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0.0

    def test_half_overlap(self) -> None:
        # 두 정사각형이 절반 겹침 → IoU = inter/union = 50/150 = 1/3
        result = bbox_iou((0, 0, 10, 10), (5, 0, 10, 10))
        assert abs(result - 1 / 3) < 1e-9

    def test_contained(self) -> None:
        # 내부 사각형 (5,5,4,4) area=16, 외부 (0,0,10,10) area=100, 교집합=16
        result = bbox_iou((0, 0, 10, 10), (5, 5, 4, 4))
        assert abs(result - 16 / 100) < 1e-9

    def test_zero_area(self) -> None:
        assert bbox_iou((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0
        assert bbox_iou((0, 0, 10, 10), (5, 5, -1, 4)) == 0.0


class TestMaskIou:
    def test_identical(self) -> None:
        m = np.zeros((10, 10), dtype=bool)
        m[2:7, 2:7] = True
        assert mask_iou(m, m) == 1.0

    def test_disjoint(self) -> None:
        a = np.zeros((10, 10), dtype=bool)
        b = np.zeros((10, 10), dtype=bool)
        a[0:3, 0:3] = True
        b[5:8, 5:8] = True
        assert mask_iou(a, b) == 0.0

    def test_empty(self) -> None:
        a = np.zeros((10, 10), dtype=bool)
        b = np.zeros((10, 10), dtype=bool)
        assert mask_iou(a, b) == 0.0

    def test_shape_mismatch_raises(self) -> None:
        import pytest

        a = np.zeros((10, 10), dtype=bool)
        b = np.zeros((5, 5), dtype=bool)
        with pytest.raises(ValueError, match="shape mismatch"):
            mask_iou(a, b)


class TestMaskToBbox:
    def test_simple(self) -> None:
        m = np.zeros((20, 20), dtype=bool)
        m[5:10, 7:12] = True
        bbox = mask_to_bbox(m)
        assert bbox == (7.0, 5.0, 5.0, 5.0)

    def test_empty(self) -> None:
        m = np.zeros((10, 10), dtype=bool)
        assert mask_to_bbox(m) is None


class TestBestMatch:
    def test_finds_best(self) -> None:
        target = (10.0, 10.0, 5.0, 5.0)
        candidates = [
            (0.0, 0.0, 5.0, 5.0),  # 멀리
            (10.0, 10.0, 5.0, 5.0),  # 정확 일치
            (12.0, 12.0, 5.0, 5.0),  # 부분 겹침
        ]
        idx, iou = best_match_iou(candidates, target)
        assert idx == 1
        assert iou == 1.0

    def test_no_match(self) -> None:
        target = (100.0, 100.0, 5.0, 5.0)
        candidates = [(0.0, 0.0, 5.0, 5.0)]
        idx, iou = best_match_iou(candidates, target)
        assert idx == -1
        assert iou == 0.0

    def test_empty_candidates(self) -> None:
        idx, iou = best_match_iou([], (0.0, 0.0, 5.0, 5.0))
        assert idx == -1
        assert iou == 0.0
