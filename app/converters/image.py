from pathlib import Path

from PIL import Image, ImageOps

from app.core.models import AnalysisResult


class ImageConversionError(RuntimeError):
    pass


def _flatten_for_jpeg(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, background)
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


def convert_image(
    source: Path,
    destination: Path,
    analysis: AnalysisResult,
    *,
    jpeg_quality: int = 95,
    background: tuple[int, int, int] | None = None,
) -> Path:
    """
    Convert an image while preserving dimensions by default.

    Important:
    - No resizing.
    - No cropping.
    - No stretching.
    - JPEG transparency requires an explicit background.
    """
    target = analysis.target_format.upper()
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(source) as original:
            image = original.copy()

            # Apply EXIF orientation only if the caller later chooses that policy.
            # For v0.2 we keep pixels untouched and preserve orientation metadata.
            exif = original.getexif()
            icc = original.info.get("icc_profile")

            save_kwargs = {}

            if exif:
                save_kwargs["exif"] = exif.tobytes()
            if icc:
                save_kwargs["icc_profile"] = icc

            if target == "JPEG":
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    if background is None:
                        raise ImageConversionError(
                            "This image has transparency. Choose a background color before converting to JPEG."
                        )
                    image = _flatten_for_jpeg(image, background)
                elif image.mode not in ("RGB", "L", "CMYK"):
                    image = image.convert("RGB")

                save_kwargs["quality"] = max(1, min(100, jpeg_quality))
                save_kwargs["optimize"] = True

            elif target == "WEBP":
                # Lossless is deliberately used by default to prioritize preservation.
                save_kwargs["lossless"] = True
                if image.mode == "P":
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")

            elif target == "PNG":
                if image.mode == "P" and "transparency" in image.info:
                    image = image.convert("RGBA")

            elif target == "GIF":
                # Pillow handles palette conversion. Animation handling will be expanded later.
                save_kwargs["save_all"] = getattr(original, "is_animated", False)

            image.save(destination, format=target, **save_kwargs)

    except ImageConversionError:
        raise
    except Exception as exc:
        raise ImageConversionError(f"Image conversion failed: {exc}") from exc

    return destination
