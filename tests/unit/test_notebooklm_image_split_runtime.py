from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from typer.testing import CliRunner

from star_slide.cli import notebooklm as notebooklm_cli
from star_slide.cli.main import app
from star_slide.config import Settings
from star_slide.pipeline import codex_image_split, notebooklm_auto
from star_slide.vision_llm import image_split_client


def test_settings_accept_documented_vision_environment_names(monkeypatch) -> None:
    # Given: the public environment variable names documented for CLI agents
    monkeypatch.setenv("STAR_SLIDE_BASE_URL", "http://vision.example/v1")
    monkeypatch.setenv("STAR_SLIDE_MODEL", "vision-model")
    monkeypatch.setenv("STAR_SLIDE_API_KEY", "secret")

    # When: settings are parsed without a dotenv file
    settings = Settings(_env_file=None)

    # Then: web and internal pipeline defaults match the documented configuration
    assert settings.vision_base_url == "http://vision.example/v1"
    assert settings.vision_model == "vision-model"
    assert settings.vision_api_key == "secret"


def test_cli_accepts_legacy_vision_environment_aliases(tmp_path, monkeypatch) -> None:
    # Given: an existing deployment that still uses the legacy vision variable names
    input_path = tmp_path / "input.pptx"
    input_path.write_bytes(b"fixture")
    output_path = tmp_path / "output.pptx"
    captured: dict[str, Any] = {}

    def fake_convert(**kwargs: Any) -> notebooklm_auto.NotebookLmAutoResult:
        captured.update(kwargs)
        output_path.write_bytes(b"pptx")
        return notebooklm_auto.NotebookLmAutoResult(
            output=output_path,
            workdir=tmp_path / "work",
            selected_layout_dir=tmp_path / "layouts",
            report=tmp_path / "report.json",
            vector_pptx=output_path,
            hybrid_pptx=output_path,
            artifact_dir=tmp_path / "artifacts",
            montage=None,
        )

    monkeypatch.setattr(notebooklm_cli, "convert_notebooklm_auto", fake_convert)
    env = {
        "STAR_SLIDE_VISION_BASE_URL": "http://legacy.example/v1",
        "STAR_SLIDE_VISION_MODEL": "legacy-model",
        "STAR_SLIDE_VISION_API_KEY": "legacy-secret",
    }

    # When: the public CLI is invoked without explicit provider flags
    result = CliRunner().invoke(
        app,
        ["notebooklm", "run", str(input_path), "-o", str(output_path), "--quiet"],
        env=env,
    )

    # Then: the legacy aliases reach the same runtime options as the public names
    assert result.exit_code == 0
    options = captured["options"]
    assert options.base_url == "http://legacy.example/v1"
    assert options.model == "legacy-model"
    assert options.api_key == "legacy-secret"


def test_quiet_subprocess_command_does_not_leak_output(capfd) -> None:
    # Given: a successful child process that writes to both output streams
    command = [
        sys.executable,
        "-c",
        "import sys; print('stdout-noise'); print('stderr-noise', file=sys.stderr)",
    ]

    # When: the pipeline executes it in quiet mode
    notebooklm_auto.run_cmd(command, quiet=True)

    # Then: machine-readable CLI output remains uncontaminated
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_image_split_receives_timeout_and_cancel_callback(tmp_path, monkeypatch) -> None:
    # Given: an image-split conversion with a custom timeout and cancellation source
    input_image = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "white").save(input_image)
    output_path = tmp_path / "result.pptx"
    workdir = tmp_path / "work"
    captured: dict[str, Any] = {}

    def fake_convert_image_split_multi(**kwargs: Any) -> codex_image_split.ImageSplitResult:
        captured.update(kwargs)
        output_path.write_bytes(b"pptx")
        split_workdir = Path(kwargs["workdir"])
        split_workdir.mkdir(parents=True, exist_ok=True)
        clean_bg = split_workdir / "clean.png"
        Image.new("RGB", (32, 18), "white").save(clean_bg)
        text_layout = split_workdir / "text.json"
        object_layers = split_workdir / "layers.json"
        text_layout.write_text("{}", encoding="utf-8")
        object_layers.write_text("{}", encoding="utf-8")
        return codex_image_split.ImageSplitResult(
            output=output_path,
            workdir=split_workdir,
            text_layout_json=text_layout,
            clean_bg_png=clean_bg,
            object_layers_json=object_layers,
            elapsed_sec=0.1,
        )

    monkeypatch.setattr(
        codex_image_split,
        "convert_image_split_multi",
        fake_convert_image_split_multi,
    )
    cancelled = False

    def cancel() -> bool:
        return cancelled

    # When: the notebook pipeline delegates to image-split
    notebooklm_auto._convert_image_split(
        input_images=[input_image],
        input_path=tmp_path / "input.pptx",
        output_path=output_path,
        workdir=workdir,
        options=notebooklm_auto.NotebookLmAutoOptions(
            timeout_sec=37.0,
            reconstruction_mode="image_split",
            keep_intermediates=True,
        ),
        emit=lambda _message, _percent: None,
        check_cancel=lambda: None,
        cancel=cancel,
        pre_cleanup_hook=None,
        keep_intermediates=True,
    )

    # Then: the delegated runtime observes the same timeout and cancellation source
    assert captured["options"].vision_timeout_sec == 37.0
    assert captured["cancel"] is cancel


def test_remote_vision_endpoint_receives_embedded_image(tmp_path, monkeypatch) -> None:
    # Given: a remote OpenAI-compatible endpoint that cannot reach local loopback URLs
    image_path = tmp_path / "slide.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    captured: dict[str, Any] = {}

    def fake_post_json(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(image_split_client, "_post_json", fake_post_json)

    # When: image-split sends the slide to the remote endpoint
    image_split_client.call_vision_json(
        image_path,
        "analyze",
        base_url="https://api.openai.com/v1",
        model="vision-model",
        api_key="secret",
    )

    # Then: the request carries the image bytes instead of an unreachable 127.0.0.1 URL
    image_url = captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


def test_local_vision_endpoint_receives_temporary_http_url(tmp_path, monkeypatch) -> None:
    # Given: a loopback proxy that can fetch files from this process
    image_path = tmp_path / "slide.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    captured: dict[str, Any] = {}

    def fake_post_json(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(image_split_client, "_post_json", fake_post_json)

    # When: image-split sends the slide through the local proxy
    image_split_client.call_vision_json(
        image_path,
        "analyze",
        base_url="http://localhost:8300/v1",
        model="vision-model",
        api_key="secret",
    )

    # Then: the existing local URL transport remains available
    image_url = captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("http://127.0.0.1:")


def test_invalid_reconstruction_mode_fails_before_extraction(tmp_path, monkeypatch) -> None:
    # Given: a mistyped reconstruction mode that would otherwise fall through to auto mode
    input_path = tmp_path / "input.pptx"
    input_path.write_bytes(b"not-read")

    def unexpected_extraction(_input_path: Path, _image_dir: Path) -> list[Path]:
        pytest.fail("input extraction must not start for invalid options")

    monkeypatch.setattr(notebooklm_auto, "extract_embedded_images", unexpected_extraction)

    # When/Then: the public pipeline rejects the invalid boundary value immediately
    with pytest.raises(ValueError, match="reconstruction_mode"):
        notebooklm_auto.convert_notebooklm_auto(
            input_path=input_path,
            output_path=tmp_path / "output.pptx",
            workdir=tmp_path / "work",
            options=notebooklm_auto.NotebookLmAutoOptions(reconstruction_mode="image_splt"),
        )
