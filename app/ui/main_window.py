from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSettings, QSize, QThread, QTimer, Qt,
    QObject, Signal, QUrl,
)
from PySide6.QtGui import QAction, QDesktopServices, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMenuBar, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.background.api import BackgroundAPIError, remove_background_online
from app.background.credits import DAILY_LIMIT, mark_exhausted, record_success, remaining_today
from app.background.providers import get_provider
from app.converters.audio import AUDIO_TARGETS, convert_audio
from app.converters.document import (
    image_to_text, pdf_to_word, text_to_image, word_to_pdf, document_engine_status,
)
from app.converters.video import VIDEO_TARGETS, convert_video
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
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        paths = [
            Path(u.toLocalFile())
            for u in event.mimeData().urls()
            if u.isLocalFile()
        ]
        if paths:
            self.on_files(paths)


class FileRow(QWidget):
    """A queue row: remove button, file name, status and elapsed timer."""

    def __init__(self, text: str, on_remove):
        super().__init__()
        self._started_at = None

        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("FileRemove")
        self.remove_button.setFixedSize(32, 32)
        self.remove_button.setToolTip("Remove this file")
        self.remove_button.clicked.connect(on_remove)

        self.name_label = QLabel(text)
        self.name_label.setObjectName("FileName")
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.name_label.setToolTip(text)

        self.status = QLabel("Waiting")
        self.status.setObjectName("FileStatus")
        self.status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.timer = QLabel("00:00")
        self.timer.setObjectName("FileTimer")
        self.timer.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(10)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.timer)

    def _refresh_style(self):
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def waiting(self):
        self._started_at = None
        self.status.setObjectName("FileStatus")
        self.status.setText("Waiting")
        self.timer.setText("00:00")
        self._refresh_style()

    def start(self):
        self._started_at = time.monotonic()
        self.status.setObjectName("FileStatusActive")
        self.status.setText("Converting…")
        self.update_timer()
        self._refresh_style()

    def update_timer(self):
        if self._started_at is None:
            return
        elapsed = int(time.monotonic() - self._started_at)
        self.timer.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def complete(self):
        elapsed = self.timer.text()
        self._started_at = None
        self.status.setObjectName("FileStatusDone")
        self.status.setText("✓ Completed")
        self.timer.setText(elapsed)
        self._refresh_style()

    def fail(self):
        elapsed = self.timer.text()
        self._started_at = None
        self.status.setObjectName("FileStatusFailed")
        self.status.setText("⚠ Failed")
        self.timer.setText(elapsed)
        self._refresh_style()


class TitleBar(QWidget):
    """Custom frameless title bar with native-like window controls."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._drag_offset = None
        self.setObjectName("TitleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 5, 8, 5)
        layout.setSpacing(5)

        mark = QLabel()
        mark.setObjectName("TitleMark")
        mark.setFixedSize(30, 30)
        mark.setStyleSheet("background: transparent; border: none;")
        logo = QPixmap("app/ui/sakuro_logo.png")
        if not logo.isNull():
            mark.setPixmap(logo.scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        name = QLabel("SakuConvert")
        name.setObjectName("TitleName")
        layout.addWidget(mark)
        layout.addWidget(name)
        layout.addSpacing(14)
        self.menu_holder = QWidget()
        self.menu_layout = QHBoxLayout(self.menu_holder)
        self.menu_layout.setContentsMargins(0, 0, 0, 0)
        self.menu_layout.setSpacing(0)
        layout.addWidget(self.menu_holder, 1)

        self.min_button = QPushButton("—")
        self.max_button = QPushButton("□")
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("CloseWindowButton")
        for button in (self.min_button, self.max_button):
            button.setObjectName("WindowButton")
            button.setFixedSize(42, 32)
            layout.addWidget(button)
        layout.addWidget(self.close_button)

        self.min_button.clicked.connect(self.window.showMinimized)
        self.max_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self.window.close)

    def set_menu_bar(self, menu_bar):
        self.menu_layout.addWidget(menu_bar)

    def toggle_maximize(self):
        if self.window.isMaximized():
            self.window.show_fitted()
        else:
            self.window.showMaximized()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.window.isMaximized():
                self.window.show_fitted()
            self.window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SakuConvert")
        self.setMinimumSize(900, 680)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        self.current_files: list[Path] = []
        self.media_type: str | None = None
        self._worker_thread = None
        self._worker = None
        self._queue_index = 0
        self._queue_success = 0
        self._queue_failed = 0
        self._output_folder = Path.home() / "Downloads" / "SakuConvert"
        self._output_folder_ready = False
        self._document_engines = document_engine_status()
        self.settings = QSettings("SakuConvert", "SakuConvert")
        self.theme = str(self.settings.value("theme", "light")).lower()
        if self.theme not in {"light", "dark", "system"}:
            self.theme = "light"

        self._build_menu()

        central = QWidget()
        central.setObjectName("MainSurface")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(34, 26, 34, 42)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header = QLabel("SakuConvert")
        header.setObjectName("AppTitle")
        header_row.addWidget(header)
        header_row.addStretch()

        self.output_badge = QLabel()
        self.output_badge.setObjectName("OutputBadge")
        header_row.addWidget(self.output_badge)

        tagline = QLabel("Convert locally. Keep your files yours.")
        tagline.setObjectName("Tagline")

        self.drop_zone = DropZone(self.add_files)
        self.drop_zone.setMinimumHeight(155)

        self.files = QListWidget()
        self.files.setMinimumHeight(100)
        self.files.setMaximumHeight(280)
        self.files.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )

        controls = QHBoxLayout()

        self.format_label = QLabel("Convert to:")
        self.format_box = QComboBox()
        self.format_box.currentTextChanged.connect(self.refresh_analysis)
        self.format_label.hide()
        self.format_box.hide()
        controls.addWidget(self.format_label)
        controls.addWidget(self.format_box)

        self.detected_label = QLabel("No file selected")
        self.detected_label.setObjectName("DetectedLabel")
        controls.addWidget(self.detected_label)
        controls.addStretch()

        self.remove_bg_button = QPushButton("✦ Remove Background")
        self.remove_bg_button.clicked.connect(self.background_removal_info)
        controls.addWidget(self.remove_bg_button)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.convert_button = QPushButton("Choose a file to convert")
        self.convert_button.setObjectName("ConvertButton")
        self.convert_button.clicked.connect(self.convert_selected)

        layout.addLayout(header_row)
        layout.addWidget(tagline)
        layout.addWidget(self.drop_zone)
        layout.addWidget(self.files)
        layout.addLayout(controls)
        layout.addWidget(self.status_label)
        layout.addWidget(self.convert_button)

        self.setStyleSheet("""
            QMainWindow { background: #f8edf2; }
            QWidget#MainSurface {
                background-color: rgba(255, 250, 252, 238);
                background-image: url(app/ui/sakura_ambient.png);
                background-position: center;
                background-repeat: no-repeat;
            }
            QWidget#TopChrome {
                background: rgba(255, 250, 252, 248);
                border-bottom: 1px solid #e7d9df;
            }
            QWidget#TitleBar {
                background: rgba(255, 250, 252, 248);
            }
            QLabel#TitleMark {
                background: transparent;
                border: none;
            }
            QLabel#TitleName {
                color: #2b2528;
                font-size: 17px;
                font-weight: 900;
            }
            QPushButton#WindowButton {
                background: transparent;
                color: #4f4349;
                border: none;
                border-radius: 6px;
                padding: 0;
                font-size: 19px;
                font-weight: 700;
            }
            QPushButton#WindowButton:hover { background: #f3e1e8; }
            QPushButton#WindowButton:pressed { background: #e9cbd7; }
            QPushButton#CloseWindowButton:hover {
                background: #d96888; color: #ffffff;
            }
            QPushButton#CloseWindowButton:pressed {
                background: #c45575; color: #ffffff;
            }

            QMenuBar {
                background: transparent;
                color: #2b2528;
                border: none;
                padding: 3px 6px;
                font-size: 16px;
                font-weight: 800;
            }
            QMenuBar::item {
                padding: 9px 15px;
                border-radius: 7px;
            }
            QMenuBar::item:selected { background: #f7e1e8; }

            QMenu {
                background: #ffffff;
                color: #2b2528;
                border: 1px solid #e4d9de;
                padding: 6px;
                font-size: 15px;
                font-weight: 700;
            }
            QMenu::item {
                padding: 9px 34px 9px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected { background: #f8e3ea; }

            QLabel {
                color: #2b2528;
                font-family: "Segoe UI";
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#AppTitle {
                font-size: 40px;
                font-weight: 900;
            }
            QLabel#Tagline {
                font-size: 18px;
                font-weight: 700;
                color: #705e67;
            }
            QLabel#OutputBadge {
                background: rgba(255,255,255,225);
                border: 1px solid #e3cbd5;
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLabel#DetectedLabel {
                font-size: 16px;
                font-weight: 800;
                padding-left: 8px;
            }
            QLabel#StatusLabel {
                font-size: 16px;
                font-weight: 800;
                padding: 5px;
            }
            QLabel#DropTitle {
                font-size: 29px;
                font-weight: 900;
            }

            #DropZone {
                background: rgba(255,255,255,245);
                border: 2px dashed #df9fba;
                border-radius: 16px;
            }

            QPushButton {
                background: #e8a8c0;
                color: #2a2024;
                border: 1px solid #df9bb5;
                border-radius: 9px;
                padding: 11px 18px;
                font-weight: 800;
                font-size: 15px;
            }
            QPushButton:hover { background: #edb6cb; }
            QPushButton:pressed { background: #df98b2; }
            QPushButton:disabled {
                background: #eee4e8;
                color: #95858c;
                border-color: #e5dadd;
            }
            QPushButton#ConvertButton {
                min-height: 48px;
                font-size: 17px;
                font-weight: 900;
            }
            QPushButton#FileRemove {
                background: transparent;
                border: none;
                color: #9b596f;
                font-size: 24px;
                font-weight: 500;
                padding: 0;
            }
            QPushButton#FileRemove:hover {
                background: #f8e1e9;
                color: #7d4056;
                border-radius: 15px;
            }

            QComboBox {
                background: #ffffff;
                color: #2b2528;
                border: 1px solid #dfd3d8;
                border-radius: 9px;
                padding: 10px 12px;
                min-width: 170px;
                font-size: 16px;
                font-weight: 800;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #2b2528;
                selection-background-color: #f7dce6;
                selection-color: #2b2528;
                border: 1px solid #dfd3d8;
                padding: 4px;
                font-size: 16px;
                font-weight: 800;
            }

            QListWidget {
                background: rgba(255,255,255,245);
                border: 1px solid #e4d9de;
                border-radius: 14px;
                padding: 6px;
                font-size: 15px;
            }
            QListWidget::item { padding: 0; border-radius: 9px; }
            QListWidget::item:selected {
                background: #f9e2eb;
                color: #2a2024;
            }

            QLabel#FileName {
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#FileStatus {
                color: #76666d;
                font-size: 14px;
                font-weight: 800;
            }
            QLabel#FileStatusActive {
                color: #9a5670;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#FileStatusDone {
                color: #4e7b60;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#FileStatusFailed {
                color: #a64f57;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#FileTimer {
                color: #5f5157;
                font-family: "Consolas";
                font-size: 14px;
                font-weight: 800;
                min-width: 52px;
            }
        """)
        self._light_stylesheet = self.styleSheet()
        self._apply_theme()

        # Output-folder validation is performed after the splash/reveal so the
        # first-run dialog is part of the real application flow.
        self.refresh_format_options()
        self.refresh_credit_ui()
        self.update_file_action_state()

        QTimer.singleShot(0, self._animate_reveal)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(250)
        self.ui_timer.timeout.connect(self._update_live_timers)
        self.ui_timer.start()

    def show_fitted(self):
        """Show a frameless window with a comfortable bottom breathing space."""
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            self.showNormal()
            return
        geo = screen.availableGeometry()
        dpi = screen.logicalDotsPerInch() or 96.0
        bottom_gap = int(round(5.0 / 2.54 * dpi))  # requested ~5 cm
        bottom_gap = max(110, min(bottom_gap, 190))
        top_gap = max(18, int(round(0.18 * dpi)))
        width = min(geo.width() - 36, max(1100, int(geo.width() * 0.94)))
        height = max(680, geo.height() - top_gap - bottom_gap)
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y() + top_gap
        self.showNormal()
        self.setGeometry(x, y, width, height)
        self.title_bar.max_button.setText("□")

    def _animate_reveal(self):
        start_pos = self.pos()
        self.move(start_pos.x(), start_pos.y() + 12)
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(220)
        anim.setStartValue(self.pos())
        anim.setEndValue(start_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._reveal_animation = anim

    def _build_menu(self):
        top = QWidget(self)
        top.setObjectName("TopChrome")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        top_layout.addWidget(self.title_bar)

        menu = QMenuBar()
        menu.setNativeMenuBar(False)
        menu.setObjectName("MainMenuBar")
        self.title_bar.set_menu_bar(menu)
        self.setMenuWidget(top)

        file_menu = menu.addMenu("File")
        add_action = QAction("Add Files…", self)
        add_action.setShortcut("Ctrl+O")
        add_action.triggered.connect(self._browse_files)
        file_menu.addAction(add_action)

        clear_action = QAction("Clear All", self)
        clear_action.setShortcut("Ctrl+Shift+Backspace")
        clear_action.triggered.connect(self.clear_files)
        file_menu.addAction(clear_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        remove_menu = menu.addMenu("Remove")
        remove_action = QAction("Remove Selected File", self)
        remove_action.setShortcut("Delete")
        remove_action.triggered.connect(self.remove_selected_file)
        remove_menu.addAction(remove_action)
        clear_remove = QAction("Clear All Files", self)
        clear_remove.triggered.connect(self.clear_files)
        remove_menu.addAction(clear_remove)

        settings_menu = menu.addMenu("Settings")
        output_action = QAction("Output Folder…", self)
        output_action.triggered.connect(self.choose_output_folder)
        settings_menu.addAction(output_action)

        open_output = QAction("Open Output Folder", self)
        open_output.triggered.connect(self.open_output_folder)
        settings_menu.addAction(open_output)

        reset_output = QAction("Reset to Default", self)
        reset_output.triggered.connect(self.reset_output_folder)
        settings_menu.addAction(reset_output)

        appearance_menu = settings_menu.addMenu("Appearance")
        for title, value in (("Light", "light"), ("Dark", "dark"), ("System", "system")):
            action = QAction(title, self)
            action.setCheckable(True)
            action.setChecked(self.theme == value)
            action.triggered.connect(
                lambda checked=False, v=value: self.set_theme(v)
            )
            appearance_menu.addAction(action)
        self._appearance_actions = {
            "light": appearance_menu.actions()[0],
            "dark": appearance_menu.actions()[1],
            "system": appearance_menu.actions()[2],
        }

        help_menu = menu.addMenu("Help")
        privacy_menu = help_menu.addMenu("Privacy Center")
        for title, key in [
            ("Privacy Overview", "overview"),
            ("Local Processing", "local"),
            ("Online Features", "online"),
            ("Files & Temporary Data", "files"),
            ("Network Transparency", "network"),
        ]:
            action = QAction(title, self)
            action.triggered.connect(
                lambda checked=False, k=key: self._show_privacy(k)
            )
            privacy_menu.addAction(action)

        help_menu.addSeparator()
        about_action = QAction("About SakuConvert", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def set_theme(self, theme: str):
        theme = str(theme).lower()
        if theme not in {"light", "dark", "system"}:
            theme = "light"
        self.theme = theme
        self.settings.setValue("theme", theme)
        self.settings.sync()
        for value, action in getattr(self, "_appearance_actions", {}).items():
            action.setChecked(value == theme)
        self._apply_theme()

    def _apply_theme(self):
        theme = self.theme
        if theme == "system":
            # Follow Windows' current palette in a simple, deterministic way.
            app = QApplication.instance()
            window_color = app.palette().window().color() if app else None
            theme = "dark" if window_color and window_color.value() < 128 else "light"

        stylesheet = self._light_stylesheet
        if theme == "dark":
            replacements = {
                "#f8edf2": "#120d11",
                "rgba(255, 250, 252, 238)": "rgba(18, 12, 17, 232)",
                "rgba(255, 250, 252, 248)": "rgba(16, 10, 15, 245)",
                "#e7d9df": "#3d2935",
                "#2b2528": "#f7edf2",
                "#4f4349": "#d9c8d0",
                "#f3e1e8": "#35232d",
                "#e9cbd7": "#4a2c3a",
                "#d96888": "#c95d80",
                "#c45575": "#ad4b69",
                "#f7e1e8": "#38242f",
                "#ffffff": "#1d171c",
                "#e4d9de": "#45343d",
                "#f8e3ea": "#3a2731",
                "#705e67": "#d0b7c3",
                "rgba(255,255,255,225)": "rgba(30, 22, 27, 235)",
                "#e3cbd5": "#563946",
                "#df9fba": "#b86a8b",
                "#e8a8c0": "#d4779d",
                "#2a2024": "#fff4f8",
                "#df9bb5": "#bc6689",
                "#edb6cb": "#df8eb0",
                "#df98b2": "#c96f95",
                "#eee4e8": "#32262c",
                "#95858c": "#a996a0",
                "#f8e1e9": "#3a2630",
                "#7d4056": "#f0b1c7",
                "#dfd3d8": "#514149",
                "#f7dce6": "#4a2b3a",
                "rgba(255,255,255,245)": "rgba(26, 19, 24, 238)",
                "#e4d9de": "#45343d",
                "#f9e2eb": "#402a34",
                "#76666d": "#bdaab3",
                "#9a5670": "#e4a1ba",
                "#4e7b60": "#8cc39a",
                "#a64f57": "#ef8f98",
                "#5f5157": "#c7b4bc",
                "app/ui/sakura_ambient.png": "app/ui/saku_background_dark.png",
            }
            for old, new in replacements.items():
                stylesheet = stylesheet.replace(old, new)
        else:
            stylesheet = stylesheet.replace(
                "app/ui/sakura_ambient.png", "app/ui/saku_background.png"
            )

        self.setStyleSheet(stylesheet)

    def _browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files")
        if files:
            self.add_files([Path(f) for f in files])

    def _is_output_folder_accessible(self, folder: Path, create=False) -> tuple[bool, str]:
        """Return whether *folder* exists and is writable by SakuConvert.

        We deliberately test real write access instead of relying only on
        os.access(), which can be misleading on Windows/network locations.
        """
        try:
            if create and not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
            if not folder.exists():
                return False, "The selected folder does not exist or is not reachable."
            if not folder.is_dir():
                return False, "The selected output path is not a folder."

            probe = folder / ".sakuconvert_write_test.tmp"
            with open(probe, "wb") as fh:
                fh.write(b"SakuConvert")
            try:
                probe.unlink()
            except OSError:
                pass
            return True, ""
        except Exception as exc:
            return False, f"SakuConvert cannot access this folder.\n\n{exc}"

    def _load_output_folder(self):
        """Load the saved folder and validate it before allowing conversion."""
        raw = self.settings.value("output_folder", "")
        if not raw:
            self._output_folder_ready = False
            self._prompt_for_output_folder(first_run=True)
            return

        folder = Path(str(raw)).expanduser()
        ok, reason = self._is_output_folder_accessible(folder)
        if ok:
            self._output_folder = folder
            self._output_folder_ready = True
            self._update_output_badge()
            return

        self._output_folder_ready = False
        QMessageBox.critical(
            self,
            "Output folder unavailable",
            f"Your saved SakuConvert output folder is unavailable:\n\n"
            f"{folder}\n\n{reason}\n\n"
            "Please choose a new accessible folder before converting files.",
        )
        self._prompt_for_output_folder(first_run=False)

    def _prompt_for_output_folder(self, first_run=False):
        title = "Choose SakuConvert output folder"
        message = (
            "SakuConvert needs an output folder before you can convert files.\n\n"
            "Choose a folder where SakuConvert is allowed to create converted files."
            if first_run
            else
            "Choose a new accessible output folder for SakuConvert."
        )

        while True:
            QMessageBox.information(self, title, message)
            folder = QFileDialog.getExistingDirectory(
                self,
                title,
                str(Path.home() / "Downloads"),
                QFileDialog.Option.ShowDirsOnly,
            )
            if not folder:
                self._output_folder_ready = False
                QMessageBox.critical(
                    self,
                    "Output folder required",
                    "SakuConvert cannot convert files until an accessible output folder is selected.",
                )
                return False

            selected = Path(folder)
            ok, reason = self._is_output_folder_accessible(selected)
            if not ok:
                QMessageBox.critical(
                    self,
                    "Output folder unavailable",
                    f"SakuConvert cannot use:\n\n{selected}\n\n{reason}\n\n"
                    "Please choose another folder.",
                )
                continue

            self._output_folder = selected
            self.settings.setValue("output_folder", str(selected))
            self.settings.sync()
            self._output_folder_ready = True
            self._update_output_badge()
            self.status_label.setText("Output folder ready")
            return True

    def ensure_output_folder_ready(self):
        """Called once after the splash screen to perform first-run validation."""
        if self._output_folder_ready:
            return True
        return self._load_output_folder()

    def _update_output_badge(self):
        if self._output_folder_ready:
            self.output_badge.setText(f"Output: {self._output_folder}")
            self.output_badge.setToolTip(str(self._output_folder))
        else:
            self.output_badge.setText("Output: Not selected")
            self.output_badge.setToolTip("Choose an accessible output folder in Settings.")

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose output folder", str(self._output_folder)
        )
        if not folder:
            return

        selected = Path(folder)
        ok, reason = self._is_output_folder_accessible(selected)
        if not ok:
            QMessageBox.critical(
                self,
                "Output folder unavailable",
                f"SakuConvert cannot use:\n\n{selected}\n\n{reason}",
            )
            return

        self._output_folder = selected
        self.settings.setValue("output_folder", str(selected))
        self.settings.sync()
        self._output_folder_ready = True
        self._update_output_badge()
        self.status_label.setText("Output folder updated")

    def reset_output_folder(self):
        self.settings.remove("output_folder")
        self.settings.sync()
        self._output_folder_ready = False
        self._update_output_badge()
        self._prompt_for_output_folder(first_run=True)

    def open_output_folder(self):
        if not self._output_folder_ready:
            if not self.ensure_output_folder_ready():
                return
        ok, reason = self._is_output_folder_accessible(self._output_folder)
        if not ok:
            self._output_folder_ready = False
            self._update_output_badge()
            QMessageBox.critical(
                self,
                "Output folder unavailable",
                f"The output folder is no longer accessible:\n\n"
                f"{self._output_folder}\n\n{reason}",
            )
            return

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_folder)))
        if not opened:
            QMessageBox.critical(
                self,
                "Could not open output folder",
                f"Windows could not open:\n\n{self._output_folder}",
            )

    def _show_privacy(self, key="overview"):
        texts = {
            "overview": (
                "Privacy Overview",
                "SakuConvert is local-first. Normal conversions are performed "
                "on this computer. No cloud conversion service is used for "
                "normal conversion."
            ),
            "local": (
                "Local Processing",
                "Image, video, audio and document conversions use local "
                "software. Normal conversion files are not sent to a "
                "SakuConvert backend."
            ),
            "online": (
                "Online Features",
                "Background removal is the explicit online exception. "
                "SakuConvert asks for confirmation immediately before the "
                "selected image is uploaded to the configured third-party "
                "provider. Normal conversion does not require Internet access."
            ),
            "files": (
                "Files & Temporary Data",
                "Converted output is written to the folder shown in Settings. "
                "Conversion libraries may create temporary data while a job "
                "runs. SakuConvert does not intentionally upload normal "
                "conversion files."
            ),
            "network": (
                "Network Transparency",
                "Normal conversion is designed to work without Internet access. "
                "Background removal makes a network request only after you "
                "confirm. Third-party provider policies remain outside "
                "SakuConvert's control."
            ),
        }
        title, body = texts.get(key, texts["overview"])
        QMessageBox.information(self, title, body)

    def _show_about(self):
        QMessageBox.about(
            self,
            "About SakuConvert",
            "SakuConvert\n\n"
            "A free, open-source, privacy-first desktop file converter.\n\n"
            "FEATURES\n"
            "• Image conversion: PNG, JPEG, WEBP, GIF, BMP, TIFF, HEIC/HEIF\n"
            "• Video conversion using local codecs\n"
            "• Audio conversion using local codecs\n"
            "• PDF → Word and Word → PDF document conversion\n"
            "• Image → Text (OCR) and Text → Image\n"
            "• Optional online background removal with an explicit warning\n"
            "• Sequential multi-file conversion queue with per-file timers\n"
            "• User-selected output folder\n\n"
            "PRIVACY MODEL\n"
            "Normal conversions are designed to stay on your device. "
            "No cloud conversion is used.\n"
            "Background removal is a separate online feature and requires "
            "your confirmation before upload.\n\n"
            "DESIGN PRINCIPLES\n"
            "• Local-first processing\n"
            "• No silent uploads\n"
            "• Preserve content where possible\n"
            "• Never silently crop or resize images\n"
            "• Explain limitations instead of hiding them\n\n"
            "SakuConvert is community-driven open-source software."
        )

    def update_file_action_state(self):
        enabled = (
            bool(self.current_files)
            and self.media_type is not None
            and self._worker_thread is None
        )
        self.convert_button.setEnabled(enabled)

    def clear_files(self):
        if self._worker_thread is not None:
            return
        self.current_files.clear()
        self.files.clear()
        self.media_type = None
        self.detected_label.setText("No file selected")
        self.status_label.setText("Ready")
        self.refresh_format_options()
        self.refresh_credit_ui()
        self.update_file_action_state()

    def remove_file(self, path: Path):
        if self._worker_thread is not None:
            return
        try:
            index = self.current_files.index(path)
        except ValueError:
            return

        self.current_files.pop(index)
        self.files.takeItem(index)
        self.rebuild_media_state()

        if self.files.count():
            self.files.setCurrentRow(min(index, self.files.count() - 1))
        self.status_label.setText("File removed")
        self.refresh_credit_ui()

    def remove_selected_file(self):
        if self._worker_thread is not None:
            return
        selected = self.files.selectedItems()
        if selected:
            path = Path(selected[0].data(Qt.ItemDataRole.UserRole))
            self.remove_file(path)

    def add_files(self, paths):
        if self._worker_thread is not None:
            return

        valid = [p for p in paths if p.exists() and p.is_file()]
        if not valid:
            return

        for path in valid:
            if path in self.current_files:
                continue

            try:
                kind = detect_media_type(path)
                if kind == "image":
                    label = (
                        f"{path.name}  •  {detect_image(path)}  •  "
                        f"{path.stat().st_size / 1024:.1f} KB"
                    )
                elif kind == "video":
                    label = (
                        f"{path.name}  •  VIDEO  •  "
                        f"{path.stat().st_size / (1024 * 1024):.1f} MB"
                    )
                elif kind == "audio":
                    label = (
                        f"{path.name}  •  AUDIO  •  "
                        f"{path.stat().st_size / (1024 * 1024):.1f} MB"
                    )
                else:
                    label = f"{path.name}  •  {kind.upper()}"
            except Exception:
                label = f"{path.name}  •  unsupported/unknown"

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setSizeHint(QSize(0, 48))
            self.files.addItem(item)

            row = FileRow(
                label,
                lambda checked=False, p=path: self.remove_file(p),
            )
            self.files.setItemWidget(item, row)
            self.current_files.append(path)

        self.rebuild_media_state()
        if self.files.count() and not self.files.selectedItems():
            self.files.setCurrentRow(0)

        self.status_label.setText(
            f"Loaded {len(self.current_files)} file"
            f"{'s' if len(self.current_files) != 1 else ''}"
        )
        self.refresh_credit_ui()

    def rebuild_media_state(self):
        if not self.current_files:
            self.media_type = None
            self.detected_label.setText("No file selected")
            self.refresh_format_options()
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
            self.format_label.hide()
            self.format_box.hide()
            self.convert_button.setEnabled(False)
            self.refresh_credit_ui()
            return

        self.media_type = types[0]
        labels = {
            "image": "IMAGE",
            "video": "VIDEO",
            "audio": "AUDIO",
            "pdf": "PDF",
            "word": "WORD/DOCX",
            "text": "TEXT",
        }
        self.detected_label.setText(
            f"Detected: {labels.get(self.media_type, self.media_type.upper())}"
        )
        self.refresh_format_options()
        self.refresh_credit_ui()

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
            self.format_label.hide()
            self.format_box.hide()
            self.format_box.blockSignals(False)
            self.convert_button.setEnabled(False)
            return

        self.format_label.show()
        self.format_box.show()
        self.format_box.blockSignals(False)
        self.refresh_analysis()

    def refresh_analysis(self):
        if (
            not self.current_files
            or not self.media_type
            or not self.format_box.currentText()
        ):
            self.convert_button.setText("Choose a file to convert")
            self.convert_button.setEnabled(False)
            return

        target = self.format_box.currentText()
        labels = {
            "WORD (DOCX)": "Convert to Word",
            "PDF": "Convert to PDF",
            "TEXT (OCR)": "Extract Text (OCR)",
            "PNG IMAGE": "Convert to PNG",
        }
        self.convert_button.setText(
            labels.get(target, f"Convert to {target}")
        )

        if self.media_type == "pdf" and not self._document_engines["pdf_to_word"]:
            self.status_label.setText(
                "PDF → Word engine is not installed"
            )
            self.convert_button.setEnabled(False)
            return

        if self.media_type == "word" and not self._document_engines["word_to_pdf"]:
            self.status_label.setText(
                "Install Microsoft Word or LibreOffice for Word → PDF"
            )
            self.convert_button.setEnabled(False)
            return

        self.convert_button.setEnabled(self._worker_thread is None)

    def _row_for_index(self, index):
        if 0 <= index < self.files.count():
            return self.files.itemWidget(self.files.item(index))
        return None

    def _update_live_timers(self):
        for i in range(self.files.count()):
            row = self._row_for_index(i)
            if row:
                row.update_timer()

    def _safe_output(self, source: Path, target: str) -> Path:
        ext_map = {
            "WORD (DOCX)": ".docx",
            "TEXT (OCR)": ".txt",
            "PNG IMAGE": ".png",
            "JPEG": ".jpg",
        }
        ext = ext_map.get(target, "." + target.lower())
        candidate = self._output_folder / f"{source.stem}{ext}"

        if candidate == source:
            candidate = self._output_folder / f"{source.stem}_converted{ext}"

        n = 1
        while candidate.exists():
            candidate = (
                self._output_folder
                / f"{source.stem}_converted_{n}{ext}"
            )
            n += 1
        return candidate

    def _convert_one(self, source: Path, dest: Path, target: str):
        if self.media_type == "image" and target == "TEXT (OCR)":
            return image_to_text(source, dest)

        if self.media_type == "image":
            result = analyze_image(source, target)
            if result.source.has_alpha and target in {"JPEG", "BMP"}:
                raise RuntimeError(
                    "This target cannot store transparency. Choose a target "
                    "that supports transparency."
                )
            return convert(source, dest, target)[0]

        if self.media_type == "video":
            return convert_video(source, dest, target)

        if self.media_type == "audio":
            return convert_audio(source, dest, target)

        if self.media_type == "pdf":
            return pdf_to_word(source, dest)

        if self.media_type == "word":
            return word_to_pdf(source, dest)

        if self.media_type == "text":
            return text_to_image(source, dest)

        raise RuntimeError("Unsupported conversion type")

    def convert_selected(self):
        if (
            not self.current_files
            or not self.media_type
            or not self.format_box.currentText()
            or self._worker_thread is not None
        ):
            return

        if not self._output_folder_ready:
            if not self.ensure_output_folder_ready():
                return

        ok, reason = self._is_output_folder_accessible(self._output_folder)
        if not ok:
            self._output_folder_ready = False
            self._update_output_badge()
            QMessageBox.critical(
                self,
                "Output folder unavailable",
                f"SakuConvert cannot write converted files to:\n\n"
                f"{self._output_folder}\n\n{reason}\n\n"
                "Choose another folder in Settings.",
            )
            return

        target = self.format_box.currentText()
        self._queue_index = 0
        self._queue_success = 0
        self._queue_failed = 0

        for i in range(self.files.count()):
            row = self._row_for_index(i)
            if row:
                row.waiting()
                row.remove_button.setEnabled(False)

        self._process_next_in_queue(target)

    def _process_next_in_queue(self, target):
        if self._queue_index >= len(self.current_files):
            self._worker_thread = None
            self._worker = None
            self.convert_button.setEnabled(True)
            self.convert_button.setText("Convert Again")
            self.status_label.setText(
                f"Queue complete • {self._queue_success} completed • "
                f"{self._queue_failed} failed"
            )

            # Automatically open the selected output folder after a successful
            # queue so the user can immediately see the converted files.
            if self._queue_success > 0:
                QTimer.singleShot(250, self.open_output_folder)

            for i in range(self.files.count()):
                row = self._row_for_index(i)
                if row:
                    row.remove_button.setEnabled(True)
            return

        index = self._queue_index
        source = self.current_files[index]
        destination = self._safe_output(source, target)
        row = self._row_for_index(index)

        if row:
            row.start()

        self.status_label.setText(
            f"Converting {index + 1} of {len(self.current_files)} • "
            f"{source.name}"
        )
        self.convert_button.setText(
            f"Converting {index + 1}/{len(self.current_files)}…"
        )
        self.convert_button.setEnabled(False)

        self._worker_thread = QThread(self)
        self._worker = ConversionWorker(
            lambda: self._convert_one(source, destination, target)
        )
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(
            lambda output, idx=index: self._queue_item_done(
                idx, Path(output)
            )
        )
        self._worker.failed.connect(
            lambda message, idx=index: self._queue_item_failed(
                idx, message
            )
        )
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_cleanup)
        self._worker_thread.start()

    def _queue_item_done(self, index, output):
        row = self._row_for_index(index)
        if row:
            row.complete()
        self._queue_success += 1
        self.status_label.setText(
            f"✓ Completed • {self.current_files[index].name}"
        )

    def _queue_item_failed(self, index, message):
        row = self._row_for_index(index)
        if row:
            row.fail()
        self._queue_failed += 1
        self.status_label.setText(
            f"⚠ Failed • {self.current_files[index].name}"
        )

    def _worker_cleanup(self):
        self._worker = None
        self._worker_thread = None
        self._queue_index += 1
        QTimer.singleShot(
            120,
            lambda: self._process_next_in_queue(
                self.format_box.currentText()
            ),
        )

    def refresh_credit_ui(self):
        left = remaining_today()
        enabled = (
            self.media_type == "image"
            and bool(self.current_files)
            and left > 0
            and self._worker_thread is None
        )
        self.remove_bg_button.setEnabled(enabled)

        if left > 0:
            self.remove_bg_button.setText("✦ Remove Background")
            self.remove_bg_button.setToolTip(
                "Online feature: requires confirmation and Internet access."
            )
        else:
            self.remove_bg_button.setText(
                "✦ Background Removal Unavailable Today"
            )
            self.remove_bg_button.setToolTip(
                "Daily background-removal allowance is exhausted. "
                "Try again tomorrow."
            )

    def background_removal_info(self):
        left = remaining_today()
        if (
            not self.current_files
            or self.media_type != "image"
            or left <= 0
        ):
            self.refresh_credit_ui()
            return

        source = self.current_files[0]
        provider = get_provider("bgninja")

        answer = QMessageBox.warning(
            self,
            "Online background removal",
            f"This is the one SakuConvert feature that uses the Internet.\n\n"
            f"Your selected image will be uploaded to {provider.name} "
            f"for processing.\n"
            f"Normal conversions remain local and do not require this upload.\n\n"
            f"SakuConvert daily credit: {left}/{DAILY_LIMIT} remaining.\n"
            f"Provider limit: 10 requests/day per IP.\n\n"
            f"Continue with online background removal?",
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Ok:
            return

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Save background-removed image",
            str(self._output_folder / f"{source.stem}_no_bg.png"),
            "PNG (*.png)",
        )
        if not destination:
            return

        self.remove_bg_button.setEnabled(False)
        self.status_label.setText(
            "Uploading image for background removal…"
        )

        try:
            output = remove_background_online(
                source,
                Path(destination),
                provider_id="bgninja",
            )
            record_success()
        except BackgroundAPIError as exc:
            if exc.daily_limit_reached:
                mark_exhausted()
            QMessageBox.critical(
                self, "Background removal failed", str(exc)
            )
            return
        finally:
            self.refresh_credit_ui()

        left = remaining_today()
        self.status_label.setText("Background removal complete")
        QMessageBox.information(
            self,
            "Background removal complete",
            f"✓ Done\n\nSaved: {Path(output).name}\n\n"
            f"SakuConvert credit remaining: {left}/{DAILY_LIMIT}",
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return

        if (
            event.key() == Qt.Key.Key_Escape
            and self.isFullScreen()
        ):
            self.showNormal()
            return

        super().keyPressEvent(event)
