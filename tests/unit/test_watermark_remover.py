from pathlib import Path

from PIL import Image, ImageDraw

from star_slide.input.watermark_remover import remove_watermark_inplace


def test_remove_watermark_preserves_png_background_color(tmp_path: Path) -> None:
    # Given: a flat-color slide with a dark mark in the NotebookLM watermark region
    image_path = tmp_path / "slide.png"
    image = Image.new("RGB", (200, 100), (24, 48, 72))
    ImageDraw.Draw(image).rectangle((170, 85, 195, 98), fill=(255, 255, 255))
    image.save(image_path)

    # When: the fast watermark remover processes the slide
    remove_watermark_inplace(image_path)

    # Then: the watermark region is restored with the sampled RGB background
    with Image.open(image_path) as result:
        assert result.convert("RGB").getpixel((180, 95)) == (24, 48, 72)


def test_remove_watermark_preserves_jpeg_format(tmp_path: Path) -> None:
    # Given: a JPEG slide accepted by the image-split pipeline
    image_path = tmp_path / "slide.jpg"
    Image.new("RGB", (200, 100), (240, 240, 240)).save(image_path, quality=95)

    # When: the watermark remover overwrites the image
    remove_watermark_inplace(image_path)

    # Then: the output remains a readable JPEG
    with Image.open(image_path) as result:
        assert result.format == "JPEG"
