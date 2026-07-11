"""vtracer CLI wrapper — 마스크/이미지 PNG → SVG path d 문자열.

PRD §10.1 / ADR-003. vtracer 0.6.5 (MIT) 사용.
- BW 모드: 단색 마스크 → 단일 path
- 기본 위치는 vtracer가 transform="translate(x,y)"로 출력하지만,
  PowerPoint shape는 EMU 위치를 자체 보유하므로 transform을 d 문자열에 합쳐서 반환.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET

from PIL import Image

VTRACER_BIN_DEFAULT = "vtracer"

SVG_NS = "http://www.w3.org/2000/svg"


class VtracerNotFoundError(RuntimeError):
    """vtracer 바이너리를 찾을 수 없음."""


class VtracerError(RuntimeError):
    """vtracer 실행 실패."""


@dataclass(frozen=True)
class TracedPath:
    """vtracer가 추출한 한 path."""

    d: str  # SVG path d, transform 적용된 절대 좌표
    fill: str  # hex color (예: '#000000') 또는 'none'
    bbox: tuple[float, float, float, float]  # SVG 좌표 (x, y, w, h)


def _resolve_translate(transform: str | None) -> tuple[float, float]:
    """vtracer 'translate(x, y)' 형식 파싱."""
    if not transform:
        return (0.0, 0.0)
    m = re.search(r"translate\(\s*([-\d.]+)\s*,?\s*([-\d.]+)?\s*\)", transform)
    if not m:
        return (0.0, 0.0)
    tx = float(m.group(1))
    ty = float(m.group(2)) if m.group(2) is not None else 0.0
    return (tx, ty)


def _apply_translate_to_d(d: str, dx: float, dy: float) -> str:
    """path d 문자열의 절대 좌표에 (dx, dy) 가산.

    vtracer는 absolute 명령(M, L, C, ...)만 사용한다고 가정 (대문자).
    상대 명령(m, l, ...) 혼합 시에는 첫 번째 점만 이동되므로 이 가정이 깨지면 잘못된 결과.
    실측: vtracer 0.6.5 BW 모드는 모두 absolute로 출력.
    """
    if dx == 0 and dy == 0:
        return d

    # 명령자 유지하면서 좌표 쌍만 변환. 명령자: [MmLlCcSsQqTtAaZz]
    # 토큰화: 명령자 또는 숫자 (음수, 소수 허용)
    tokens: list[str] = []
    for tok in re.findall(r"[MmLlCcSsQqTtAaZz]|-?\d+\.?\d*(?:[eE][-+]?\d+)?", d):
        tokens.append(tok)

    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        cmd = tokens[i]
        out.append(cmd)
        i += 1
        if cmd in ("Z", "z"):
            continue
        # 각 명령의 (x, y) 쌍 개수
        if cmd in ("M", "m", "L", "l", "T", "t"):
            pair_count = 1
        elif cmd in ("Q", "q", "S", "s"):
            pair_count = 2
        elif cmd in ("C", "c"):
            pair_count = 3
        elif cmd in ("A", "a"):
            # rx ry rot large sweep x y — 6 params + 1 endpoint. 단순화: 마지막 2개만 좌표.
            pair_count = 1  # 처리 단순화
            for _ in range(5):
                if i < n:
                    out.append(tokens[i])
                    i += 1
        elif cmd in ("H", "h", "V", "v"):
            # 단일 좌표 (수평/수직). 보수적으로 1개 처리.
            if i < n:
                v = float(tokens[i])
                v += dx if cmd in ("H", "h") else dy
                out.append(f"{v:g}")
                i += 1
            continue
        else:
            # 알 수 없는 명령 → 그대로 통과 (다음 명령자까지 좌표로 간주하지 않음)
            continue

        # 같은 명령은 좌표 쌍이 반복될 수 있음 (e.g. "L 1 2 3 4 5 6"). 명령자 또는 끝까지 처리.
        is_relative = cmd.islower()
        while i < n and not tokens[i][0].isalpha():
            for _ in range(pair_count):
                if i + 1 >= n:
                    break
                x = float(tokens[i])
                y = float(tokens[i + 1])
                if not is_relative:
                    x += dx
                    y += dy
                out.append(f"{x:g}")
                out.append(f"{y:g}")
                i += 2

    return " ".join(out)


def _path_bbox(d: str) -> tuple[float, float, float, float]:
    """path d 문자열의 좌표만 보고 (느슨한) bbox 계산. svg.path 호출 회피용 빠른 헬퍼."""
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", d)]
    if len(nums) < 2:
        return (0.0, 0.0, 0.0, 0.0)
    xs = nums[0::2]
    ys = nums[1::2]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return (x_min, y_min, x_max - x_min, y_max - y_min)


def trace_image(
    image_path: Path,
    *,
    color_mode: Literal["bw", "color"] = "bw",
    mode: Literal["pixel", "polygon", "spline"] = "spline",
    filter_speckle: int = 4,
    corner_threshold: int = 60,
    bin_path: str = VTRACER_BIN_DEFAULT,
) -> list[TracedPath]:
    """이미지 → SVG → TracedPath 리스트.

    Args:
        image_path: 입력 PNG/JPG 경로
        color_mode: 'bw' (이진) | 'color' (멀티 컬러)
        mode: vtracer 곡선 fitting (기본 spline)
        filter_speckle: X px 이하 점 무시
        corner_threshold: 코너 판정 각도(도)
        bin_path: vtracer 바이너리 경로
    """
    if not image_path.exists():
        raise FileNotFoundError(f"vtracer 입력 없음: {image_path}")

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        cmd = [
            bin_path,
            "--input",
            str(image_path),
            "--output",
            str(out_path),
            "--colormode",
            color_mode,
            "--mode",
            mode,
            "--filter_speckle",
            str(filter_speckle),
            "--corner_threshold",
            str(corner_threshold),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError as exc:
            raise VtracerNotFoundError(f"vtracer 바이너리를 찾을 수 없음: {bin_path}") from exc

        if proc.returncode != 0:
            raise VtracerError(f"vtracer 실패 (code={proc.returncode}): {proc.stderr.strip()}")

        return _parse_svg(out_path)
    finally:
        out_path.unlink(missing_ok=True)


def _parse_svg(svg_path: Path) -> list[TracedPath]:
    """vtracer 출력 SVG에서 path 요소들을 추출. transform은 d에 흡수."""
    tree = ET.parse(svg_path)
    root = tree.getroot()

    paths: list[TracedPath] = []
    for el in root.iter(f"{{{SVG_NS}}}path"):
        d = el.get("d", "").strip()
        if not d:
            continue
        fill = el.get("fill") or "#000000"
        dx, dy = _resolve_translate(el.get("transform"))
        if dx != 0 or dy != 0:
            d = _apply_translate_to_d(d, dx, dy)
        bbox = _path_bbox(d)
        if bbox[2] <= 0 or bbox[3] <= 0:
            continue
        paths.append(TracedPath(d=d, fill=fill, bbox=bbox))

    return paths


def dominant_hex_color(image: Image.Image) -> str:
    """이미지의 최빈 픽셀 색상을 hex로 반환 (검정/흰색은 제외하지 않음).

    Phase 1 단순 휴리스틱 — Pillow getcolors() 사용. 256 색상 한도 초과 시
    quantize(16색)로 축약 후 측정.
    """
    img = image.convert("RGB")
    colors = img.getcolors(maxcolors=img.width * img.height)
    if colors is None:
        img = img.quantize(colors=16).convert("RGB")
        colors = img.getcolors(maxcolors=img.width * img.height)
    if not colors:
        return "#000000"
    _count, rgb = max(colors, key=lambda c: c[0])
    if not isinstance(rgb, tuple) or len(rgb) < 3:
        return "#000000"
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return f"#{r:02X}{g:02X}{b:02X}"
