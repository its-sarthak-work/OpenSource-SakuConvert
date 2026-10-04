# SakuConvert v0.9.2

SakuConvert is a local-first, open-source Windows file converter. Normal conversion is performed on the user's computer. Online background removal is an explicitly separate feature that requires user confirmation.

## v0.7 document engine

- High-fidelity PDF → DOCX reconstruction with `pdf2docx`
- High-fidelity DOCX → PDF rendering with local LibreOffice
- Unicode-aware document rendering; no intentional `₹` → `?` substitution
- Output validation after document conversion
- Isolated LibreOffice profile and bounded timeout to prevent hung conversions
- Clear handling of scanned/image-only PDFs
- Existing image, video, audio, OCR and background-removal features remain available

### Install

Create/use the project's Python 3.12 virtual environment and run:

```powershell
..\.venv\Scripts\python.exe -m pip install -e .
..\.venv\Scripts\python.exe -m app.main
```

For high-fidelity Word → PDF, install LibreOffice locally. No cloud service is required.

## v0.9.1 UI and queue

- Full-screen frameless Windows UI with a Sakura-themed original background
- File/Remove/Settings/Help menu bar
- Persistent output-folder setting
- Sequential multi-file conversion queue
- Per-file elapsed timers and completed/failed states
- Privacy Center under Help
- Detailed About dialog
- Background-removal network warning and daily credit are shown when the feature is used


### v0.9.2 output-folder and queue polish

- First launch requires choosing an accessible, writable output folder.
- Saved output folders are validated at startup and before conversion.
- Inaccessible or unreachable folders show a clear error instead of failing silently.
- The output folder automatically opens after a successful conversion queue.
- The audio format dropdown explicitly styles its popup text for reliable visibility.

SakuConvert version: 0.9.5
