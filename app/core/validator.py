from pathlib import Path
from PIL import Image


def validate_image_output(
    output: Path,
    *,
    expected_width: int,
    expected_height: int,
) -> tuple[bool, list[str]]:
    issues: list[str] = []

    if not output.exists() or output.stat().st_size == 0:
        return False, ["Output file was not created correctly."]

    try:
        with Image.open(output) as image:
            if image.width != expected_width or image.height != expected_height:
                issues.append(
                    f"Resolution changed: expected {expected_width} × {expected_height}, "
                    f"got {image.width} × {image.height}."
                )
            image.verify()
    except Exception as exc:
        issues.append(f"Output image failed validation: {exc}")

    return not issues, issues
