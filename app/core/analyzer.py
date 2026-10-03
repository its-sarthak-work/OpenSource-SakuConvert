from pathlib import Path
from PIL import Image

from app.core.models import AnalysisResult, ConversionWarning, ImageInfo


# Formats supported by the first image engine.
IMAGE_TARGETS = {
    "JPEG": "JPEG",
    "JPG": "JPEG",
    "PNG": "PNG",
    "WEBP": "WEBP",
    "BMP": "BMP",
    "TIFF": "TIFF",
    "GIF": "GIF",
}


def inspect_image(path: Path) -> ImageInfo:
    with Image.open(path) as image:
        exif = image.getexif()
        return ImageInfo(
            path=path,
            format=(image.format or "UNKNOWN").upper(),
            width=image.width,
            height=image.height,
            mode=image.mode,
            has_alpha=("A" in image.getbands()) or ("transparency" in image.info),
            animated=bool(getattr(image, "is_animated", False)),
            frame_count=int(getattr(image, "n_frames", 1)),
            file_size=path.stat().st_size,
            exif_present=bool(exif),
            icc_present=bool(image.info.get("icc_profile")),
            orientation=exif.get(274) if exif else None,
        )


def analyze_image(path: Path, target_format: str) -> AnalysisResult:
    source = inspect_image(path)
    target = target_format.upper().lstrip(".")

    if target == "JPG":
        target = "JPEG"

    result = AnalysisResult(source=source, target_format=target)

    if target not in IMAGE_TARGETS:
        result.can_convert = False
        result.warnings.append(
            ConversionWarning("warning", f"{target} is not supported by the current image engine.")
        )
        return result

    # Dimensions and aspect ratio are preserved by default.
    result.preserved.append(f"Resolution: {source.width} × {source.height}")
    result.preserved.append("Aspect ratio")

    if source.icc_present:
        result.preserved.append("ICC color profile")

    if source.exif_present:
        result.preserved.append("EXIF metadata where supported")

    if source.orientation is not None:
        result.preserved.append("Orientation metadata")

    if source.animated:
        if target not in {"GIF", "WEBP"}:
            result.warnings.append(
                ConversionWarning(
                    "warning",
                    f"This file contains {source.frame_count} frames. "
                    f"{target} conversion may not preserve animation."
                )
            )
        else:
            result.preserved.append("Animation frames where supported")

    if source.has_alpha and target in {"JPEG", "BMP"}:
        result.warnings.append(
            ConversionWarning(
                "warning",
                f"{target} does not support transparency. "
                "A background color will be required; SakuConvert will not silently crop or flatten it."
            )
        )

    if target == "JPEG":
        result.warnings.append(
            ConversionWarning(
                "info",
                "JPEG uses lossy compression. Some image information may be changed."
            )
        )

    if target == "GIF":
        result.warnings.append(
            ConversionWarning(
                "info",
                "GIF has limited color support. Colors may change during conversion."
            )
        )

    if source.format == target:
        result.warnings.append(
            ConversionWarning("info", "Source and target formats are the same.")
        )

    return result
