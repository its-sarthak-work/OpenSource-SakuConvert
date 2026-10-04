import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.splash import SplashScreen


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SakuConvert")
    app.setApplicationDisplayName("SakuConvert")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 13))

    # Show the brand logo first. The real application is not constructed
    # until the splash has finished its short hold, so the user never sees
    # the main UI underneath the logo.
    splash = SplashScreen()
    splash.show_centered()

    window_holder = {}

    def launch_app():
        window = MainWindow()
        window_holder["window"] = window
        window.show_fitted()
        splash.reveal_and_close(window)
        # Let the reveal finish before asking for first-launch output setup.
        QTimer.singleShot(500, window.ensure_output_folder_ready)

    QTimer.singleShot(900, launch_app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
