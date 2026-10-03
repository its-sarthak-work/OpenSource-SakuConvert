from pathlib import Path

from app.converters.image import convert_image
from app.core.analyzer import analyze_image
from app.core.validator import validate_image_output


class ConversionError(RuntimeError):
    pass


def convert(source: Path, destination: Path, target_format: str, **options) -> tuple[Path, list[str]]:
    analysis = analyze_image(source, target_format)

    if not analysis.can_convert:
        raise ConversionError("Conversion is not supported.")

    output = convert_image(
        source,
        destination,
        analysis,
        jpeg_quality=options.get("jpeg_quality", 95),
        background=options.get("background"),
    )

    valid, issues = validate_image_output(
        output,
        expected_width=analysis.source.width,
        expected_height=analysis.source.height,
    )

    if not valid:
        raise ConversionError("Output validation failed: " + " | ".join(issues))

    return output, issues
