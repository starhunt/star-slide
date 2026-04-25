"""python-pptx Shape에 custGeom XML 주입.

python-pptx는 add_shape()로 preset geometry 도형만 직접 만들 수 있다.
custGeom으로 바꾸려면 shape의 spPr/prstGeom 요소를 제거하고 custGeom XML을 삽입해야 함.

주의: shape의 cx, cy(크기)는 그대로 보존되며, custGeom 내부의 path는
a:path[w, h] 좌표계가 셰이프 사이즈에 맞게 스케일된다.
"""

from __future__ import annotations

from lxml import etree  # type: ignore[import-untyped]
from pptx.shapes.autoshape import Shape

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
A = f"{{{NS_A}}}"


def replace_geometry_with_custgeom(shape: Shape, custgeom_xml: str) -> None:
    """shape의 spPr 안의 prstGeom을 제거하고 custGeom으로 교체.

    Args:
        shape: python-pptx Shape (add_shape로 만든 도형)
        custgeom_xml: svg_path_to_custgeom()의 xml 문자열
    """
    sp_pr = shape._element.spPr

    # 기존 preset geometry 제거
    for prst in sp_pr.findall(f"{A}prstGeom"):
        sp_pr.remove(prst)

    # 기존 custGeom이 있다면 제거
    for cust in sp_pr.findall(f"{A}custGeom"):
        sp_pr.remove(cust)

    # 새 custGeom 파싱 후 삽입
    cust_el = etree.fromstring(custgeom_xml)

    # spPr 첫 자식 위치(xfrm 다음)에 삽입
    xfrm = sp_pr.find(f"{A}xfrm")
    if xfrm is not None:
        idx = list(sp_pr).index(xfrm) + 1
        sp_pr.insert(idx, cust_el)
    else:
        sp_pr.insert(0, cust_el)
