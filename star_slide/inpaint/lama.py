"""LaMa 인페인팅 wrapper (simple-lama-inpainting 기반).

PRD §6.5 FR-040: 텍스트 영역 마스크 → 자연스러운 배경 복원.
ADR-004 채택. IOPaint 대신 simple-lama-inpainting 사용 (경량, 의존성 적음).

big-lama 가중치(~196MB) 첫 호출 시 자동 다운로드.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from star_slide.segmentation.iou import Bbox

_LAMA_CACHE: dict[str, Any] = {}


def _get_lama() -> Any:
    """SimpleLama 인스턴스 캐싱."""
    if "lama" in _LAMA_CACHE:
        return _LAMA_CACHE["lama"]
    from simple_lama_inpainting import SimpleLama

    _LAMA_CACHE["lama"] = SimpleLama()
    return _LAMA_CACHE["lama"]


def _bboxes_to_mask(
    bboxes: list[Bbox],
    image_size: tuple[int, int],
    padding: int = 12,
    dilate_kernel: int = 5,
) -> Image.Image:
    """OCR/객체 bbox 리스트 → 흰색 마스크 PIL 이미지 (인페인팅 입력).

    LaMa 마스크 컨벤션: 흰색(255) = 인페인팅, 검정(0) = 보존.
    bbox 외부 padding + cv2.dilate로 한글 가장자리 잔재 방지.
    """
    import cv2

    w, h = image_size
    mask = np.zeros((h, w), dtype=np.uint8)
    for bx, by, bw, bh in bboxes:
        x1 = max(0, int(bx) - padding)
        y1 = max(0, int(by) - padding)
        x2 = min(w, int(bx + bw) + padding)
        y2 = min(h, int(by + bh) + padding)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255

    if dilate_kernel > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel)
        )
        mask = cv2.dilate(mask, kernel, iterations=1).astype(np.uint8)

    return Image.fromarray(mask, mode="L")


def inpaint_background(
    image: Image.Image | Path,
    bboxes: list[Bbox],
    *,
    padding: int = 12,
    dilate_kernel: int = 5,
    ssim_threshold: float = 0.3,
    return_mask: bool = False,
) -> Image.Image | tuple[Image.Image, Image.Image]:
    """이미지의 bbox 영역을 LaMa로 인페인팅.

    Args:
        image: 입력 PIL 또는 파일 경로
        bboxes: 지울 영역 (OCR 텍스트 bbox 등)
        padding: bbox 주변 padding (px) — 글자 가장자리까지 확실히 덮음
        ssim_threshold: 인페인팅 전후 SSIM 임계 (FR-041 안전 fallback)
        return_mask: True면 (inpainted, mask) 반환

    Returns:
        인페인팅된 PIL Image (또는 (inpainted, mask) 튜플)
    """
    pil = image if isinstance(image, Image.Image) else Image.open(image)
    pil = pil.convert("RGB")
    w, h = pil.size

    if not bboxes:
        if return_mask:
            empty_mask = Image.fromarray(np.zeros((h, w), dtype=np.uint8), mode="L")
            return pil, empty_mask
        return pil

    mask = _bboxes_to_mask(bboxes, (w, h), padding=padding, dilate_kernel=dilate_kernel)

    lama = _get_lama()
    inpainted = lama(pil, mask)
    # SimpleLama 반환은 PIL.Image 또는 numpy.ndarray (구버전).
    if not isinstance(inpainted, Image.Image):
        inpainted = Image.fromarray(np.asarray(inpainted))

    # SSIM 안전 검사 — 인페인팅이 이미지를 망가뜨리지 않았는지
    # (마스크 영역이 큰 경우 SSIM은 자연히 낮아짐, 보수적 임계값)
    try:
        orig_arr = np.asarray(pil.convert("L"))
        new_arr = np.asarray(inpainted.convert("L"))
        if orig_arr.shape == new_arr.shape:
            score = ssim(orig_arr, new_arr, data_range=255)  # type: ignore[no-untyped-call]
            if score < ssim_threshold:
                # 너무 망가졌으면 원본 사용
                inpainted = pil
    except Exception:
        pass

    if return_mask:
        return inpainted, mask
    return inpainted


def inpaint_to_path(
    image_path: Path,
    bboxes: list[Bbox],
    out_path: Path,
    *,
    padding: int = 4,
) -> NDArray[np.uint8]:
    """파일 → 인페인팅 → 파일. 편의 함수.

    Returns:
        결과 이미지의 numpy array
    """
    inpainted = inpaint_background(image_path, bboxes, padding=padding)
    if isinstance(inpainted, tuple):
        inpainted = inpainted[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inpainted.save(out_path)
    return np.asarray(inpainted)
