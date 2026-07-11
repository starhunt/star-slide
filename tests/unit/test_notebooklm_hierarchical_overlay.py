from pathlib import Path

from star_slide.pipeline import notebooklm_auto


def test_build_hybrid_layouts_enables_child_peeling_for_hierarchical_overlay(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run_cmd(cmd, **_kwargs):
        captured.append([str(item) for item in cmd])

    monkeypatch.setattr(notebooklm_auto, "run_cmd", fake_run_cmd)

    notebooklm_auto.build_hybrid_layouts(
        layout_dir=Path("layouts"),
        image_root=Path("images"),
        groups_dir=Path("groups"),
        sam_dir=None,
        out_dir=Path("out"),
        slide_count=2,
        editable_embedded_text=True,
        hierarchical_overlay=True,
    )

    assert captured
    cmd = captured[0]
    assert "--peel-child-objects" in cmd
    assert "--child-object-max-area-ratio" in cmd
    assert "0.25" in cmd


def test_build_hybrid_layouts_keeps_default_command_without_child_peeling(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run_cmd(cmd, **_kwargs):
        captured.append([str(item) for item in cmd])

    monkeypatch.setattr(notebooklm_auto, "run_cmd", fake_run_cmd)

    notebooklm_auto.build_hybrid_layouts(
        layout_dir=Path("layouts"),
        image_root=Path("images"),
        groups_dir=Path("groups"),
        sam_dir=None,
        out_dir=Path("out"),
        slide_count=1,
        editable_embedded_text=True,
    )

    cmd = captured[0]
    assert "--peel-child-objects" not in cmd
