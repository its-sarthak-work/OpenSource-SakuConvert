# SakuConvert v0.7 Document Engine

## PDF → Word

SakuConvert uses `pdf2docx` for local layout reconstruction rather than extracting all PDF text into plain paragraphs. The engine attempts to preserve positioned text, paragraph structure, tables and images.

Scanned/image-only PDFs are detected and rejected with a clear message rather than producing a misleading empty or badly reconstructed DOCX. OCR remains a separate local feature.

## Word → PDF

SakuConvert uses LibreOffice's headless Writer renderer when installed. This is the primary high-fidelity path because it performs real Word document pagination and rendering locally.

The converter launches LibreOffice with an isolated temporary user profile and a timeout. This prevents an existing LibreOffice session from hijacking the conversion and prevents an indefinite wait from blocking the application.

The generated PDF is reopened and validated before SakuConvert reports success.

## Unicode and the ₹ symbol

Word → PDF delegates font selection and glyph rendering to LibreOffice, so the result can preserve `₹` and other Unicode characters when the source document's fonts or installed fallback fonts contain those glyphs. SakuConvert does not replace unsupported characters with ASCII approximations.

PDF → Word relies on the source PDF's text/font information. A PDF that has converted its text into vector outlines or a scanned image cannot reliably provide editable Unicode text without OCR.

## Privacy

Both document conversions are local. LibreOffice and pdf2docx are local engines; SakuConvert does not send document contents to a SakuConvert backend.
