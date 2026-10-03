from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from docx import Document
import pytesseract


class DocumentConversionError(RuntimeError):
    pass


def _find_soffice() -> str | None:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _find_word() -> bool:
    """Return whether Microsoft Word automation is available on Windows."""
    if os.name != "nt":
        return False
    try:
        import win32com.client  # noqa: F401
        # DispatchEx is used only as a capability probe; it starts an isolated
        # Word process which is immediately closed.
        app = win32com.client.DispatchEx("Word.Application")
        app.Quit()
        return True
    except Exception:
        return False


def document_engine_status() -> dict[str, bool]:
    """Return availability of the high-fidelity local document engines."""
    try:
        from pdf2docx import Converter as _Converter  # noqa: F401
        pdf_to_word_available = True
    except ImportError:
        pdf_to_word_available = False
    word_available = _find_word()
    libreoffice_available = _find_soffice() is not None
    return {
        "pdf_to_word": pdf_to_word_available,
        "word_to_pdf": word_available or libreoffice_available,
        "word_to_pdf_word": word_available,
        "word_to_pdf_libreoffice": libreoffice_available,
    }


def _validate_docx(path: Path) -> None:
    try:
        doc = Document(str(path))
        # Force parsing of paragraphs/tables so a corrupt ZIP/XML is caught.
        _ = len(doc.paragraphs) + len(doc.tables)
    except Exception as exc:
        raise DocumentConversionError(
            f"The generated Word document failed validation: {exc}"
        ) from exc


def _validate_pdf(path: Path) -> None:
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            raise ValueError("the PDF contains no pages")
    except Exception as exc:
        raise DocumentConversionError(
            f"The generated PDF failed validation: {exc}"
        ) from exc


def pdf_to_word(source: Path, destination: Path) -> Path:
    """High-fidelity local PDF → DOCX reconstruction using pdf2docx.

    This preserves positioned text, paragraphs, tables and images much better
    than plain text extraction. Scanned/image-only PDFs still require OCR and
    are reported clearly instead of silently producing an empty document.
    """
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise DocumentConversionError(
            "The high-fidelity PDF → Word engine is not installed. "
            "Run: python -m pip install -e ."
        ) from exc

    try:
        reader = PdfReader(str(source))
    except Exception as exc:
        raise DocumentConversionError(f"Could not open PDF: {exc}") from exc

    if not reader.pages:
        raise DocumentConversionError("The PDF contains no pages.")

    # A quick text check lets us distinguish a normal PDF from an image-only
    # scan. We do not pretend that layout-preserving PDF→DOCX can OCR a scan.
    text_sample = "".join((page.extract_text() or "") for page in reader.pages[:3]).strip()
    if not text_sample:
        raise DocumentConversionError(
            "This PDF appears to be scanned/image-only. PDF → Word cannot preserve "
            "its layout reliably without OCR. Use Image → Text for local OCR first, "
            "or use an OCR-capable document workflow."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_output = destination.with_name(destination.stem + ".saku-tmp.docx")
    if temp_output.exists():
        temp_output.unlink()

    converter = None
    try:
        converter = Converter(str(source))
        converter.convert(str(temp_output), start=0, end=None)
    except Exception as exc:
        raise DocumentConversionError(
            "PDF → Word reconstruction failed. The PDF may contain a layout or "
            f"feature the converter cannot reproduce. Details: {exc}"
        ) from exc
    finally:
        if converter is not None:
            try:
                converter.close()
            except Exception:
                pass

    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise DocumentConversionError("The PDF converter produced no Word document.")

    try:
        _validate_docx(temp_output)
        if destination.exists():
            destination.unlink()
        temp_output.replace(destination)
    except Exception:
        temp_output.unlink(missing_ok=True)
        raise

    return destination


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _word_com_to_pdf(source: Path, destination: Path) -> Path:
    """Render DOCX with the locally installed Microsoft Word application.

    This is the preferred Windows renderer when Word is installed because the
    document is paginated by the same engine that authored the DOCX.
    """
    if os.name != "nt":
        raise DocumentConversionError("Microsoft Word automation is Windows-only.")
    try:
        import win32com.client
    except ImportError as exc:
        raise DocumentConversionError(
            "Microsoft Word automation support is not installed. Run the SakuConvert dependency install first."
        ) from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(
            str(source.resolve()),
            ReadOnly=True,
            AddToRecentFiles=False,
            ConfirmConversions=False,
            Visible=False,
        )
        # wdExportFormatPDF = 17
        doc.ExportAsFixedFormat(
            OutputFileName=str(destination.resolve()),
            ExportFormat=17,
            OpenAfterExport=False,
            OptimizeFor=0,
            Range=0,
            Item=0,
            IncludeDocProps=True,
            KeepIRM=True,
            CreateBookmarks=1,
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
    except Exception as exc:
        raise DocumentConversionError(f"Microsoft Word could not render the document: {exc}") from exc
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass

    if not destination.exists() or destination.stat().st_size == 0:
        raise DocumentConversionError("Microsoft Word produced no PDF output.")
    _validate_pdf(destination)
    return destination


def word_to_pdf(source: Path, destination: Path, timeout: int = 180) -> Path:
    """High-fidelity local DOCX → PDF using LibreOffice's document renderer.

    LibreOffice runs with an isolated temporary profile and output directory.
    This prevents a running personal LibreOffice instance or an existing output
    file from interfering with conversion. A hard timeout prevents indefinite
    waits and the generated PDF is validated before it is moved into place.
    """
    # On Windows, prefer Microsoft Word when available for maximum DOCX fidelity.
    if _find_word():
        return _word_com_to_pdf(source, destination)

    soffice = _find_soffice()
    if not soffice:
        raise DocumentConversionError(
            "High-fidelity Word → PDF requires LibreOffice installed locally. "
            "Install LibreOffice, then restart SakuConvert. No file is uploaded."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sakuconvert-lo-") as temp_root:
        root = Path(temp_root)
        profile_dir = root / "profile"
        output_dir = root / "output"
        output_dir.mkdir()
        profile_url = _file_url(profile_dir)

        command = [
            soffice,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile_url}",
            "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", str(output_dir),
            str(source),
        ]

        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError(
                f"LibreOffice did not finish within {timeout} seconds. "
                "The conversion was stopped to keep SakuConvert responsive."
            ) from exc
        except OSError as exc:
            raise DocumentConversionError(f"Could not start LibreOffice: {exc}") from exc

        produced = output_dir / f"{source.stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            details = (proc.stderr or proc.stdout or "No LibreOffice error details.").strip()
            raise DocumentConversionError(
                "LibreOffice could not convert the Word document. "
                f"Details: {details[-1800:]}"
            )

        try:
            _validate_pdf(produced)
        except DocumentConversionError:
            raise

        try:
            if destination.exists():
                destination.unlink()
            shutil.move(str(produced), str(destination))
        except OSError as exc:
            raise DocumentConversionError(
                f"The PDF was rendered successfully but could not be saved: {exc}"
            ) from exc

    return destination


def image_to_text(source: Path, destination: Path, language: str = "eng") -> Path:
    try:
        with Image.open(source) as image:
            image = image.convert("RGB")
            text = pytesseract.image_to_string(image, lang=language)
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentConversionError(
            "Local OCR requires Tesseract OCR. Install Tesseract and make sure "
            "tesseract.exe is on PATH, then restart SakuConvert. No image is uploaded."
        ) from exc
    except Exception as exc:
        raise DocumentConversionError(f"OCR failed: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def _font(size: int):
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\NotoSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def text_to_image(source: Path, destination: Path) -> Path:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines() or [""]
    font = _font(30)
    padding = 40
    line_height = 42
    width = 1400
    height = max(100, padding * 2 + line_height * len(lines))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y = padding
    for line in lines:
        chunks = [line[i:i + 80] for i in range(0, max(1, len(line)), 80)] or [""]
        for chunk in chunks:
            draw.text((padding, y), chunk, fill="black", font=font)
            y += line_height
    image = image.crop((0, 0, width, min(y + padding, height)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(destination), format="PNG")
    return destination
