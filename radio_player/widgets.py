"""Custom Qt widgets used by RadioPlayer."""

from typing import Any

from PyQt6.QtWidgets import QTableWidgetItem


class BitrateItem(QTableWidgetItem):
    """Table item that sorts bitrate values numerically."""

    def __init__(self, value: str):
        super().__init__(value)
        try:
            self.bitrate_value = int(float(value))
        except (TypeError, ValueError):
            self.bitrate_value = -1

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, BitrateItem):
            return self.bitrate_value < other.bitrate_value
        return super().__lt__(other)
