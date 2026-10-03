from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg


VIDEO_TARGETS = {
    "MP4": "mp4",
    "MKV": "mkv",
    "WEBM": "webm",
    "MOV": "mov",
    "AVI": "avi",
    "GIF": "gif",
}


class VideoConversionError(RuntimeError):
    pass


def _ffmpeg() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise VideoConversionError(
            "FFmpeg is not available. Reinstall SakuConvert's video dependencies."
        ) from exc


def inspect_video(path: Path) -> dict:
    ffmpeg = _ffmpeg()

    # FFmpeg's stderr is the most portable way to inspect a media file when
    # ffprobe is not shipped separately.
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i", str(path),
        "-f", "null",
        "-",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    text = proc.stderr

    # Basic metadata extraction without a second FFmpeg dependency.
    import re
    duration = None
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    width = height = None
    vm = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", text, re.S)
    if vm:
        width, height = int(vm.group(1)), int(vm.group(2))

    if "Video:" not in text:
        raise VideoConversionError(
            f"FFmpeg could not find a video stream in '{path.name}'."
        )

    return {
        "format": path.suffix.lower().lstrip(".").upper(),
        "duration": duration,
        "width": width,
        "height": height,
        "file_size": path.stat().st_size,
    }


def convert_video(
    source: Path,
    destination: Path,
    target_format: str,
    *,
    crf: int = 23,
) -> Path:
    target = target_format.upper().lstrip(".")
    if target not in VIDEO_TARGETS:
        raise VideoConversionError(f"Unsupported video target: {target}")

    _ = inspect_video(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()

    if target == "GIF":
        # GIF needs a palette for reasonable quality.
        filter_complex = (
            "[0:v]fps=15,split[s0][s1];"
            "[s0]palettegen=max_colors=256[p];"
            "[s1][p]paletteuse=dither=sierra2_4a"
        )
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-filter_complex", filter_complex,
            str(destination),
        ]
    elif target == "MP4":
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-c:v", "libx264", "-preset", "medium",
            "-crf", str(max(0, min(51, crf))),
            "-c:a", "aac", "-movflags", "+faststart",
            str(destination),
        ]
    elif target == "WEBM":
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-c:v", "libvpx-vp9", "-crf", str(max(0, min(63, crf))),
            "-b:v", "0", "-c:a", "libopus",
            str(destination),
        ]
    elif target == "MKV":
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-c:v", "libx264", "-crf", str(max(0, min(51, crf))),
            "-c:a", "aac",
            str(destination),
        ]
    elif target == "MOV":
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-c:v", "libx264", "-crf", str(max(0, min(51, crf))),
            "-c:a", "aac",
            str(destination),
        ]
    else:  # AVI
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-c:v", "mpeg4", "-q:v", "4",
            "-c:a", "mp3",
            str(destination),
        ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout)[-1500:]
        raise VideoConversionError(
            f"FFmpeg conversion failed.\n\n{detail}"
        )

    if not destination.exists() or destination.stat().st_size == 0:
        raise VideoConversionError("FFmpeg produced no output file.")

    return destination
