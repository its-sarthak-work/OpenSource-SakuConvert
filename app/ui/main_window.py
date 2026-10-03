from pathlib import Path

from pypdf import PdfReader
from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget
)

from app.background.api import BackgroundAPIError, remove_background_online
from app.background.credits import DAILY_LIMIT, mark_exhausted, record_success, remaining_today
from app.background.providers import get_provider
from app.converters.audio import AUDIO_TARGETS, AudioConversionError, convert_audio, inspect_audio
from app.converters.document import (
    DocumentConversionError, image_to_text, pdf_to_word, text_to_image, word_to_pdf, document_engine_status,
)
from app.converters.video import VIDEO_TARGETS, VideoConversionError, convert_video, inspect_video
from app.core.analyzer import analyze_image
from app.core.converter import convert
from app.core.detector import detect_image, detect_media_type

IMAGE_TARGETS = ["PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF", "HEIC", "HEIF"]
VIDEO_TARGETS_LIST = list(VIDEO_TARGETS.keys())
AUDIO_TARGETS_LIST = list(AUDIO_TARGETS.keys())
DOCUMENT_TARGETS = {
    "pdf": ["WORD (DOCX)"],
    "word": ["PDF"],
    "text": ["PNG IMAGE"],
}


class ConversionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class DropZone(QFrame):
    def __init__(self, on_files):
        super().__init__()
        self.on_files = on_files
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        layout = QVBoxLayout(self)
        title = QLabel("Drop files here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        sub = QLabel("or choose files from your computer")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browse = QPushButton("Browse Files")
        browse.clicked.connect(self.browse)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files")
        if files:
            self.on_files([Path(f) for f in files])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.on_files(paths)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SakuConvert")
        self.resize(1050, 800)
        self.current_files: list[Path] = []
        self.media_type: str | None = None
        self._worker_thread = None
        self._worker = None
        self._document_engines = document_engine_status()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        header = QLabel("🌸 SakuConvert")
        header.setStyleSheet("font-size: 30px; font-weight: 800;")
        tagline = QLabel("Convert locally. Keep your files yours.")

        self.drop_zone = DropZone(self.add_files)
        self.drop_zone.setMinimumHeight(180)

        self.files = QListWidget()
        self.files.setMinimumHeight(120)
        self.files.setMaximumHeight(250)
        self.files.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.files.setSpacing(4)
        self.files.itemSelectionChanged.connect(self.update_file_action_state)

        file_actions = QHBoxLayout()
        self.clear_files_button = QPushButton("Clear All")
        self.clear_files_button.clicked.connect(self.clear_files)
        file_actions.addWidget(self.clear_files_button)
        file_actions.addStretch()

        controls = QHBoxLayout()
        self.format_label = QLabel("Convert to:")
        self.format_box = QComboBox()
        self.format_box.currentTextChanged.connect(self.refresh_analysis)
        self.format_label.setVisible(False)
        self.format_box.setVisible(False)
        controls.addWidget(self.format_label)
        controls.addWidget(self.format_box)
        self.detected_label = QLabel("No file selected")
        self.detected_label.setStyleSheet("font-weight: 600; padding-left: 8px;")
        controls.addWidget(self.detected_label)
        controls.addStretch()

        self.remove_bg_button = QPushButton()
        self.remove_bg_button.clicked.connect(self.background_removal_info)
        controls.addWidget(self.remove_bg_button)
        self.credit_label = QLabel()
        controls.addWidget(self.credit_label)

        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-weight: 600; padding: 3px;")
        privacy = QLabel("🔒 Normal conversion: LOCAL  •  Online Background Removal is an explicit exception")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.convert_button = QPushButton("Convert")
        self.convert_button.clicked.connect(self.convert_selected)

        for w in (self.clear_files_button, self.convert_button):
            w.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(header)
        layout.addWidget(tagline)
        layout.addWidget(self.drop_zone)
        layout.addWidget(self.files)
        layout.addLayout(file_actions)
        layout.addLayout(controls)
        layout.addWidget(self.status_label)
        layout.addWidget(privacy)
        layout.addWidget(self.convert_button)

        self.setStyleSheet("""
            QMainWindow { background: #fffafc; }
            QLabel { color: #2d2529; }
            #DropZone { background: #ffffff; border: 1px dashed #e4a8bf; border-radius: 14px; }
            QPushButton { background: #e9a8c2; color: #2d2026; border: 1px solid #dfa0b9; border-radius: 8px; padding: 9px 15px; font-weight: 600; }
            QPushButton:hover { background: #efb7ce; }
            QPushButton:pressed { background: #df98b5; }
            QPushButton:disabled { background: #eee6e9; color: #968a8f; border-color: #e4dce0; }
            QPushButton#FileRemoveButton { background: transparent; color: #75666d; border: none; border-radius: 15px; font-size: 22px; font-weight: 400; padding: 0; }
            QPushButton#FileRemoveButton:hover { background: #f5e1e9; color: #5b4b53; }
            QPushButton#FileRemoveButton:pressed { background: #ecd0dc; }
            QComboBox { background: white; border: 1px solid #e3d9de; border-radius: 8px; padding: 8px; min-width: 120px; }
            QListWidget { background: white; border: 1px solid #e3d9de; border-radius: 12px; padding: 5px; }
            QListWidget::item { padding: 2px; border-radius: 8px; }
            QListWidget::item:selected { background: #f8dce7; color: #2d2026; }
            QLabel#FileNameLabel { color: #3a3035; padding: 2px 4px; }
        """)
        self.refresh_format_options()
        self.refresh_credit_ui()
        self.update_file_action_state()

    def update_file_action_state(self):
        has = bool(self.current_files)
        self.clear_files_button.setEnabled(has and self._worker_thread is None)

    def clear_files(self):
        if self._worker_thread is not None:
            return
        self.current_files.clear()
        self.files.clear()
        self.media_type = None
        self.detected_label.setText("No file selected")
        self.status_label.setText("Ready")
        self.refresh_format_options()
        self.update_file_action_state()

    def remove_file_at(self, index: int):
        if self._worker_thread is not None:
            return
        if index < 0 or index >= len(self.current_files):
            return
        self.current_files.pop(index)
        self.files.takeItem(index)
        self.rebuild_media_state()
        if self.files.count():
            self.files.setCurrentRow(min(index, self.files.count() - 1))
        else:
            self.status_label.setText("Ready")

    def add_files(self, paths):
        if self._worker_thread is not None:
            return
        valid = [p for p in paths if p.exists() and p.is_file()]
        if not valid:
            return
        # A new drop replaces the current selection. This keeps detection predictable.
        self.current_files = valid
        self.files.clear()
        for path in valid:
            try:
                kind = detect_media_type(path)
                if kind == "image":
                    label = f"{path.name}  •  {detect_image(path)}  •  {path.stat().st_size / 1024:.1f} KB"
                elif kind == "video":
                    label = f"{path.name}  •  VIDEO  •  {path.stat().st_size / (1024 * 1024):.1f} MB"
                elif kind == "audio":
                    label = f"{path.name}  •  AUDIO  •  {path.stat().st_size / (1024 * 1024):.1f} MB"
                else:
                    label = f"{path.name}  •  {kind.upper()}"
            except Exception:
                kind = "unknown"
                label = f"{path.name}  •  unsupported/unknown"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files.addItem(item)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 3, 4, 3)
            row_layout.setSpacing(8)

            remove = QPushButton("×")
            remove.setObjectName("FileRemoveButton")
            remove.setFixedSize(30, 30)
            remove.setToolTip(f"Remove {path.name}")
            remove.clicked.connect(lambda _checked=False, idx=self.files.count() - 1: self.remove_file_at(idx))

            name_label = QLabel(label)
            name_label.setObjectName("FileNameLabel")
            name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            name_label.setToolTip(str(path))

            row_layout.addWidget(remove)
            row_layout.addWidget(name_label, 1)
            self.files.setItemWidget(item, row)
        self.rebuild_media_state()
        if self.files.count():
            self.files.setCurrentRow(0)
        self.status_label.setText(f"Loaded {len(valid)} file{'s' if len(valid) != 1 else ''}")

    def rebuild_media_state(self):
        if not self.current_files:
            self.media_type = None
            self.detected_label.setText("No file selected")
            self.refresh_format_options()
            self.update_file_action_state()
            return
        types = []
        for path in self.current_files:
            try:
                types.append(detect_media_type(path))
            except ValueError:
                types.append("unknown")
        if any(t == "unknown" for t in types) or len(set(types)) != 1:
            self.media_type = None
            self.detected_label.setText("Mixed or unsupported file types")
            self.format_label.setVisible(False)
            self.format_box.setVisible(False)
            self.convert_button.setEnabled(False)
            self.update_file_action_state()
            return
        self.media_type = types[0]
        labels = {"image": "IMAGE", "video": "VIDEO", "audio": "AUDIO", "pdf": "PDF", "word": "WORD/DOCX", "text": "TEXT"}
        self.detected_label.setText(f"Detected: {labels.get(self.media_type, self.media_type.upper())}")
        self.refresh_format_options()
        self.update_file_action_state()

    def refresh_format_options(self):
        self.format_box.blockSignals(True)
        self.format_box.clear()
        if self.media_type == "image":
            self.format_box.addItems(IMAGE_TARGETS + ["TEXT (OCR)"])
        elif self.media_type == "video":
            self.format_box.addItems(VIDEO_TARGETS_LIST)
        elif self.media_type == "audio":
            self.format_box.addItems(AUDIO_TARGETS_LIST)
        elif self.media_type in DOCUMENT_TARGETS:
            self.format_box.addItems(DOCUMENT_TARGETS[self.media_type])
        else:
            self.format_label.setVisible(False)
            self.format_box.setVisible(False)
            self.format_box.blockSignals(False)
            self.convert_button.setEnabled(False)
            self.refresh_credit_ui()
            return
        self.format_label.setVisible(True)
        self.format_box.setVisible(True)
        self.format_box.blockSignals(False)
        self.refresh_analysis()
        self.refresh_credit_ui()

    def refresh_analysis(self):
        """Refresh only the compact UI state; no large preview panel is used."""
        if not self.current_files or not self.media_type or not self.format_box.currentText():
            self.convert_button.setText("Convert")
            self.convert_button.setEnabled(False)
            self.status_label.setText("Ready")
            return

        target = self.format_box.currentText()
        labels = {
            "WORD (DOCX)": "Convert to Word",
            "PDF": "Convert to PDF",
            "TEXT (OCR)": "Extract Text (OCR)",
            "PNG IMAGE": "Convert to PNG",
        }
        action = labels.get(target, f"Convert to {target}")
        self.convert_button.setText(action)

        # Lightweight capability/status information only. Heavy inspection is
        # intentionally kept out of the UI refresh path.
        if self.media_type == "pdf":
            if self._document_engines["pdf_to_word"]:
                self.status_label.setText("PDF detected • Local PDF → Word engine ready")
            else:
                self.status_label.setText("PDF detected • PDF → Word engine is not installed")
                self.convert_button.setEnabled(False)
                return
        elif self.media_type == "word":
            if self._document_engines["word_to_pdf"]:
                if self._document_engines.get("word_to_pdf_word"):
                    self.status_label.setText("Word document detected • Microsoft Word local renderer ready")
                else:
                    self.status_label.setText("Word document detected • Local LibreOffice renderer ready")
            else:
                self.status_label.setText("Word document detected • Install Microsoft Word or LibreOffice for Word → PDF")
                self.convert_button.setEnabled(False)
                return
        elif self.media_type == "image" and target == "TEXT (OCR)":
            self.status_label.setText("Image detected • Local OCR selected")
        else:
            self.status_label.setText(f"Ready • {len(self.current_files)} file{'s' if len(self.current_files) != 1 else ''} selected")

        self.convert_button.setEnabled(self._worker_thread is None)

    def _start_worker(self, fn, success_title, success_message):
        self.convert_button.setEnabled(False)
        self.clear_files_button.setEnabled(False)
        self.remove_bg_button.setEnabled(False)
        self.status_label.setText("Converting locally…")
        self.convert_button.setText("Converting…")
        self._worker_thread = QThread(self)
        self._worker = ConversionWorker(fn)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        # Stop the worker thread before showing any modal dialog. This prevents
        # the UI from appearing stuck while a QMessageBox is open.
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.finished.connect(lambda output: self._worker_done(output, success_title, success_message))
        self._worker.failed.connect(self._worker_failed)
        self._worker_thread.finished.connect(self._worker_cleanup)
        self._worker_thread.start()

    def _worker_done(self, output, title, message):
        self.status_label.setText("Conversion complete")
        QMessageBox.information(self, title, message.format(output=Path(output)))

    def _worker_failed(self, message):
        self.status_label.setText("Conversion failed")
        QMessageBox.critical(self, "Conversion failed", message)

    def _worker_cleanup(self):
        self._worker = None
        self._worker_thread = None
        self.refresh_credit_ui()
        self.refresh_analysis()
        self.update_file_action_state()

    def convert_selected(self):
        if not self.current_files or not self.media_type or not self.format_box.currentText() or self._worker_thread is not None:
            return
        source = self.current_files[0]
        target = self.format_box.currentText()

        ext_map = {"WORD (DOCX)": "docx", "TEXT (OCR)": "txt", "PNG IMAGE": "png", "JPEG": "jpg"}
        ext = ext_map.get(target, target.lower())
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save converted file", str(source.with_suffix("." + ext)), f"{target} (*.{ext})"
        )
        if not destination:
            return
        dest = Path(destination)

        if self.media_type == "image" and target == "TEXT (OCR)":
            self._start_worker(lambda: image_to_text(source, dest), "Image → Text complete", "✓ OCR complete\n\nSaved: {output}\n\nThe image was processed locally.")
            return
        if self.media_type == "image":
            try:
                result = analyze_image(source, target)
            except Exception as exc:
                QMessageBox.critical(self, "Analysis failed", str(exc)); return
            warnings = [w.message for w in result.warnings if w.level == "warning"]
            if warnings:
                answer = QMessageBox.warning(self, "Review conversion warnings", "\n".join(f"• {w}" for w in warnings) + "\n\nContinue?", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Ok:
                    return
            if result.source.has_alpha and target in {"JPEG", "BMP"}:
                QMessageBox.information(self, "Transparency needs a background", "This target cannot store transparency. SakuConvert will not silently choose a background color. Please choose a target that supports transparency.")
                return
            self._start_worker(lambda: convert(source, dest, target)[0], "Image conversion complete", "✓ Conversion complete\n\nSaved: {output}\n\nNo automatic crop or resize was performed.")
            return
        if self.media_type == "video":
            self._start_worker(lambda: convert_video(source, dest, target), "Video conversion complete", "✓ Video conversion complete\n\nSaved: {output}\n\nProcessing was local.")
            return
        if self.media_type == "audio":
            self._start_worker(lambda: convert_audio(source, dest, target), "Audio conversion complete", "✓ Audio conversion complete\n\nSaved: {output}\n\nProcessing was local.")
            return
        if self.media_type == "pdf":
            self._start_worker(lambda: pdf_to_word(source, dest), "PDF → Word complete", "✓ High-fidelity PDF → Word conversion complete\n\nSaved: {output}\n\nProcessing was local. Layout reconstruction was performed by the document engine.")
            return
        if self.media_type == "word":
            self._start_worker(lambda: word_to_pdf(source, dest), "Word → PDF complete", "✓ High-fidelity Word → PDF conversion complete\n\nSaved: {output}\n\nLibreOffice rendered the document locally; no upload was used.")
            return
        if self.media_type == "text":
            self._start_worker(lambda: text_to_image(source, dest), "Text → Image complete", "✓ Text → Image complete\n\nSaved: {output}\n\nProcessing was local.")

    def refresh_credit_ui(self):
        left = remaining_today()
        self.credit_label.setText(f"BG removal: {left}/{DAILY_LIMIT}")
        enabled = self.media_type == "image" and bool(self.current_files) and left > 0 and self._worker_thread is None
        self.remove_bg_button.setEnabled(enabled)
        self.remove_bg_button.setText("✦ Remove Background" if left > 0 else "✦ Background Removal — 0/10 • Tomorrow")

    def background_removal_info(self):
        left = remaining_today()
        if not self.current_files or self.media_type != "image" or left <= 0:
            self.refresh_credit_ui(); return
        source = self.current_files[0]
        provider = get_provider("bgninja")
        answer = QMessageBox.warning(
            self, "Online background removal",
            f"⚠ This feature requires Internet access.\n\nYour image will be uploaded to {provider.name}.\n\nNormal conversion remains local.\n\nSakuConvert credits: {left}/{DAILY_LIMIT} remaining.\nProvider limit: 10 requests/day per IP.\n\nContinue?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Save background-removed image", str(source.with_name(source.stem + "_no_bg.png")), "PNG (*.png)")
        if not destination:
            return
        self.remove_bg_button.setEnabled(False)
        self.status_label.setText("Uploading image for background removal…")
        try:
            output = remove_background_online(source, Path(destination), provider_id="bgninja")
            record_success()
        except BackgroundAPIError as exc:
            if exc.daily_limit_reached:
                mark_exhausted()
            QMessageBox.critical(self, "Background removal failed", str(exc))
            return
        finally:
            self.refresh_credit_ui()
        left = remaining_today()
        self.status_label.setText("Background removal complete")
        QMessageBox.information(self, "Background removal complete", f"✓ Done\n\nSaved: {Path(output).name}\n\nLeft credit: {left}/{DAILY_LIMIT}")
