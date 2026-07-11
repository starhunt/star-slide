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
from numpy.typing import NDArray
from PIL import Image

from star_slide.segmentation.iou import Bbox, mask_to_bbox

DEFAULT_MODEL_ID = "facebook/sam3"


def _require_torch() -> Any:
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "SAM3에는 GPU segmentation 의존성이 필요합니다. "
            "`uv sync --extra gpu-segmentation`을 실행하세요."
        ) from exc
    return torch


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
    concept: str  # 어떤 prompt에서 검출됐는지 (box prompt면 'box:<idx>')
    source_box_idx: int | None = None  # box-prompt에서 어느 입력 박스에 매칭됐는가


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
    torch = _require_torch()
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

    try:
        from transformers import Sam3Model, Sam3Processor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "SAM3에는 GPU segmentation 의존성이 필요합니다. "
            "`uv sync --extra gpu-segmentation`을 실행하세요."
        ) from exc

    model = Sam3Model.from_pretrained(model_id).to(device)
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
    torch = _require_torch()

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


def run_sam3_box_prompts(
    image: Path | NDArray[np.uint8] | Image.Image,
    boxes_xywh: list[Bbox],
    *,
    model_id: str = DEFAULT_MODEL_ID,
    device: str = "auto",
    threshold: float = 0.0,
    mask_threshold: float = 0.5,
) -> Sam3Result:
    """OCR bbox 리스트 → 박스별 정밀 마스크 (per-box forward).

    PCS 패러다임의 핵심 활용 — 외부에서 박스를 주면 그 박스 안 객체의
    *정밀 픽셀 마스크* 반환. OCR이 텍스트 박스를 제공하므로 박스당 글자
    ink 픽셀까지 정확히 segment.

    threshold=0.0: 박스마다 mask 1개 보장 (drop 방지). best score 마스크 채택.
    PoC 검증: per-box forward가 batched 모드보다 누락 없음 (24/24).
    """
    import time

    pil = _to_pil(image)
    w, h = pil.size
    torch = _require_torch()
    dev = _select_device(device)
    model, processor = _load_sam3(model_id=model_id, device=dev)

    result = Sam3Result(image_size=(w, h), device=dev)
    t0 = time.perf_counter()

    for i, box_xywh in enumerate(boxes_xywh):
        bx, by, bw, bh = box_xywh
        if bw <= 0 or bh <= 0:
            continue
        box_xyxy = [[float(bx), float(by), float(bx + bw), float(by + bh)]]
        try:
            inputs = processor(
                images=pil,
                input_boxes=[box_xyxy],
                input_boxes_labels=[[1]],
                return_tensors="pt",
            ).to(dev)
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
        except Exception:
            continue

        masks_t = post.get("masks")
        scores_t = post.get("scores")
        if masks_t is None or scores_t is None or len(masks_t) == 0:
            continue

        scores_np = scores_t.detach().cpu().numpy().astype(float)
        if len(scores_np) == 0:
            continue
        best = int(scores_np.argmax())

        m = masks_t[best].detach().cpu().numpy()
        if m.dtype != bool:
            m = m.astype(bool)
        if m.ndim == 3:
            m = m.squeeze(0)
        if m.shape != (h, w):
            continue
        bbox = mask_to_bbox(m)
        if bbox is None:
            continue

        result.masks.append(
            Sam3Mask(
                bbox=bbox,
                segmentation=m,
                score=float(scores_np[best]),
                concept=f"box:{i}",
                source_box_idx=i,
            )
        )

    result.elapsed_per_prompt["__box_prompt_total__"] = time.perf_counter() - t0
    return result


def run_sam3_text_prompt(
    image: Path | NDArray[np.uint8] | Image.Image,
    prompt: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    device: str = "auto",
    threshold: float = 0.3,
    mask_threshold: float = 0.5,
    max_masks: int = 200,
) -> Sam3Result:
    """단일 text 컨셉 prompt로 그 컨셉의 모든 인스턴스 마스크.

    OCR 미검출 텍스트(prompt='text'), 특정 도형 카테고리(prompt='chart',
    'graphic', 'rectangle' 등) 검출 등에 활용.

    threshold 권장:
      - 'text' 0.3 (잔재 보충용 — 관대한 임계로 모든 텍스트 영역 capture)
      - 'chart'/'graphic'/'rectangle' 0.5
    """
    import time

    pil = _to_pil(image)
    w, h = pil.size
    torch = _require_torch()
    dev = _select_device(device)
    model, processor = _load_sam3(model_id=model_id, device=dev)

    result = Sam3Result(image_size=(w, h), device=dev)
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
        print(f"[sam3] text prompt={prompt!r} 실패: {exc}")
        return result

    masks_t = post.get("masks")
    scores_t = post.get("scores")
    if masks_t is None or scores_t is None:
        result.elapsed_per_prompt[prompt] = time.perf_counter() - t0
        return result

    masks_np = masks_t.detach().cpu().numpy().astype(bool)
    scores_np = scores_t.detach().cpu().numpy().astype(float)
    n_keep = min(len(masks_np), max_masks)
    for i in range(n_keep):
        m = masks_np[i]
        if m.ndim == 3:
            m = m.squeeze(0)
        if m.shape != (h, w):
            continue
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
