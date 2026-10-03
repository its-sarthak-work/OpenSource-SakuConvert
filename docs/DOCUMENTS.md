# Documents — v0.6

## PDF → Word
Uses `pypdf` to extract text from each PDF page and writes it to a `.docx` file with `python-docx`.

This is a **text extraction conversion**, not a promise of pixel-perfect PDF layout reproduction. PDFs with complex tables, positioned text, embedded images, forms, or scanned pages may not convert faithfully.

## Word → PDF
SakuConvert first looks for a local LibreOffice installation and uses its headless converter. If LibreOffice is unavailable, SakuConvert uses a conservative local text-layout fallback. It preserves document text but does not claim pixel-perfect Word layout reproduction.

No cloud document conversion is used by this feature.

## Image → Text
Uses local Tesseract OCR through `pytesseract`. Tesseract itself must be installed separately because bundling its language data into SakuConvert would substantially increase the installer size.

The image is processed locally and is not uploaded by SakuConvert.

## Text → Image
Uses Pillow to render a UTF-8 text file to a PNG image locally.
