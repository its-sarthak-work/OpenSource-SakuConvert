from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImageInfo:
    path: Path
    format: str
    width: int
    height: int
    mode: str
    has_alpha: bool
    animated: bool
    frame_count: int
    file_size: int
    exif_present: bool
    icc_present: bool
    orientation: Any = None


@dataclass
class ConversionWarning:
    level: str  # "warning" or "info"
    message: str


@dataclass
class AnalysisResult:
    source: ImageInfo
    target_format: str
    warnings: list[ConversionWarning] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    can_convert: bool = True
