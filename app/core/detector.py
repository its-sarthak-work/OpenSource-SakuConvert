from pathlib import Path
from PIL import Image, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt"}


def detect_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS: return "video"
    if suffix in AUDIO_EXTENSIONS: return "audio"
    if suffix in DOCUMENT_EXTENSIONS:
        if suffix == ".pdf": return "pdf"
        if suffix == ".docx": return "word"
        return "text"
    try:
        with Image.open(path) as image:
            if not image.format: raise UnidentifiedImageError(path)
            return "image"
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Unable to identify media: {path.name}") from exc


def detect_image(path: Path) -> str:
    try:
        with Image.open(path) as image:
            if not image.format: raise UnidentifiedImageError(path)
            return image.format.upper()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Unable to identify image: {path.name}") from exc
