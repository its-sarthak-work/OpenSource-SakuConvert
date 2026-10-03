from pathlib import Path
from PIL import Image


def inspect_image(path: Path) -> dict:
    with Image.open(path) as image:
        exif = image.getexif()
        return {
            "exif": exif,
            "icc_profile": image.info.get("icc_profile"),
            "orientation": exif.get(274) if exif else None,
        }
