from scripts.generate_layout_json import _normalize_polyline_points


def test_normalize_flat_polyline_points() -> None:
    layout = {
        "objects": [
            {
                "type": "polyline",
                "name": "trace",
                "points": [10, 20, 30, 40, 50, 60],
            }
        ]
    }

    _normalize_polyline_points(layout)

    assert layout["objects"][0]["points"] == [[10, 20], [30, 40], [50, 60]]
