# Architecture

SakuConvert uses Python/PySide6 for the desktop application and keeps conversion logic independent from the UI.

## Conversion pipeline

DETECT → ANALYZE → WARN → USER CONFIRMS → CONVERT → VALIDATE → REPORT CHANGES

The UI calls the core API. The core does not import or depend on UI widgets.

## Image engine v0.2

The first real engine uses Pillow for:

- JPEG
- PNG
- WebP
- GIF
- BMP
- TIFF

The engine preserves dimensions by default and never crops/resizes/stretches automatically.

Lossy or incompatible conversions generate warnings before conversion.

Native engines such as FFmpeg, LibreOffice, and archive tools will be added as separate adapters later.
