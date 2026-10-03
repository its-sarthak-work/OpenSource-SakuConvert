from dataclasses import dataclass
from pathlib import Path

@dataclass
class ConversionJob:
    source: Path
    target_format: str
    output: Path | None = None
    status: str = "queued"
