"""IoU(Intersection over Union) 계산 유틸.

H1 검증(SAM 3.1 마스크 vs ground truth bbox), 그리고 P1 객체 매칭에 공용으로 사용.
"""

from __future__ import annotations

from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray

# (x, y, w, h) 픽셀 단위 bbox
Bbox: TypeAlias = tuple[float, float, float, float]
BoolMask: TypeAlias = NDArray[np.bool_]


def bbox_iou(a: Bbox, b: Bbox) -> float:
    """두 bbox의 IoU (axis-aligned).

    bbox 형식: (x, y, w, h). w/h ≤ 0이면 0 반환.
    """
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return float(inter / union)


def mask_iou(a: BoolMask, b: BoolMask) -> float:
    """두 bool 마스크의 픽셀 단위 IoU."""
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 0.0
    return float(inter / union)


def mask_to_bbox(mask: BoolMask) -> Bbox | None:
    """bool 마스크 → (x, y, w, h) bbox. 빈 마스크면 None."""
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x_min = float(xs.min())
    y_min = float(ys.min())
    x_max = float(xs.max())
    y_max = float(ys.max())
    return (x_min, y_min, x_max - x_min + 1, y_max - y_min + 1)


def best_match_iou(candidates: list[Bbox], target: Bbox) -> tuple[int, float]:
    """target에 대해 candidates 중 IoU가 가장 큰 인덱스와 그 IoU를 반환.

    매칭이 없으면 (-1, 0.0) 반환.
    """
    best_idx = -1
    best_iou = 0.0
    for i, c in enumerate(candidates):
        score = bbox_iou(c, target)
        if score > best_iou:
            best_iou = score
            best_idx = i
    return best_idx, best_iou
