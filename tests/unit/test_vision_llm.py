"""Vision LLM 단위 테스트 — 외부 통신 없이 파싱/스키마/HTTP 서버만 검증."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from star_slide.vision_llm import VisionExtractor, VisionSlide
from star_slide.vision_llm.extractor import VisionExtractError


def test_parse_plain_json() -> None:
    raw = json.dumps(
        {
            "image_size": [1280, 720],
            "elements": [
                {
                    "type": "text",
                    "bbox": {"x": 100, "y": 200, "w": 300, "h": 40},
                    "content": "안녕하세요",
                    "color": "#000000",
                    "font_size_pt": 24.0,
                }
            ],
        }
    )
    slide = VisionExtractor._parse_json(raw)
    assert isinstance(slide, VisionSlide)
    assert slide.image_size == (1280, 720)
    assert len(slide.elements) == 1
    el = slide.elements[0]
    assert el.type == "text"
    assert el.content == "안녕하세요"


def test_parse_markdown_fenced_json() -> None:
    raw = (
        "```json\n"
        '{"image_size":[640,480],'
        '"elements":[{"type":"shape","bbox":{"x":0,"y":0,"w":10,"h":10},'
        '"subtype":"rectangle","fill":"#FF0000"}]}\n'
        "```"
    )
    slide = VisionExtractor._parse_json(raw)
    assert slide.image_size == (640, 480)
    assert slide.elements[0].type == "shape"
    assert slide.elements[0].fill == "#FF0000"


def test_parse_with_leading_prose_extracts_braces() -> None:
    raw = 'Sure, here is the JSON:\n{"image_size":[100,100],"elements":[]}\nHope this helps.'
    slide = VisionExtractor._parse_json(raw)
    assert slide.image_size == (100, 100)
    assert slide.elements == []


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(VisionExtractError):
        VisionExtractor._parse_json("not json at all")


def test_parse_missing_required_fields_raises() -> None:
    raw = '{"elements": []}'  # image_size 누락
    with pytest.raises(VisionExtractError):
        VisionExtractor._parse_json(raw)


def test_local_http_server_serves_png(tmp_path: Path) -> None:
    """start_server / url_for / stop_server 라이프사이클 + 실제 GET."""
    png = tmp_path / "slide_001.png"
    # 가짜 PNG 헤더 + 작은 본문 (타입 감지보다 raw bytes 확인이 목적)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)

    extractor = VisionExtractor(api_key="dummy")
    extractor.start_server(tmp_path)
    try:
        url = extractor.url_for(png)
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            data = resp.read()
        assert data.startswith(b"\x89PNG")
    finally:
        extractor.stop_server()


def test_url_for_requires_started_server(tmp_path: Path) -> None:
    extractor = VisionExtractor(api_key="dummy")
    with pytest.raises(VisionExtractError):
        extractor.url_for(tmp_path / "x.png")


def test_serving_context_manager(tmp_path: Path) -> None:
    extractor = VisionExtractor(api_key="dummy")
    with extractor.serving(tmp_path):
        assert extractor._server is not None
    assert extractor._server is None
