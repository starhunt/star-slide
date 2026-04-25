"""svg2custgeom 변환기 단위 테스트."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from star_slide.composer.svg2custgeom import (
    NS_A,
    CustGeomResult,
    svg_path_to_custgeom,
)


class TestRectangle:
    def test_basic_rectangle(self) -> None:
        d = "M 0 0 L 100 0 L 100 60 L 0 60 Z"
        result = svg_path_to_custgeom(d)

        assert isinstance(result, CustGeomResult)
        assert result.bbox == (0.0, 0.0, 100.0, 60.0)
        assert result.n_segments == 5  # M, L, L, L, Z
        assert not result.has_arc

    def test_xml_has_required_elements(self) -> None:
        d = "M 0 0 L 100 0 L 100 60 L 0 60 Z"
        result = svg_path_to_custgeom(d)

        root = ET.fromstring(result.xml)
        ns = {"a": NS_A}
        assert root.find("a:pathLst", ns) is not None
        path = root.find("a:pathLst/a:path", ns)
        assert path is not None
        assert path.get("w") == "1000000"
        assert path.get("h") == "1000000"

        moves = path.findall("a:moveTo", ns)
        lns = path.findall("a:lnTo", ns)
        closes = path.findall("a:close", ns)
        assert len(moves) == 1
        assert len(lns) == 3
        assert len(closes) == 1

    def test_coordinates_scaled_to_target(self) -> None:
        d = "M 0 0 L 100 0 L 100 100 L 0 100 Z"
        result = svg_path_to_custgeom(d, target_w=2_000_000, target_h=2_000_000)

        root = ET.fromstring(result.xml)
        ns = {"a": NS_A}
        # M (0,0) → (0, 0)
        move_pt = root.find("a:pathLst/a:path/a:moveTo/a:pt", ns)
        assert move_pt is not None
        assert int(move_pt.get("x") or "0") == 0
        assert int(move_pt.get("y") or "0") == 0

        # 마지막 lnTo는 (0, 100) → (0, 2,000,000)
        ln_pts = root.findall("a:pathLst/a:path/a:lnTo/a:pt", ns)
        assert len(ln_pts) == 3
        last = ln_pts[-1]
        assert int(last.get("x") or "0") == 0
        assert int(last.get("y") or "0") == 2_000_000


class TestBezier:
    def test_cubic_bezier(self) -> None:
        # 진짜 곡선 — control point가 위로 올라가서 bbox.h > 0
        d = "M 0 50 C 25 0 75 0 100 50 Z"
        result = svg_path_to_custgeom(d)
        root = ET.fromstring(result.xml)
        ns = {"a": NS_A}
        cubics = root.findall("a:pathLst/a:path/a:cubicBezTo", ns)
        assert len(cubics) == 1
        # 각 cubicBezTo는 3개 a:pt (control1, control2, end)
        pts = cubics[0].findall("a:pt", ns)
        assert len(pts) == 3

    def test_quadratic_bezier(self) -> None:
        # M..L..Q..Z 구조 (Q 단독은 종종 bbox 0)
        d = "M 0 50 Q 50 0 100 50 L 100 100 L 0 100 Z"
        result = svg_path_to_custgeom(d)
        root = ET.fromstring(result.xml)
        ns = {"a": NS_A}
        quads = root.findall("a:pathLst/a:path/a:quadBezTo", ns)
        assert len(quads) == 1
        # quadBezTo는 2개 a:pt (control, end)
        pts = quads[0].findall("a:pt", ns)
        assert len(pts) == 2


class TestEdgeCases:
    def test_negative_coords_normalized(self) -> None:
        # 음수 좌표 → bbox 기준으로 정규화되어 모두 양수
        d = "M -50 -50 L 50 -50 L 50 50 L -50 50 Z"
        result = svg_path_to_custgeom(d)

        assert result.bbox == (-50.0, -50.0, 100.0, 100.0)
        root = ET.fromstring(result.xml)
        # 모든 좌표 ≥ 0
        for pt in root.iter(f"{{{NS_A}}}pt"):
            assert int(pt.get("x") or "0") >= 0
            assert int(pt.get("y") or "0") >= 0

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="bbox"):
            svg_path_to_custgeom("M 0 0")

    def test_xml_namespace_prefix_normalized(self) -> None:
        d = "M 0 0 L 100 100 Z"
        result = svg_path_to_custgeom(d)
        # ns0 prefix가 a:로 정규화되어야 PowerPoint 인식 가능
        assert "ns0:" not in result.xml
        assert "a:custGeom" in result.xml or "{http" in result.xml
