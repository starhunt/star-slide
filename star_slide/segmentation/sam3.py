"""SAM 3 (Promptable Concept Segmentation) wrapper.

SAM 3 패러다임 차이:
- SAM 1/2: 점/박스 prompt 또는 everything mode (자동 모든 객체)
- SAM 3: 텍스트/이미지 개념(concept) prompt → 매칭되는 모든 인스턴스 분리

슬라이드 도메인에서는 ['text', 'icon', 'logo', 'shape', 'chart', 'diagram',
'arrow', 'box', 'photo'] 같은 다중 클래스 prompt를 순차 실행해 의미론적 분류 +
분리를 동시에 얻는 전략 (FR-024 객체 분류와 정확히 일치).

ADR-001 채택. transformers `Sam3Model` 사용.
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

DEFAULT_MODEL_ID = "facebook/sam3"

# 슬라이드 도메인 기본 prompt 풀 (PRD §10.1 Segmentation 클래스에 부합)
DEFAULT_SLIDE_PROMPTS: tuple[str, ...] = (
    "text",
    "icon",
    "logo",
    "shape",
    "chart",
    "diagram",
    "arrow",
    "photo",
    "table",
)


@dataclass(frozen=True)
class Sam3Mask:
    """SAM 3 출력 마스크 한 개."""

    bbox: Bbox  # (x, y, w, h) 픽셀 단위
    segmentation: NDArray[np.bool_]  # (H, W) bool
    score: float
    concept: str  # 어떤 prompt에서 검출됐는지


@dataclass
class Sam3Result:
    """한 이미지에 대한 SAM 3 다중 prompt 추론 결과."""

    image_size: tuple[int, int]  # (W, H)
    masks: list[Sam3Mask] = field(default_factory=list)
    elapsed_per_prompt: dict[str, float] = field(default_factory=dict)
    device: str = "cpu"

    def by_concept(self, concept: str) -> list[Sam3Mask]:
        return [m for m in self.masks if m.concept == concept]


def _select_device(prefer: str = "auto") -> str:
    """auto | cuda | mps | cpu."""
    if prefer == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    return prefer


_LOADED_SAM3: dict[tuple[str, str], tuple[Any, Any]] = {}


def _load_sam3(model_id: str = DEFAULT_MODEL_ID, device: str = "cpu") -> tuple[Any, Any]:
    """SAM 3 모델 + processor 로드 (메모리 캐시)."""
    key = (model_id, device)
    if key in _LOADED_SAM3:
        return _LOADED_SAM3[key]

    from transformers import Sam3Model, Sam3Processor

    model = Sam3Model.from_pretrained(model_id).to(device)  # type: ignore[arg-type]
    model.eval()
    processor = Sam3Processor.from_pretrained(model_id)
    _LOADED_SAM3[key] = (model, processor)
    return model, processor


def _to_pil(image: Path | NDArray[np.uint8] | Image.Image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, Path):
        return Image.open(image).convert("RGB")
    return Image.fromarray(image).convert("RGB")


def run_sam3(
    image: Path | NDArray[np.uint8] | Image.Image,
    prompts: tuple[str, ...] | list[str] = DEFAULT_SLIDE_PROMPTS,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    device: str = "auto",
    threshold: float = 0.5,
    mask_threshold: float = 0.5,
    max_masks_per_concept: int = 50,
) -> Sam3Result:
    """이미지에 다중 텍스트 prompt를 순차 실행 → 마스크 합집합.

    Args:
        image: 입력 이미지
        prompts: 슬라이드 객체 클래스 prompt 목록
        model_id: HuggingFace 모델 ID
        device: 'auto' | 'cuda' | 'mps' | 'cpu'
        threshold: instance 점수 임계
        mask_threshold: 마스크 픽셀 임계 (logits → bool)
        max_masks_per_concept: prompt당 최대 마스크 수 (메모리 보호)
    """
    import time

    pil = _to_pil(image)
    w, h = pil.size

    dev = _select_device(device)
    model, processor = _load_sam3(model_id=model_id, device=dev)

    result = Sam3Result(image_size=(w, h), device=dev)

    for prompt in prompts:
        t0 = time.perf_counter()
        try:
            inputs = processor(images=pil, text=prompt, return_tensors="pt").to(dev)
            with torch.no_grad():
                outputs = model(**inputs)
            target_sizes_t = inputs.get("original_sizes")
            target_sizes = target_sizes_t.tolist() if target_sizes_t is not None else [[h, w]]

            post = processor.post_process_instance_segmentation(
                outputs,
                threshold=threshold,
                mask_threshold=mask_threshold,
                target_sizes=target_sizes,
            )[0]
        except Exception as exc:
            result.elapsed_per_prompt[prompt] = -1.0
            result.elapsed_per_prompt[f"{prompt}_error"] = -1.0
            print(f"[sam3] prompt={prompt!r} 실패: {exc}")
            continue

        masks_t = post.get("masks")
        scores_t = post.get("scores")
        if masks_t is None or scores_t is None:
            result.elapsed_per_prompt[prompt] = time.perf_counter() - t0
            continue

        masks_np = masks_t.detach().cpu().numpy().astype(bool)
        scores_np = scores_t.detach().cpu().numpy().astype(float)

        # masks_np shape: (N, H, W)
        n_keep = min(len(masks_np), max_masks_per_concept)
        for i in range(n_keep):
            m = masks_np[i]
            if m.ndim == 3:  # 일부 모델은 (1, H, W)
                m = m.squeeze(0)
            bbox = mask_to_bbox(m)
            if bbox is None:
                continue
            result.masks.append(
                Sam3Mask(
                    bbox=bbox,
                    segmentation=m,
                    score=float(scores_np[i]),
                    concept=prompt,
                )
            )

        result.elapsed_per_prompt[prompt] = time.perf_counter() - t0

    return result
