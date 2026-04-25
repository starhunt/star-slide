"""SAM 2.1 자동 마스크 생성 wrapper (transformers pipeline 'mask-generation').

SAM 3는 facebook/sam3가 gated repo (HuggingFace access request 필요).
Phase 0 PoC는 SAM 2.1 hiera-large로 fallback — PRD §10.1 'everything mode' 가정과 일치.

Phase 1 이후 SAM 3 access 확보되면 sam3.py로 교체. ADR-001의 SAM 2 fallback 경로.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from PIL import Image

from star_slide.segmentation.iou import Bbox, mask_to_bbox

DEFAULT_SAM2_MODEL = "facebook/sam2.1-hiera-large"


@dataclass(frozen=True)
class Sam2Mask:
    """SAM 2 자동 마스크."""

    bbox: Bbox  # (x, y, w, h) 픽셀
    segmentation: NDArray[np.bool_]
    score: float
    area: int


@dataclass
class Sam2Result:
    image_size: tuple[int, int]
    masks: list[Sam2Mask] = field(default_factory=list)
    elapsed_sec: float = 0.0
    device: str = "cpu"


def _select_device(prefer: str = "auto") -> str:
    if prefer == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    return prefer


_LOADED_PIPELINE: dict[tuple[str, str], Any] = {}


def _get_pipeline(model_id: str, device: str) -> Any:
    key = (model_id, device)
    if key in _LOADED_PIPELINE:
        return _LOADED_PIPELINE[key]

    from transformers import pipeline

    # transformers pipeline은 device 인자에 'mps'/'cuda'/'cpu' 또는 정수 GPU 인덱스 받음
    pipe = pipeline(
        "mask-generation",
        model=model_id,
        device=device,
    )
    _LOADED_PIPELINE[key] = pipe
    return pipe


def _to_pil(image: Path | NDArray[np.uint8] | Image.Image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, Path):
        return Image.open(image).convert("RGB")
    return Image.fromarray(image).convert("RGB")


def run_sam2_auto(
    image: Path | NDArray[np.uint8] | Image.Image,
    *,
    model_id: str = DEFAULT_SAM2_MODEL,
    device: str = "auto",
    points_per_batch: int = 64,
    points_per_side: int = 32,
    pred_iou_thresh: float = 0.86,
    stability_score_thresh: float = 0.92,
    max_masks: int = 200,
) -> Sam2Result:
    """SAM 2.1 자동 마스크 생성.

    Args:
        image: 입력 이미지
        model_id: HF 모델 ID (기본 facebook/sam2.1-hiera-large)
        device: 'auto' | 'cuda' | 'mps' | 'cpu'
        points_per_batch: 배치당 grid point 수 (메모리/속도 trade-off)
        points_per_side: grid 한 변의 point 수 (총 = side²)
        pred_iou_thresh: SAM 신뢰도 임계
        stability_score_thresh: 마스크 안정성 임계
        max_masks: 결과 마스크 최대 수 (메모리 보호)
    """
    import time

    pil = _to_pil(image)
    w, h = pil.size

    dev = _select_device(device)
    pipe = _get_pipeline(model_id=model_id, device=dev)

    t0 = time.perf_counter()
    output = pipe(
        pil,
        points_per_batch=points_per_batch,
        points_per_side=points_per_side,
        pred_iou_thresh=pred_iou_thresh,
        stability_score_thresh=stability_score_thresh,
    )
    elapsed = time.perf_counter() - t0

    masks_list = output.get("masks", [])
    scores_list = output.get("scores", [])

    result = Sam2Result(image_size=(w, h), elapsed_sec=elapsed, device=dev)

    n_keep = min(len(masks_list), max_masks)
    for i in range(n_keep):
        m_raw = masks_list[i]
        m = m_raw.detach().cpu().numpy() if isinstance(m_raw, torch.Tensor) else np.asarray(m_raw)
        if m.dtype != bool:
            m = m.astype(bool)
        if m.ndim == 3:
            m = m.squeeze(0)

        bbox = mask_to_bbox(m)
        if bbox is None:
            continue

        score = float(scores_list[i]) if i < len(scores_list) else 0.0
        area = int(m.sum())

        result.masks.append(Sam2Mask(bbox=bbox, segmentation=m, score=score, area=area))

    return result
