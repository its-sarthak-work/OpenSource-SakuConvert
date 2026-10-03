from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

AUDIO_TARGETS = {
    "MP3": "mp3",
    "WAV": "wav",
    "M4A": "m4a",
    "FLAC": "flac",
    "OGG": "ogg",
    "OPUS": "opus",
    "AAC": "aac",
}


class AudioConversionError(RuntimeError):
    pass


def _ffmpeg() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise AudioConversionError("FFmpeg is not available.") from exc


def inspect_audio(path: Path) -> dict:
    ffmpeg = _ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = proc.stderr
    import re
    duration = None
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    if m:
        duration = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
    if "Audio:" not in text:
        raise AudioConversionError(f"No audio stream found in '{path.name}'.")
    return {
        "format": path.suffix.lower().lstrip(".").upper(),
        "duration": duration,
        "file_size": path.stat().st_size,
    }


def convert_audio(source: Path, destination: Path, target_format: str) -> Path:
    target = target_format.upper().lstrip(".")
    if target not in AUDIO_TARGETS:
        raise AudioConversionError(f"Unsupported audio target: {target}")

    inspect_audio(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()

    # Use broadly compatible codecs for the selected container.
    codec_args = {
        "MP3": ["-c:a", "libmp3lame", "-q:a", "2"],
        "WAV": ["-c:a", "pcm_s16le"],
        "M4A": ["-c:a", "aac", "-b:a", "256k"],
        "FLAC": ["-c:a", "flac"],
        "OGG": ["-c:a", "libvorbis", "-q:a", "5"],
        "OPUS": ["-c:a", "libopus", "-b:a", "160k"],
        "AAC": ["-c:a", "aac", "-b:a", "256k"],
    }

    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-vn", *codec_args[target], str(destination)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout)[-1500:]
        raise AudioConversionError(f"FFmpeg audio conversion failed.\n\n{detail}")
    if not destination.exists() or destination.stat().st_size == 0:
        raise AudioConversionError("FFmpeg produced no output file.")
    return destination
