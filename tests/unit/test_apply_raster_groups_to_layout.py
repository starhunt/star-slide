import json
from pathlib import Path

from PIL import Image

from scripts.apply_raster_groups_to_layout import apply_to_layout, make_asset


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    image_root = tmp_path / "images"
    layout_dir = tmp_path / "layouts"
    groups_dir = tmp_path / "groups"
    out_dir = tmp_path / "out"
    image_root.mkdir()
    layout_dir.mkdir()
    groups_dir.mkdir()

    image = Image.new("RGB", (100, 100), "white")
    for x in range(20, 31):
        for y in range(20, 31):
            image.putpixel((x, y), (255, 0, 0))
    image.save(image_root / "slide_001.png")

    layout = {
        "id": "slide_001",
        "image": "slide_001.png",
        "canvas": {"width": 100, "height": 100},
        "background": {"mode": "solid", "color": "#FFFFFF", "decorations": []},
        "objects": [
            {
                "type": "shape",
                "name": "small_editable_badge",
                "shape": "RECTANGLE",
                "bbox": [20, 20, 10, 10],
                "fill": "#FF0000",
                "stroke": "none",
            }
        ],
    }
    (layout_dir / "slide_001.layout.json").write_text(json.dumps(layout), encoding="utf-8")
    groups = {"raster_groups": [{"name": "large_panel", "bbox": [10, 10, 80, 80]}]}
    (groups_dir / "slide_001_raster_groups.json").write_text(json.dumps(groups), encoding="utf-8")
    return image_root, layout_dir, groups_dir, out_dir


def test_peel_child_objects_keeps_small_editable_child_and_punches_parent_layer(
    tmp_path: Path,
) -> None:
    image_root, layout_dir, groups_dir, out_dir = _write_fixture(tmp_path)

    result = apply_to_layout(
        layout_path=layout_dir / "slide_001.layout.json",
        image_root=image_root,
        groups_dir=groups_dir,
        sam_dir=None,
        out_dir=out_dir,
        punchout_padding=0,
        nontext_overlap_threshold=0.20,
        erase_mode="alpha",
        drop_full_slide_grid=False,
        rasterize_embedded_labels=False,
        peel_child_objects=True,
        child_object_max_area_ratio=0.25,
    )

    names = [obj["name"] for obj in result["objects"]]
    assert "small_editable_badge" in names
    assert "replaceable_large_panel" in names
    meta = result["metadata"]["raster_group_replacement"]
    assert meta["peeled_child_object_count"] == 1

    parent = next(obj for obj in result["objects"] if obj["name"] == "replaceable_large_panel")
    with Image.open(parent["path"]) as asset:
        assert asset.mode == "RGBA"
        # child bbox [20,20,10,10] is local [10,10,10,10] inside parent crop [10,10,80,80]
        assert asset.getpixel((10, 10))[3] == 0


def test_solid_erase_mode_fills_punchout_with_surrounding_color(tmp_path: Path) -> None:
    image = Image.new("RGB", (60, 60), "white")
    for x in range(20, 31):
        for y in range(20, 31):
            image.putpixel((x, y), (0, 0, 0))
    image_path = tmp_path / "slide.png"
    image.save(image_path)

    asset_path = make_asset(
        image_path=image_path,
        group={"name": "panel", "bbox": [10, 10, 40, 40]},
        punchouts=[[20, 20, 10, 10]],
        out_dir=tmp_path / "out",
        slide_stem="slide",
        index=1,
        padding=0,
        erase_mode="solid",
    )

    with Image.open(asset_path) as asset:
        assert asset.mode == "RGBA"
        assert asset.getpixel((10, 10))[:3] == (255, 255, 255)
        assert asset.getpixel((10, 10))[3] == 255
