from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image


def _load_batch_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate_layout_batch.py"
    spec = importlib.util.spec_from_file_location("generate_layout_batch", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_fallback_layout_creates_full_slide_image_object(tmp_path: Path) -> None:
    module = _load_batch_module()
    image = tmp_path / "slide_017.png"
    Image.new("RGB", (1376, 768), "white").save(image)
    output = tmp_path / "slide_017.layout.json"

    module.write_fallback_layout(image, output)

    layout = json.loads(output.read_text(encoding="utf-8"))
    assert layout["id"] == "slide_017"
    assert layout["image"] == "slide_017.png"
    assert layout["canvas"] == {"width": 1376, "height": 768}
    assert layout["metadata"]["fallback_reason"] == "layout_generation_failed"
    assert layout["objects"] == [
        {
            "type": "image",
            "name": "fallback_source_slide",
            "path": "slide_017.png",
            "bbox": [0, 0, 1376, 768],
            "replaceable": False,
            "source": "fallback",
        }
    ]
