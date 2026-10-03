# SakuConvert v0.7.1

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
