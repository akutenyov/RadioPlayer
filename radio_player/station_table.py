"""Presentation and incremental population of the station table."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from .widgets import BitrateItem

TABLE_BATCH_SIZE = 100


class StationTablePresenter(QObject):
    """Keep large table updates responsive by writing a bounded batch per event-loop turn."""

    def __init__(self, table: QTableWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.table = table
        self.pending_stations: list[dict[str, str]] = []
        self.fill_index = 0
        self.column_max_widths: list[int] = []
        self.fill_timer = QTimer(self)
        self.fill_timer.setInterval(0)
        self.fill_timer.timeout.connect(self._fill_next_batch)

    @staticmethod
    def configure(table: QTableWidget) -> None:
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["Назва станції", "Країна", "Genre", "Codec", "Bitrate", "URL"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setSortingEnabled(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setStyleSheet(
            "QTableWidget { background-color: #2f2f2f; color: #ffffff; gridline-color: #4a4a4a; }"
            "QHeaderView::section { background-color: #242424; color: #ffffff; }"
        )

    def begin_fill(self, stations: list[dict[str, str]], on_finished: Callable[[], None]) -> None:
        """Prepare one result set; sorting is disabled until all rows are inserted."""
        self._on_finished = on_finished
        self.pending_stations = stations
        self.fill_index = 0
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(stations))

        metrics = self.table.fontMetrics()
        self.column_max_widths = [
            metrics.horizontalAdvance(self.table.horizontalHeaderItem(column).text())
            for column in range(self.table.columnCount())
        ]
        if not stations:
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(True)
            self._on_finished()
            return
        self.fill_timer.start()

    def _fill_next_batch(self) -> None:
        if not self.pending_stations:
            self.fill_timer.stop()
            return

        end_index = min(self.fill_index + TABLE_BATCH_SIZE, len(self.pending_stations))
        table = self.table
        set_item = table.setItem
        widths = self.column_max_widths
        advance = table.fontMetrics().horizontalAdvance

        for row in range(self.fill_index, end_index):
            station = self.pending_stations[row]
            values = [
                station["name"],
                station["country"],
                station["genre"],
                station["codec"],
                station["bitrate"],
                station["url"],
            ]
            name_item = QTableWidgetItem(values[0])
            name_item.setData(Qt.ItemDataRole.UserRole, station)
            set_item(row, 0, name_item)
            set_item(row, 1, QTableWidgetItem(values[1]))
            set_item(row, 2, QTableWidgetItem(values[2]))
            set_item(row, 3, QTableWidgetItem(values[3]))
            set_item(row, 4, BitrateItem(values[4]))
            set_item(row, 5, QTableWidgetItem(values[5]))
            for column, value in enumerate(values):
                widths[column] = max(widths[column], advance(value))

        self.fill_index = end_index
        if self.fill_index >= len(self.pending_stations):
            self.fill_timer.stop()
            table.setUpdatesEnabled(True)
            table.setSortingEnabled(True)
            self.apply_column_widths()
            self.pending_stations = []
            self._on_finished()

    def apply_column_widths(self) -> None:
        metrics = self.table.fontMetrics()
        char_width = metrics.horizontalAdvance("0")
        self.table.setColumnWidth(0, char_width * 50)
        self.table.setColumnWidth(1, char_width * 25)
        self.table.setColumnWidth(2, char_width * 25)
        self.table.setColumnWidth(3, self.column_max_widths[3] + char_width * 3)
        self.table.setColumnWidth(4, char_width * 25)
        self.table.setColumnWidth(5, char_width * 70)

    def highlight_active_station(self, current_url: str) -> None:
        active_bg, active_fg = QBrush(QColor("#ffffff")), QBrush(QColor("#000000"))
        normal_bg, normal_fg = QBrush(QColor("#2f2f2f")), QBrush(QColor("#ffffff"))
        for row in range(self.table.rowCount()):
            url_item = self.table.item(row, 5)
            is_active = bool(url_item and current_url and url_item.text().strip() == current_url)
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item:
                    item.setBackground(active_bg if is_active else normal_bg)
                    item.setForeground(active_fg if is_active else normal_fg)
