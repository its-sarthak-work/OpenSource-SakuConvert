from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class SplashScreen(QWidget):
    """Clean logo-first startup screen for SakuConvert."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(520, 420)
        self.setStyleSheet("""
            QWidget {
                background: #fffafd;
                border: 1px solid #efdce5;
                border-radius: 24px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("border: none; background: transparent;")
        pixmap = QPixmap("app/ui/sakuro_logo.png")
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(
                350, 350,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.activateWindow()

    def reveal_and_close(self, main_window):
        """Reveal the real app only after the logo splash has been shown."""
        main_window.setWindowOpacity(0.0)
        main_window.show()
        main_window.raise_()
        main_window.activateWindow()

        fade_main = QPropertyAnimation(main_window, b"windowOpacity", self)
        fade_main.setDuration(360)
        fade_main.setStartValue(0.0)
        fade_main.setEndValue(1.0)
        fade_main.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_main.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(260)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)
        fade.finished.connect(self.close)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
