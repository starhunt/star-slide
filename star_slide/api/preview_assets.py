"""Generate per-slide thumbnail JPEGs for web preview comparison.

Reads slide PNGs from workdir subdirectories (images, qa_vector, qa_hybrid,
qa_selected) and writes downsampled JPEGs to artifacts/previews/. Each kind
is optional — missing directories or files are silently skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PREVIEW_KINDS = ("original", "vector", "hybrid", "selected")
DEFAULT_MAX_WIDTH = 480
DEFAULT_QUALITY = 80
SLIDE_NUMBER_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class PreviewIndexEntry:
    slide_no: int
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class PreviewGenerationResult:
    out_dir: Path
    entries: tuple[PreviewIndexEntry, ...]
    files: tuple[Path, ...]


def slide_number_from_name(name: str) -> int | None:
    match = SLIDE_NUMBER_RE.search(name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def collect_slide_pngs(directory: Path) -> dict[int, Path]:
    """Return {slide_no: PNG path} for the given directory (sorted by name).

    Multiple PNGs per slide are tolerated by keeping the lexicographically
    first one — qa_* directories typically have at most one png per slide.
    """
    if not directory.exists() or not directory.is_dir():
        return {}
    chosen: dict[int, Path] = {}
    for path in sorted(directory.glob("*.png")):
        slide_no = slide_number_from_name(path.stem)
        if slide_no is None:
            continue
        chosen.setdefault(slide_no, path)
    return chosen


def downsample_to_jpeg(
    src: Path,
    dst: Path,
    *,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
) -> Path:
    with Image.open(src) as opened:
        working: Image.Image = opened if opened.mode in {"RGB", "L"} else opened.convert("RGB")
        width, height = working.size
        if width > max_width:
            ratio = max_width / width
            working = working.resize(
                (max_width, max(1, round(height * ratio))),
                Image.Resampling.LANCZOS,
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        working.save(dst, format="JPEG", quality=quality, optimize=True)
    return dst


def generate_previews(
    *,
    workdir: Path,
    out_dir: Path,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
) -> PreviewGenerationResult:
    """Build per-slide thumbnail JPEGs into out_dir.

    Source directories (under workdir):
      - images/        -> kind "original"
      - qa_vector/     -> kind "vector"
      - qa_hybrid/     -> kind "hybrid"
      - qa_selected/   -> kind "selected"
    """
    sources: dict[str, Path] = {
        "original": workdir / "images",
        "vector": workdir / "qa_vector",
        "hybrid": workdir / "qa_hybrid",
        "selected": workdir / "qa_selected",
    }
    files_per_kind: dict[str, dict[int, Path]] = {
        kind: collect_slide_pngs(directory) for kind, directory in sources.items()
    }

    slide_numbers: set[int] = set()
    for files in files_per_kind.values():
        slide_numbers.update(files.keys())

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    entries: list[PreviewIndexEntry] = []
    for slide_no in sorted(slide_numbers):
        present_kinds: list[str] = []
        for kind in PREVIEW_KINDS:
            src = files_per_kind.get(kind, {}).get(slide_no)
            if src is None:
                continue
            dst = out_dir / f"{slide_no:03d}_{kind}.jpg"
            try:
                downsample_to_jpeg(src, dst, max_width=max_width, quality=quality)
            except (OSError, ValueError):
                continue
            written.append(dst)
            present_kinds.append(kind)
        if present_kinds:
            entries.append(PreviewIndexEntry(slide_no=slide_no, kinds=tuple(present_kinds)))

    return PreviewGenerationResult(out_dir=out_dir, entries=tuple(entries), files=tuple(written))


def index_previews(out_dir: Path) -> list[PreviewIndexEntry]:
    """Re-discover existing previews on disk for index API responses."""
    if not out_dir.exists():
        return []
    by_slide: dict[int, list[str]] = {}
    pattern = re.compile(r"^(\d+)_([a-z]+)\.jpg$")
    for path in sorted(out_dir.glob("*.jpg")):
        match = pattern.match(path.name)
        if not match:
            continue
        slide_no = int(match.group(1))
        kind = match.group(2)
        if kind not in PREVIEW_KINDS:
            continue
        by_slide.setdefault(slide_no, []).append(kind)
    entries: list[PreviewIndexEntry] = []
    for slide_no in sorted(by_slide):
        ordered = tuple(kind for kind in PREVIEW_KINDS if kind in by_slide[slide_no])
        entries.append(PreviewIndexEntry(slide_no=slide_no, kinds=ordered))
    return entries
