"""SAM 3.1 모델 로더 스텁.

Phase 0 H1 검증용. 실제 SAM 3.1 패키지 출시 후 정확한 import 경로 확정 필요.
지금은 인터페이스만 정의하고 raise NotImplementedError로 표시 — 모델 다운로드 작업과 분리.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class SamMask:
    """SAM 출력 마스크 한 개.

    bbox: (x, y, w, h) 픽셀 단위
    segmentation: bool 마스크 (H, W)
    """

    bbox: tuple[float, float, float, float]
    segmentation: NDArray[np.bool_]
    predicted_iou: float
    stability_score: float
    area: int


class SamGenerator(Protocol):
    """SAM AutomaticMaskGenerator 프로토콜.

    실 구현체(sam3.1, sam2 fallback)는 이 프로토콜을 따른다.
    """

    def generate(self, image: NDArray[np.uint8]) -> list[SamMask]:  # pragma: no cover
        ...


def load_sam(
    model_name: str = "sam3.1",
    weights_path: Path | None = None,
    device: str = "cpu",
    points_per_side: int = 32,
    pred_iou_thresh: float = 0.86,
    stability_score_thresh: float = 0.92,
    min_mask_region_area: int = 100,
    **kwargs: Any,
) -> SamGenerator:
    """SAM 모델을 로드해 SamGenerator를 반환.

    Phase 0에서는 sam3.1 / sam2 두 분기 지원 예정. 현재는 placeholder.

    Args:
        model_name: "sam3.1" | "sam2" (fallback)
        weights_path: 모델 가중치 파일. None이면 환경변수/기본 경로 시도.
        device: "cuda" | "mps" | "cpu"
        points_per_side: 자동 마스크 그리드 포인트 수
        pred_iou_thresh: SAM 자체 신뢰도 임계
        stability_score_thresh: 마스크 안정성 임계
        min_mask_region_area: 노이즈 제거 최소 픽셀

    Raises:
        NotImplementedError: SAM 3.1 출시 후 실제 구현 채움.
    """
    raise NotImplementedError(
        f"SAM model loader not yet implemented (model={model_name}). "
        "P0-T03에서 sam3.1 또는 segment-anything 패키지 출시 확정 후 구현. "
        "참조: docs/Star-Slide_TechDecisions.md ADR-001"
    )
