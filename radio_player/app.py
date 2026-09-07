"""The RadioPlayer main window and its UI-level orchestration."""

from __future__ import annotations

import re
from typing import Any

from PyQt6.QtCore import QSettings, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .api import APP_VERSION, CountriesLoader, StationsLoader, default_country_map
from .metadata import clean_stream_title, normalize_bitrate
from .metadata_view import MetadataView
from .playback import PlaybackEngine
from .station_table import StationTablePresenter


class RadioApp(QMainWindow):
    """Coordinate background API loading, table presentation, and audio playback."""

    probed_title_ready = pyqtSignal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Radio Player {APP_VERSION}")
        self.setWindowIcon(self._build_radio_icon())
        self.resize(1200, 780)

        self.countries = default_country_map()
        self.loader_thread: QThread | None = None
        self.loader_worker: StationsLoader | None = None
        self.countries_thread: QThread | None = None
        self.countries_worker: CountriesLoader | None = None
        self.is_loading = False
        self.bitrate_sort_order = Qt.SortOrder.DescendingOrder
        self.url_sort_order = Qt.SortOrder.AscendingOrder

        self.current_stream_url = ""
        self.current_station_name = "-"
        self.current_codec = "-"
        self.current_bitrate = "-"
        self.current_genre = "-"
        self.current_description = "-"
        self.last_stream_title = "-"
        self.stream_probe_id = 0
        self._meta_key_cache: dict[str, Any] = {}
        self.settings = QSettings("akutenyov", "RadioPlayer")

        self._build_ui()
        self.playback = PlaybackEngine(f"RadioPlayer/{APP_VERSION}", self)
        # Backwards-compatible aliases also make the Qt ownership visible at the window level.
        self.media_player = self.playback.player
        self.audio_output = self.playback.audio_output
        self.metadata_timer = self.playback.metadata_timer
        self.playback.player_error.connect(self.handle_player_error)
        self.playback.metadata_changed.connect(self.update_stream_info)
        self.playback.title_probed.connect(self.on_probed_title_ready)
        self.probed_title_ready.connect(self.on_probed_title_ready)

        self._restore_settings()
        self.load_countries()
        self.load_data()

    def _build_radio_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#000000"), 4))
        painter.drawLine(32, 52, 32, 22)
        painter.setPen(QPen(QColor("#000000"), 3))
        painter.drawLine(22, 54, 42, 54)
        painter.setBrush(QColor("#000000"))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.drawEllipse(28, 16, 8, 8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#000000"), 3))
        painter.drawArc(20, 10, 24, 24, 30 * 16, 120 * 16)
        painter.drawArc(12, 2, 40, 40, 30 * 16, 120 * 16)
        painter.end()
        return QIcon(pixmap)

    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        search_bar = QHBoxLayout()
        self.country_combo = QComboBox()
        self.country_combo.addItems(self.countries.keys())
        self.country_combo.setCurrentText("Всі країни")
        self.country_combo.currentTextChanged.connect(self._persist_selected_country)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Пошук за назвою...")
        self.name_input.returnPressed.connect(self.load_data)
        self.search_btn = QPushButton("Знайти")
        self.search_btn.clicked.connect(self.load_data)
        self.status_label = QLabel("Статус: Всі країни")
        search_bar.addWidget(QLabel("Країна"))
        search_bar.addWidget(self.country_combo)
        search_bar.addWidget(self.name_input)
        search_bar.addWidget(self.search_btn)
        search_bar.addWidget(self.status_label)
        main_layout.addLayout(search_bar)

        self.table = QTableWidget()
        StationTablePresenter.configure(self.table)
        self.table_presenter = StationTablePresenter(self.table, self)
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.itemDoubleClicked.connect(self.play_radio)
        main_layout.addWidget(self.table)

        controls_row = QHBoxLayout()
        self.restart_btn = QPushButton("↻")
        self.restart_btn.clicked.connect(self.restart_stream)
        self.restart_btn.setFixedSize(66, 48)
        self.play_pause_btn = QPushButton("▶")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.play_pause_btn.setFixedSize(66, 48)
        button_style = (
            "QPushButton {font-size:25px;font-weight:700;color:#111;"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f9f9f9,stop:1 #cfcfcf);"
            "border:1px solid #7f7f7f;border-radius:8px;padding-bottom:2px;}"
            "QPushButton:pressed {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #bcbcbc,stop:1 #e6e6e6);"
            "padding-top:2px;padding-bottom:0px;}"
        )
        self.restart_btn.setStyleSheet(button_style + "QPushButton {font-size:28px;font-weight:900;}")
        self.play_pause_btn.setStyleSheet(button_style)
        self.current_label = QLabel("Оберіть станцію (подвійний клік)")
        self.current_label.setStyleSheet("font-size: 12pt;")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.change_volume)
        self.volume_label = QLabel("Гучність:")
        self.volume_label.setStyleSheet("font-size: 10pt;")
        controls_row.addWidget(self.restart_btn)
        controls_row.addWidget(self.play_pause_btn)
        controls_row.addWidget(self.current_label)
        controls_row.addStretch()
        controls_row.addWidget(self.volume_label)
        controls_row.addWidget(self.volume_slider)
        main_layout.addLayout(controls_row)

        title = QLabel("Metadata")
        title.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 13pt; font-weight: 700;")
        main_layout.addWidget(title)
        self.metadata_label = QLabel()
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.metadata_label.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 10pt;")
        self.metadata_view = MetadataView(self.metadata_label)
        self._render_metadata("-", "-", "-", "-", "-", "-", "-", "-")
        main_layout.addWidget(self.metadata_label)

    def load_countries(self) -> None:
        self.countries_thread = QThread(self)
        self.countries_worker = CountriesLoader()
        self.countries_worker.moveToThread(self.countries_thread)
        self.countries_thread.started.connect(self.countries_worker.run)
        self.countries_worker.finished.connect(self.on_countries_loaded)
        self.countries_worker.error.connect(self.on_countries_loading_error)
        self.countries_worker.finished.connect(self.countries_thread.quit)
        self.countries_worker.error.connect(self.countries_thread.quit)
        self.countries_thread.finished.connect(self.cleanup_countries_loader)
        self.countries_thread.start()

    def on_countries_loaded(self, countries: dict[str, str]) -> None:
        selected_country = self.country_combo.currentText()
        self.countries = countries
        self.country_combo.clear()
        self.country_combo.addItems(countries.keys())
        self.country_combo.setCurrentText(selected_country)

    def _restore_settings(self) -> None:
        """Restore UI state before the first search, but never auto-play a saved URL.

        The asynchronous country refresh replaces the combo-box list later; its loader
        preserves the current text, so restoring here avoids a second network request.
        """
        volume = self.settings.value("volume", 50)
        try:
            self.volume_slider.setValue(max(0, min(100, int(volume))))
        except (TypeError, ValueError):
            self.volume_slider.setValue(50)
        self.change_volume(self.volume_slider.value())
        self.country_combo.setCurrentText(str(self.settings.value("selected_country", "Всі країни")))

        saved_url = str(self.settings.value("last_station_url", "")).strip()
        saved_name = str(self.settings.value("last_station_name", "")).strip()
        if saved_url and saved_name:
            self.current_stream_url = saved_url
            self.current_station_name = saved_name
            self.current_label.setText(f"Остання станція: {saved_name}")

    def _save_last_station(self) -> None:
        self.settings.setValue("last_station_url", self.current_stream_url)
        self.settings.setValue("last_station_name", self.current_station_name)

    def _persist_selected_country(self, country_name: str) -> None:
        self.settings.setValue("selected_country", country_name)

    def on_countries_loading_error(self, _message: str) -> None:
        """Keep the built-in country list available when the API is offline."""

    def cleanup_countries_loader(self) -> None:
        if self.countries_worker:
            self.countries_worker.deleteLater()
        if self.countries_thread:
            self.countries_thread.deleteLater()
        self.countries_worker = None
        self.countries_thread = None

    def load_data(self) -> None:
        if self.is_loading:
            return
        country_name = self.country_combo.currentText()
        self.is_loading = True
        self.search_btn.setEnabled(False)
        self.current_label.setText("Завантаження станцій...")
        self.status_label.setText(f"Статус: Завантаження | Країна: {country_name}")
        self.loader_thread = QThread(self)
        self.loader_worker = StationsLoader(self.countries.get(country_name, ""), self.name_input.text().strip())
        self.loader_worker.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader_worker.run)
        self.loader_worker.finished.connect(self.on_stations_loaded)
        self.loader_worker.error.connect(self.on_loading_error)
        self.loader_worker.finished.connect(self.loader_thread.quit)
        self.loader_worker.error.connect(self.loader_thread.quit)
        self.loader_thread.finished.connect(self.cleanup_loader)
        self.loader_thread.start()

    def on_stations_loaded(self, stations: list[dict[str, str]]) -> None:
        self.search_btn.setEnabled(True)
        country_name = self.country_combo.currentText()
        self.current_label.setText(f"Знайдено станцій {len(stations)}")
        self.status_label.setText(f"Статус: Готово | Країна: {country_name} | Результатів: {len(stations)}")
        self._begin_fill(stations)

    def on_loading_error(self, message: str) -> None:
        self.table.setRowCount(0)
        self.search_btn.setEnabled(True)
        self.current_label.setText(message)
        self.status_label.setText(f"Статус: Помилка | {message}")

    def cleanup_loader(self) -> None:
        if self.loader_worker:
            self.loader_worker.deleteLater()
        if self.loader_thread:
            self.loader_thread.deleteLater()
        self.loader_worker = None
        self.loader_thread = None
        self.is_loading = False

    def _begin_fill(self, stations: list[dict[str, str]]) -> None:
        self.table_presenter.begin_fill(stations, self._highlight_active_station)

    def _highlight_active_station(self) -> None:
        self.table_presenter.highlight_active_station(self.current_stream_url)

    def on_header_clicked(self, column: int) -> None:
        if column == 4:
            self.table.sortItems(4, self.bitrate_sort_order)
            self.bitrate_sort_order = (
                Qt.SortOrder.AscendingOrder
                if self.bitrate_sort_order == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )
            self._highlight_active_station()
        elif column == 5:
            self.table.sortItems(5, self.url_sort_order)
            self.url_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self.url_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            self._highlight_active_station()

    def toggle_play_pause(self) -> None:
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.playback.pause()
            self.play_pause_btn.setText("▶")
        elif self.current_stream_url:
            self.playback.resume()
            self.play_pause_btn.setText("⏸")
        else:
            self.current_label.setText("Оберіть станцію для відтворення")

    def play_radio(self, item: QTableWidgetItem) -> None:
        row = item.row()
        name_item, codec_item = self.table.item(row, 0), self.table.item(row, 3)
        bitrate_item, url_item = self.table.item(row, 4), self.table.item(row, 5)
        if not name_item or not url_item:
            self.current_label.setText("Помилка неповні дані станції")
            return
        url = url_item.text().strip()
        qurl = QUrl(url)
        if not qurl.isValid() or qurl.scheme() not in {"http", "https"}:
            self.current_label.setText("Помилка некоректний URL потоку")
            return
        station_data = name_item.data(Qt.ItemDataRole.UserRole)
        self.current_stream_url = url
        self.current_station_name = name_item.text().strip() or "Без назви"
        self.current_codec = codec_item.text().strip() if codec_item else "-"
        self.current_bitrate = bitrate_item.text().strip() if bitrate_item else "-"
        if isinstance(station_data, dict):
            self.current_genre = str(station_data.get("genre") or "-").strip()
            self.current_description = str(station_data.get("description") or "-").strip()
        else:
            self.current_genre = self.current_description = "-"
        self.last_stream_title = "-"
        self.stream_probe_id += 1
        self._save_last_station()
        bitrate = normalize_bitrate(self.current_bitrate)
        self._update_current_label()
        self._render_metadata(
            self.current_codec,
            bitrate,
            self.current_genre,
            self.current_station_name,
            url,
            f"ice-samplerate=44100;ice-bitrate={bitrate};ice-channels=2",
            self.current_description,
            "-",
        )
        self.playback.play(qurl)
        self.play_pause_btn.setText("⏸")
        self.playback.start_title_probe(url, self.stream_probe_id)
        self._highlight_active_station()

    def restart_stream(self) -> None:
        if not self.current_stream_url:
            self.current_label.setText("Немає активного стріму для перезапуску")
            return
        self.last_stream_title = "-"
        self.stream_probe_id += 1
        self.playback.play(QUrl(self.current_stream_url))
        self.play_pause_btn.setText("⏸")
        self.playback.start_title_probe(self.current_stream_url, self.stream_probe_id)
        self._highlight_active_station()

    def _meta_by_key_name(self, key_name: str, metadata: Any | None = None) -> str:
        key = self._meta_key_cache.get(key_name)
        if key is None and key_name not in self._meta_key_cache:
            key = getattr(QMediaMetaData.Key, key_name, None)
            self._meta_key_cache[key_name] = key
        if key is None:
            return ""
        try:
            value = (metadata if metadata is not None else self.media_player.metaData()).value(key)
        except Exception:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return "" if value is None else str(value).strip()

    def _meta_first(self, key_names: list[str], metadata: Any | None = None) -> str:
        return next((value for key in key_names if (value := self._meta_by_key_name(key, metadata))), "")

    def _render_metadata(
        self,
        codec: str,
        bitrate: str,
        genre: str,
        name: str,
        url: str,
        audio_info: str,
        description: str,
        stream_title: str,
    ) -> None:
        """Compatibility facade for the safe metadata view, retained for callers and tests."""
        self.metadata_view.render(codec, bitrate, genre, name, url, audio_info, description, stream_title)

    def on_probed_title_ready(self, probe_id: int, title: str) -> None:
        if probe_id != self.stream_probe_id:
            return
        clean_title = clean_stream_title(title)
        if clean_title:
            self.last_stream_title = clean_title
            self.update_stream_info()

    def _update_current_label(self) -> None:
        if self.current_station_name == "-":
            return
        title = clean_stream_title(self.last_stream_title)
        base = self.current_station_name if not title or title == "-" else f"{self.current_station_name} | {title}"
        full_text = f"Відтворюється: {base}"
        self.current_label.setText(full_text if len(full_text) <= 70 else f"{full_text[:67]}...")
        self.current_label.setToolTip(full_text if len(full_text) > 70 else "")

    def update_stream_info(self) -> None:
        try:
            metadata = self.media_player.metaData()
            sample_rate = self._meta_first(["AudioSampleRate"], metadata) or "44100"
            bitrate = normalize_bitrate(self._meta_first(["AudioBitRate"], metadata))
            if bitrate == "-":
                bitrate = normalize_bitrate(self.current_bitrate)
            codec = (self._meta_first(["AudioCodec"], metadata) or self.current_codec or "mp3").lower()
            genre = self._meta_first(["Genre"], metadata) or self.current_genre or "-"
            name = self._meta_first(["Station", "AlbumTitle", "Title"], metadata) or self.current_station_name or "-"
            description = self._meta_first(["Description", "Comment"], metadata) or self.current_description or "-"
            raw_title = self._meta_first(["Title", "Comment", "Description"], metadata)
            match = re.search(r"StreamTitle='([^']+)'", raw_title, flags=re.IGNORECASE) if raw_title else None
            stream_title = clean_stream_title(match.group(1) if match else raw_title) if raw_title else "-"
            if stream_title == "-" and self.last_stream_title != "-":
                stream_title = self.last_stream_title
            elif stream_title != "-":
                self.last_stream_title = stream_title
            channel_count = self._meta_first(["ChannelCount", "AudioChannelCount"], metadata)
            if channel_count == "1":
                channels = "1"
            elif channel_count == "2" or not channel_count:
                channels = "2"
            else:
                channels = channel_count
            audio_info = f"ice-samplerate={sample_rate};ice-bitrate={bitrate};ice-channels={channels}"
            self._render_metadata(
                codec,
                bitrate,
                genre,
                name,
                self.current_stream_url or "-",
                audio_info,
                description,
                stream_title,
            )
            self.current_codec, self.current_bitrate = codec, bitrate
        except Exception:
            bitrate = normalize_bitrate(self.current_bitrate)
            self._render_metadata(
                self.current_codec or "mp3",
                bitrate,
                self.current_genre or "-",
                self.current_station_name or "-",
                self.current_stream_url or "-",
                f"ice-samplerate=44100;ice-bitrate={bitrate};ice-channels=2",
                self.current_description or "-",
                self.last_stream_title,
            )
        self._update_current_label()

    def handle_player_error(self, message: str) -> None:
        self.current_label.setText(f"Помилка плеєра {message}")

    def change_volume(self, value: int) -> None:
        self.playback.set_volume(value)
        self.settings.setValue("volume", value)
