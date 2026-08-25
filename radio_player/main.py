"""Qt application bootstrap."""

import sys

from PyQt6.QtWidgets import QApplication

from .app import RadioApp


def main() -> None:
    app = QApplication(sys.argv)
    font = app.font()
    font.setPointSize(font.pointSize() + 1)
    app.setFont(font)

    window = RadioApp()
    window.show()
    sys.exit(app.exec())
