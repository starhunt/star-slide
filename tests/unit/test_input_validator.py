"""input.validator 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from star_slide.input.validator import InputError, validate


class TestValidate:
    def test_pptx_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.pptx"
        f.write_bytes(b"PK\x03\x04dummy")  # ZIP magic + dummy
        assert validate(f) == "pptx"

    def test_pdf_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.pdf"
        f.write_bytes(b"%PDF-1.4 dummy")
        assert validate(f) == "pdf"

    def test_png_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\ndummy")
        assert validate(f) == "image"

    def test_zip_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.zip"
        f.write_bytes(b"PK\x03\x04dummy")
        assert validate(f) == "zip"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(InputError, match="존재하지"):
            validate(tmp_path / "missing.pptx")

    def test_directory_not_file(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(InputError, match="파일이 아닙"):
            validate(d)

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.pptx"
        f.write_bytes(b"")
        with pytest.raises(InputError, match="빈 파일"):
            validate(f)

    def test_size_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "huge.pptx"
        f.write_bytes(b"X" * 100)
        with pytest.raises(InputError, match="너무 큽"):
            validate(f, max_size_bytes=10)

    def test_unknown_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "weird.xyz"
        f.write_bytes(b"data")
        with pytest.raises(InputError, match="지원하지 않는 확장자"):
            validate(f)


class TestPptxExtractor:
    def test_inspect_real_pptx(self) -> None:
        """실제 NotebookLM 샘플로 동작 확인 (refdata 있을 때만)."""
        path = Path("refdata/sample1.pptx")
        if not path.exists():
            pytest.skip("refdata/sample1.pptx 없음")

        from star_slide.input.pptx_extractor import inspect_pptx, is_image_locked

        w, h, slides = inspect_pptx(path)
        assert w > 0 and h > 0
        assert len(slides) == 17  # NotebookLM sample1
        assert all(s.has_picture for s in slides)
        assert is_image_locked(path)
