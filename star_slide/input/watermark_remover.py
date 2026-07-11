"""우측 하단 NotebookLM 워터마크 영역 마스킹.

NotebookLM이 export 한 PPTX/PDF 슬라이드에는 우측 하단에 작은
"NotebookLM" 로고가 박혀 있다. 변환 옵션으로 이 영역만 슬라이드 배경색으로
덮어 LLM/렌더 양쪽에서 사라지게 한다.

전략:
- 슬라이드 가장자리 픽셀(테두리 1px) 의 중앙값을 슬라이드 배경 색으로 추정
- 우측 하단 일정 비율(기본 너비 13%, 높이 8%) 사각형을 그 색으로 페인트
- 배경이 단색이 아닐 때는 약간의 자국이 남을 수 있지만, 대부분 NotebookLM
  슬라이드는 흰/단색 배경이라 충분
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# 슬라이드 너비/높이 대비 워터마크 영역 비율 — NotebookLM 워터마크 실측 기준 보수적 값.
DEFAULT_BOX_RATIO_W = 0.13
DEFAULT_BOX_RATIO_H = 0.08
EDGE_SAMPLE_PX = 2  # 가장자리에서 배경색 추정에 사용할 라인 두께


def _estimate_background(image: Image.Image) -> tuple[int, int, int]:
    """가장자리 라인의 픽셀 중앙값을 슬라이드 배경 색으로 추정."""
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    width, height = rgb.size
    sample_px = max(1, min(EDGE_SAMPLE_PX, width // 4, height // 4))
    pixels: list[tuple[int, int, int]] = []
    rgb_bytes = rgb.tobytes()
    # 모서리에서 멀리 떨어진 가장자리 라인만 샘플 — 워터마크가 모서리 안쪽에 있을 때
    # 제거 영역 자체는 제외하기 위해 우측 끝 일부는 건너뜀.
    horizontal_skip = int(width * 0.18)
    vertical_skip = int(height * 0.10)
    for y in range(sample_px):
        for x in range(horizontal_skip, width - horizontal_skip):
            offset = (y * width + x) * 3
            pixels.append((rgb_bytes[offset], rgb_bytes[offset + 1], rgb_bytes[offset + 2]))
    for y in range(height - sample_px, height):
        for x in range(horizontal_skip, width - horizontal_skip):
            offset = (y * width + x) * 3
            pixels.append((rgb_bytes[offset], rgb_bytes[offset + 1], rgb_bytes[offset + 2]))
    for x in range(sample_px):
        for y in range(vertical_skip, height - vertical_skip):
            offset = (y * width + x) * 3
            pixels.append((rgb_bytes[offset], rgb_bytes[offset + 1], rgb_bytes[offset + 2]))
    if not pixels:
        return (255, 255, 255)
    # 채널별 중앙값
    rs = sorted(p[0] for p in pixels)
    gs = sorted(p[1] for p in pixels)
    bs = sorted(p[2] for p in pixels)
    mid = len(pixels) // 2
    return rs[mid], gs[mid], bs[mid]


def remove_watermark_inplace(
    image_path: Path,
    *,
    box_ratio_w: float = DEFAULT_BOX_RATIO_W,
    box_ratio_h: float = DEFAULT_BOX_RATIO_H,
) -> None:
    """우측 하단 워터마크 영역을 추정 배경색으로 덮어 같은 경로에 저장."""
    with Image.open(image_path) as opened:
        img = opened.convert("RGB")
    width, height = img.size
    box_w = max(1, int(width * box_ratio_w))
    box_h = max(1, int(height * box_ratio_h))
    pad_w = max(1, int(width * 0.005))
    pad_h = max(1, int(height * 0.005))
    x1 = width - pad_w - box_w
    y1 = height - pad_h - box_h
    x2 = width - pad_w
    y2 = height - pad_h
    if x1 >= x2 or y1 >= y2:
        return
    bg = _estimate_background(img)
    draw = ImageDraw.Draw(img)
    draw.rectangle([x1, y1, x2, y2], fill=bg)
    # 입력이 .jpg/.png 둘 다 있을 수 있으므로 형식 보존.
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        img.save(image_path, quality=92, optimize=True)
    else:
        img.save(image_path)


def remove_watermarks(image_paths: list[Path]) -> int:
    """여러 슬라이드 이미지에 일괄 적용. 처리한 개수 반환."""
    count = 0
    for path in image_paths:
        try:
            remove_watermark_inplace(path)
            count += 1
        except Exception:
            # best-effort — 한 슬라이드 실패가 전체 변환을 막지 않게.
            continue
    return count


def _watermark_box(width: int, height: int) -> tuple[int, int, int, int]:
    """우측 하단 워터마크 영역 좌표 (x1, y1, x2, y2)."""
    box_w = max(1, int(width * DEFAULT_BOX_RATIO_W))
    box_h = max(1, int(height * DEFAULT_BOX_RATIO_H))
    pad_w = max(1, int(width * 0.005))
    pad_h = max(1, int(height * 0.005))
    return width - pad_w - box_w, height - pad_h - box_h, width - pad_w, height - pad_h


def remove_watermark_inpaint_inplace(image_path: Path) -> None:
    """LaMa 인페인팅 — 우측 하단 워터마크 영역을 자연스럽게 채움.

    배경에 그라디언트/패턴/도형 등이 있어도 단순 페인트 대비 훨씬 자연스럽다.
    첫 호출 시 LaMa 가중치(~196MB) 자동 다운로드, 슬라이드당 1~3초 추가.
    """
    from star_slide.inpaint.lama import inpaint_with_mask

    with Image.open(image_path) as opened:
        img = opened.convert("RGB")
    width, height = img.size
    x1, y1, x2, y2 = _watermark_box(width, height)
    if x1 >= x2 or y1 >= y2:
        return
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rectangle([x1, y1, x2, y2], fill=255)
    inpainted = inpaint_with_mask(img, mask)
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        inpainted.save(image_path, quality=92, optimize=True)
    else:
        inpainted.save(image_path)


def remove_watermarks_inpaint(image_paths: list[Path]) -> int:
    count = 0
    for path in image_paths:
        try:
            remove_watermark_inpaint_inplace(path)
            count += 1
        except Exception:
            continue
    return count
