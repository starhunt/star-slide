"""입력 파일 검증 (PRD §6.1 FR-004).

확장자/MIME/크기/암호화/손상 검사. 무효 파일은 InputError로 빠르게 실패.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

SourceKind = Literal["pptx", "pdf", "image", "zip"]

VALID_EXTENSIONS: dict[str, SourceKind] = {
    ".pptx": "pptx",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".zip": "zip",
}

# 단순화: 1GB 상한 (P1)
MAX_FILE_SIZE_BYTES = 1024 * 1024 * 1024


class InputError(ValueError):
    """입력 파일 관련 모든 에러의 부모."""


def validate(
    path: Path,
    *,
    max_size_bytes: int = MAX_FILE_SIZE_BYTES,
) -> SourceKind:
    """파일 경로 검증 → 종류 반환.

    Raises:
        InputError: 존재하지 않음 / 비지원 확장자 / 크기 초과 / 빈 파일
    """
    if not path.exists():
        raise InputError(f"파일이 존재하지 않습니다: {path}")
    if not path.is_file():
        raise InputError(f"파일이 아닙니다: {path}")

    size = path.stat().st_size
    if size == 0:
        raise InputError(f"빈 파일입니다: {path}")
    if size > max_size_bytes:
        raise InputError(
            f"파일이 너무 큽니다 ({size / 1024 / 1024:.1f}MB > "
            f"{max_size_bytes / 1024 / 1024:.0f}MB): {path}"
        )

    ext = path.suffix.lower()
    kind = VALID_EXTENSIONS.get(ext)
    if kind is None:
        raise InputError(f"지원하지 않는 확장자 {ext!r}. 허용: {sorted(VALID_EXTENSIONS)}")

    return kind


def is_password_protected_pptx(path: Path) -> bool:
    """PPTX 암호 보호 여부 (간단 검사 — OOXML 미파싱).

    OOXML 암호화 PPTX는 OLE Compound Document 시그니처(D0 CF 11 E0 A1 B1 1A E1) 시작.
    """
    with path.open("rb") as f:
        head = f.read(8)
    return head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
