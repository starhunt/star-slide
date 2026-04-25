"""SVG path d=... → OOXML <a:custGeom> XML 변환기.

PRD §11 / DevPlan P0-T04 / ADR-005 핵심 모듈.

OOXML 사양 ECMA-376 Part 1, 20.1.9.10 a:custGeom:
- a:pathLst > a:path[w, h] > [a:moveTo | a:lnTo | a:cubicBezTo | a:quadBezTo | a:close ...]
- 각 점은 a:pt[x, y]. 값은 a:path의 w, h를 절대 단위로 한 정수.

EMU 변환:
- 914,400 EMU = 1 inch
- 12,700 EMU = 1 pt
- 슬라이드 16:9 기본 = 9,144,000 x 6,858,000 EMU (10 x 7.5 inch)

본 변환기는 path 좌표계를 그대로 보존하면서 a:path[w, h]에 bbox를 등록 → PowerPoint가
도형 셰이프 사이즈에 맞게 알아서 스케일링.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from svg.path import (
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    Path,
    QuadraticBezier,
    parse_path,
)

# OOXML namespace
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
ET.register_namespace("a", NS_A)


@dataclass(frozen=True)
class CustGeomResult:
    """svg→custGeom 변환 결과.

    xml: a:custGeom 루트 XML 문자열 (네임스페이스 prefix 'a:' 포함)
    bbox: SVG 좌표계 기준 (x, y, w, h)
    n_segments: path 명령 개수 (성능/품질 모니터링용)
    has_arc: SVG arc(A)가 포함됐는지 (PowerPoint 호환성 주의 신호)
    """

    xml: str
    bbox: tuple[float, float, float, float]
    n_segments: int
    has_arc: bool


def _arc_to_cubics(arc: Arc) -> list[CubicBezier]:
    """SVG arc → cubic bezier 근사 (svg.path 자체에는 변환 미제공).

    간단한 4-point cubic 근사 — 90° 이하 호로 분할.
    상용 정확도 필요 시 a2c (https://github.com/fontello/svgpath/blob/master/lib/a2c.js) 포팅 권장.
    Phase 0 PoC 수준에서는 단순화: arc를 chord로 대체 (직선 근사).
    """
    return [CubicBezier(arc.start, arc.start, arc.end, arc.end)]


def _compute_bbox(path: Path) -> tuple[float, float, float, float]:
    """path의 좌표 기반 bbox. svg.path가 제공하지 않으므로 점 샘플링.

    각 segment에서 시작점과 끝점, 그리고 곡선이면 중간 5점을 샘플링.
    """
    xs: list[float] = []
    ys: list[float] = []

    for seg in path:
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            try:
                pt = seg.point(t)
            except (ZeroDivisionError, AttributeError):
                continue
            xs.append(pt.real)
            ys.append(pt.imag)

    if not xs:
        return (0.0, 0.0, 0.0, 0.0)

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return (x_min, y_min, x_max - x_min, y_max - y_min)


def _emit_pt(parent: ET.Element, x: int, y: int) -> None:
    pt = ET.SubElement(parent, f"{{{NS_A}}}pt")
    pt.set("x", str(x))
    pt.set("y", str(y))


def _emit_move_to(parent: ET.Element, x: int, y: int) -> None:
    el = ET.SubElement(parent, f"{{{NS_A}}}moveTo")
    _emit_pt(el, x, y)


def _emit_ln_to(parent: ET.Element, x: int, y: int) -> None:
    el = ET.SubElement(parent, f"{{{NS_A}}}lnTo")
    _emit_pt(el, x, y)


def _emit_cubic_bez_to(
    parent: ET.Element,
    c1: tuple[int, int],
    c2: tuple[int, int],
    end: tuple[int, int],
) -> None:
    el = ET.SubElement(parent, f"{{{NS_A}}}cubicBezTo")
    _emit_pt(el, *c1)
    _emit_pt(el, *c2)
    _emit_pt(el, *end)


def _emit_quad_bez_to(
    parent: ET.Element,
    c: tuple[int, int],
    end: tuple[int, int],
) -> None:
    el = ET.SubElement(parent, f"{{{NS_A}}}quadBezTo")
    _emit_pt(el, *c)
    _emit_pt(el, *end)


def _emit_close(parent: ET.Element) -> None:
    ET.SubElement(parent, f"{{{NS_A}}}close")


def svg_path_to_custgeom(
    d: str,
    target_w: int = 1_000_000,
    target_h: int = 1_000_000,
) -> CustGeomResult:
    """SVG path d=... 문자열 → custGeom XML.

    Args:
        d: SVG path 데이터 (예: "M 100 100 L 200 200 Z")
        target_w, target_h: a:path[w, h] 값. PowerPoint에서 셰이프 크기에 맞게 스케일됨.
                            기본 1,000,000은 부동소수 정밀도와 정수 변환의 균형.

    Returns:
        CustGeomResult(xml, bbox, n_segments, has_arc)
    """
    path = parse_path(d)
    bbox = _compute_bbox(path)
    bx, by, bw, bh = bbox

    if bw <= 0 or bh <= 0:
        raise ValueError(f"path bbox가 유효하지 않음: {bbox}")

    sx = target_w / bw
    sy = target_h / bh

    def _scale_pt(c: complex) -> tuple[int, int]:
        x = round((c.real - bx) * sx)
        y = round((c.imag - by) * sy)
        return (x, y)

    # XML 빌드
    cust_geom = ET.Element(f"{{{NS_A}}}custGeom")
    ET.SubElement(cust_geom, f"{{{NS_A}}}avLst")
    ET.SubElement(cust_geom, f"{{{NS_A}}}gdLst")
    ET.SubElement(cust_geom, f"{{{NS_A}}}ahLst")
    ET.SubElement(cust_geom, f"{{{NS_A}}}cxnLst")
    ET.SubElement(cust_geom, f"{{{NS_A}}}rect", l="l", t="t", r="r", b="b")
    path_lst = ET.SubElement(cust_geom, f"{{{NS_A}}}pathLst")
    a_path = ET.SubElement(
        path_lst,
        f"{{{NS_A}}}path",
        w=str(target_w),
        h=str(target_h),
    )

    has_arc = False
    n_segments = 0

    for seg in path:
        n_segments += 1
        if isinstance(seg, Move):
            _emit_move_to(a_path, *_scale_pt(seg.end))
        elif isinstance(seg, Line):
            _emit_ln_to(a_path, *_scale_pt(seg.end))
        elif isinstance(seg, CubicBezier):
            _emit_cubic_bez_to(
                a_path,
                _scale_pt(seg.control1),
                _scale_pt(seg.control2),
                _scale_pt(seg.end),
            )
        elif isinstance(seg, QuadraticBezier):
            _emit_quad_bez_to(
                a_path,
                _scale_pt(seg.control),
                _scale_pt(seg.end),
            )
        elif isinstance(seg, Close):
            _emit_close(a_path)
        elif isinstance(seg, Arc):
            has_arc = True
            for cubic in _arc_to_cubics(seg):
                _emit_cubic_bez_to(
                    a_path,
                    _scale_pt(cubic.control1),
                    _scale_pt(cubic.control2),
                    _scale_pt(cubic.end),
                )
        else:
            raise NotImplementedError(f"지원하지 않는 SVG segment: {type(seg).__name__}")

    xml_str = ET.tostring(cust_geom, encoding="unicode")
    # 네임스페이스 prefix 정규화 ('ns0:' → 'a:')
    xml_str = xml_str.replace(f'xmlns:ns0="{NS_A}"', f'xmlns:a="{NS_A}"')
    xml_str = xml_str.replace("ns0:", "a:")

    return CustGeomResult(
        xml=xml_str,
        bbox=bbox,
        n_segments=n_segments,
        has_arc=has_arc,
    )
