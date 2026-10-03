# Video Conversion — v0.4

SakuConvert v0.4 adds local video conversion through FFmpeg.

Supported output targets:
- MP4 (H.264 + AAC)
- MKV
- WebM (VP9 + Opus)
- MOV
- AVI
- GIF

The FFmpeg binary is supplied through the `imageio-ffmpeg` Python package.

## Privacy

Video conversion is local. The video is not uploaded to a SakuConvert server or a conversion API.

## Important behavior

SakuConvert does not automatically crop or resize video. Codec/container differences can affect quality or metadata, so future versions should expose more codec controls and stronger output validation.
