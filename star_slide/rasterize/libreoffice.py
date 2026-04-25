"""LibreOffice headless로 슬라이드 합성 렌더링 (PRD §6.2 FR-013).

LibreOffice 미설치 시 InputError. 사용자가 설치 후 재시도해야 함.
PPTX → PNG 페이지별 변환. 마스터 배경 + 본문 합성된 최종 비주얼.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

from star_slide.input.validator import InputError


def _find_soffice() -> str | None:
    """soffice 또는 libreoffice 바이너리 찾기."""
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


class LibreOfficeNotFoundError(InputError):
    """LibreOffice headless 바이너리가 시스템에 없음."""


def render_pptx_to_pngs(
    pptx_path: Path,
    out_dir: Path,
    *,
    timeout_sec: int = 120,
) -> list[Path]:
    """PPTX 전체를 PNG들로 변환.

    LibreOffice는 PPTX → PDF → PNG 파이프라인이 가장 안정적.
    여기서는 직접 PPTX → PNG 시도, 실패하면 PDF 경유.

    Args:
        pptx_path: 입력 PPTX
        out_dir: PNG 저장 디렉토리 (없으면 생성)
        timeout_sec: LibreOffice 타임아웃

    Returns:
        슬라이드 순서대로 정렬된 PNG 경로 리스트
    """
    soffice = _find_soffice()
    if soffice is None:
        raise LibreOfficeNotFoundError(
            "LibreOffice(soffice/libreoffice) 미설치. "
            "macOS: `brew install libreoffice`. Linux: apt/dnf로 설치."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    # PPTX → PDF 변환 (가장 신뢰할 수 있는 경로)
    pdf_dir = out_dir / "_pdf"
    pdf_dir.mkdir(exist_ok=True)
    cmd_pdf = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(pdf_dir),
        str(pptx_path),
    ]
    subprocess.run(cmd_pdf, check=True, timeout=timeout_sec, capture_output=True)

    pdf_path = pdf_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.exists():
        raise InputError(f"LibreOffice PDF 변환 실패: {pptx_path}")

    # PDF → PNG (pdf2image / Poppler)
    return _pdf_to_pngs(pdf_path, out_dir, dpi=192)


def _pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 192) -> list[Path]:
    """pdf2image로 PDF 페이지별 PNG 추출."""
    from pdf2image import convert_from_path

    images = convert_from_path(str(pdf_path), dpi=dpi)
    out_paths: list[Path] = []
    for i, img in enumerate(images, start=1):
        out_path = out_dir / f"slide_{i:03d}.png"
        img.save(out_path, "PNG")
        out_paths.append(out_path)
    return out_paths


def fallback_render_from_embedded(
    pptx_path: Path,
    out_dir: Path,
    target_dpi: int = 192,
) -> list[Path]:
    """LibreOffice 미설치 시 fallback: 임베드 이미지 직접 추출.

    이미지-잠금 PPTX(NotebookLM 패턴) 한정. 임베드 PNG가 슬라이드 EMU와
    1:1 일치하지 않을 수 있으나(다운샘플 가능), Phase 0에서 ~80% 일치 확인.
    """
    from star_slide.input.pptx_extractor import extract_embedded_images

    extracted = extract_embedded_images(pptx_path, out_dir)
    # 필요 시 target_dpi 기준으로 업샘플 (CONTINUITY 관찰: 1376→1707)
    out_dir.mkdir(parents=True, exist_ok=True)
    final_paths: list[Path] = []
    for src in extracted:
        # 단순화: 원본 그대로 사용. Phase 1에서 슬라이드 EMU 비율로 정규화 가능.
        with Image.open(src) as im:
            png_path = src.with_suffix(".png")
            if src.suffix.lower() != ".png":
                im.convert("RGB").save(png_path, "PNG")
                src.unlink(missing_ok=True)
            else:
                png_path = src
        final_paths.append(png_path)
    return final_paths
