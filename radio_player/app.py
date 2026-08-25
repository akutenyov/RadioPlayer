import html
import re
import threading
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
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
from .metadata import clean_stream_title, normalize_bitrate, probe_stream_title
from .widgets import BitrateItem


class RadioApp(QMainWindow):
    probed_title_ready = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Radio Player {APP_VERSION}")
        self.setWindowIcon(self._build_radio_icon())
        self.resize(1200, 780)

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(self.handle_player_error)
        self.media_player.metaDataChanged.connect(self.update_stream_info)

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

        self.pending_stations: list[dict[str, str]] = []
        self.fill_index = 0
        self.column_max_widths: list[int] = []
        self._meta_key_cache: dict[str, Any] = {}
        self._last_metadata_text = ""

        self._build_ui()

        self.fill_timer = QTimer(self)
        self.fill_timer.setInterval(0)
        self.fill_timer.timeout.connect(self._fill_next_batch)

        self.metadata_timer = QTimer(self)
        self.metadata_timer.setInterval(2000)
        self.metadata_timer.timeout.connect(self.update_stream_info)

        self.probed_title_ready.connect(self.on_probed_title_ready)

        self.change_volume(50)
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

    def on_countries_loading_error(self, _message: str) -> None:
        # Початковий короткий список країн залишається доступним без мережі.
        return

    def cleanup_countries_loader(self) -> None:
        if self.countries_worker is not None:
            self.countries_worker.deleteLater()
        if self.countries_thread is not None:
            self.countries_thread.deleteLater()
        self.countries_worker = None
        self.countries_thread = None

    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        search_bar = QHBoxLayout()
        self.country_combo = QComboBox()
        self.country_combo.addItems(self.countries.keys())
        self.country_combo.setCurrentText("Всі країни")

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
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Назва станції", "Країна", "Genre", "Codec", "Bitrate", "URL"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionClicked.connect(self.on_header_clicked)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(self.play_radio)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #2f2f2f; color: #ffffff; gridline-color: #4a4a4a; }"
            "QHeaderView::section { background-color: #242424; color: #ffffff; }"
        )
        main_layout.addWidget(self.table)

        controls_row = QHBoxLayout()


        self.restart_btn = QPushButton("↻")
        self.restart_btn.clicked.connect(self.restart_stream)
        self.restart_btn.setFixedSize(66, 48)

        self.play_pause_btn = QPushButton("\u25B6")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.play_pause_btn.setFixedSize(66, 48)

        button_style = (
            "QPushButton {"
            "font-size: 25px;"
            "font-weight: 700;"
            "color: #111;"
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f9f9f9, stop:1 #cfcfcf);"
            "border: 1px solid #7f7f7f;"
            "border-radius: 8px;"
            "padding-bottom: 2px;"
            "}"
            "QPushButton:pressed {"
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #bcbcbc, stop:1 #e6e6e6);"
            "padding-top: 2px;"
            "padding-bottom: 0px;"
            "}"
        )
        self.restart_btn.setStyleSheet(button_style + "QPushButton { font-size: 28px; font-weight: 900; }")
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

        self.metadata_title_label = QLabel("Metadata")
        self.metadata_title_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 13pt; font-weight: 700;"
        )
        main_layout.addWidget(self.metadata_title_label)

        self.metadata_label = QLabel()
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.metadata_label.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 10pt;")
        self._render_metadata(
            codec="-",
            bitrate="-",
            genre="-",
            name="-",
            url="-",
            audio_info="-",
            description="-",
            stream_title="-",
        )
        main_layout.addWidget(self.metadata_label)

    def toggle_play_pause(self) -> None:
        state = self.media_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_pause_btn.setText("\u25B6")
            return
        if self.current_stream_url:
            self.media_player.play()
            self.metadata_timer.start()
            self.play_pause_btn.setText("\u23F8")
            return
        self.current_label.setText("\u041e\u0431\u0435\u0440\u0456\u0442\u044c \u0441\u0442\u0430\u043d\u0446\u0456\u044e \u0434\u043b\u044f \u0432\u0456\u0434\u0442\u0432\u043e\u0440\u0435\u043d\u043d\u044f")

    def _begin_fill(self, stations: list[dict[str, str]]) -> None:
        self.pending_stations = stations
        self.fill_index = 0
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(stations))

        fm = self.table.fontMetrics()
        self.column_max_widths = []
        for col in range(self.table.columnCount()):
            header_item = self.table.horizontalHeaderItem(col)
            header_text = header_item.text() if header_item is not None else ""
            self.column_max_widths.append(fm.horizontalAdvance(header_text))

        self.fill_timer.start()

    def _fill_next_batch(self) -> None:
        if not self.pending_stations:
            self.fill_timer.stop()
            return

        end_index = min(self.fill_index + TABLE_BATCH_SIZE, len(self.pending_stations))
        table = self.table
        set_item = table.setItem
        col_widths = self.column_max_widths
        pending = self.pending_stations
        advance = table.fontMetrics().horizontalAdvance

        for row in range(self.fill_index, end_index):
            station = pending[row]
            name = station["name"]
            country = station["country"]
            genre = station["genre"]
            codec = station["codec"]
            bitrate = station["bitrate"]
            url = station["url"]

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, station)
            set_item(row, 0, name_item)
            set_item(row, 1, QTableWidgetItem(country))
            set_item(row, 2, QTableWidgetItem(genre))
            set_item(row, 3, QTableWidgetItem(codec))
            set_item(row, 4, BitrateItem(bitrate))
            set_item(row, 5, QTableWidgetItem(url))

            col_widths[0] = max(col_widths[0], advance(name))
            col_widths[1] = max(col_widths[1], advance(country))
            col_widths[2] = max(col_widths[2], advance(genre))
            col_widths[3] = max(col_widths[3], advance(codec))
            col_widths[4] = max(col_widths[4], advance(bitrate))
            col_widths[5] = max(col_widths[5], advance(url))

        self.fill_index = end_index

        if self.fill_index >= len(self.pending_stations):
            self.fill_timer.stop()
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(True)
            self._apply_column_widths()
            self._highlight_active_station()
            self.pending_stations = []

    def _apply_column_widths(self) -> None:
        fm = self.table.fontMetrics()
        extra = fm.horizontalAdvance("0") * 3
        cw = fm.horizontalAdvance("0")
        self.table.setColumnWidth(0, cw * 50)
        for col in range(1, self.table.columnCount()):
            self.table.setColumnWidth(col, self.column_max_widths[col] + extra)
        self.table.setColumnWidth(1, cw * 25)
        self.table.setColumnWidth(2, cw * 25)
        self.table.setColumnWidth(4, cw * 25)
        self.table.setColumnWidth(5, cw * 70)

    def _highlight_active_station(self) -> None:
        active_bg = QBrush(QColor("#ffffff"))
        active_fg = QBrush(QColor("#000000"))
        normal_bg = QBrush(QColor("#2f2f2f"))
        normal_fg = QBrush(QColor("#ffffff"))

        for row in range(self.table.rowCount()):
            url_item = self.table.item(row, 5)
            is_active = bool(url_item and self.current_stream_url and url_item.text().strip() == self.current_stream_url)
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                item.setBackground(active_bg if is_active else normal_bg)
                item.setForeground(active_fg if is_active else normal_fg)

    def _meta_by_key_name(self, key_name: str, metadata: Any | None = None) -> str:
        key = self._meta_key_cache.get(key_name)
        if key is None and key_name not in self._meta_key_cache:
            key = getattr(QMediaMetaData.Key, key_name, None)
            self._meta_key_cache[key_name] = key
        if key is None:
            return ""

        try:
            if metadata is None:
                metadata = self.media_player.metaData()
            value = metadata.value(key)
        except Exception:
            return ""

        if isinstance(value, list):
            filtered = [str(item).strip() for item in value if str(item).strip()]
            return ", ".join(filtered)
        if value is None:
            return ""
        return str(value).strip()

    def _meta_first(self, key_names: list[str], metadata: Any | None = None) -> str:
        for key_name in key_names:
            value = self._meta_by_key_name(key_name, metadata)
            if value:
                return value
        return ""

    def _update_current_label(self) -> None:
        if self.current_station_name == "-":
            return
        title = clean_stream_title(self.last_stream_title)
        base = self.current_station_name if not title or title == "-" else f"{self.current_station_name} | {title}"
        full_text = f"\u0412\u0456\u0434\u0442\u0432\u043e\u0440\u044e\u0454\u0442\u044c\u0441\u044f: {base}"
        visible = full_text if len(full_text) <= 70 else f"{full_text[:67]}..."
        self.current_label.setText(visible)
        self.current_label.setToolTip(full_text if len(full_text) > 70 else "")

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
        rows = [
            ("Codec", codec),
            ("Bitrate", bitrate),
            ("Genre", genre),
            ("Name", name),
            ("Url", url),
            ("Audio-info", audio_info),
            ("Description", description),
            ("StreamTitle", stream_title),
        ]
        snapshot = "\n".join(f"{k}={v}" for k, v in rows)
        if snapshot == self._last_metadata_text:
            return
        self._last_metadata_text = snapshot

        html_rows = []
        for key, value in rows:
            safe_value = html.escape(str(value)).replace("\n", "<br>")
            html_rows.append(
                f"<tr><td style='padding-right:10px; vertical-align:top; font-size:10pt;'><b>{key}</b></td>"
                f"<td style='vertical-align:top; font-size:10pt;'>{safe_value}</td></tr>"
            )
        metadata_html = "<table cellspacing='0' cellpadding='0'>" + "".join(html_rows) + "</table>"
        self.metadata_label.setText(metadata_html)

    def _probe_stream_title_worker(self, url: str, probe_id: int) -> None:
        title = probe_stream_title(url, f"RadioPlayer/{APP_VERSION}")
        if title:
            self.probed_title_ready.emit(probe_id, title)

    def start_stream_title_probe(self) -> None:
        if not self.current_stream_url:
            return
        probe_id = self.stream_probe_id
        threading.Thread(
            target=self._probe_stream_title_worker,
            args=(self.current_stream_url, probe_id),
            daemon=True,
        ).start()

    def on_probed_title_ready(self, probe_id: int, title: str) -> None:
        if probe_id != self.stream_probe_id:
            return
        clean_title = clean_stream_title(title)
        if not clean_title:
            return
        self.last_stream_title = clean_title
        self.update_stream_info()

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
            stream_title = "-"
            if raw_title:
                match = re.search(r"StreamTitle='([^']+)'", raw_title, flags=re.IGNORECASE)
                stream_title = clean_stream_title(match.group(1) if match else raw_title)

            if stream_title == "-" and self.last_stream_title != "-":
                stream_title = self.last_stream_title
            elif stream_title != "-":
                self.last_stream_title = stream_title

            channel_count = self._meta_first(["ChannelCount", "AudioChannelCount"], metadata)
            if channel_count == "1":
                channels = "1"
                channel_label = "mono"
            elif channel_count == "2" or not channel_count:
                channels = "2"
                channel_label = "stereo"
            else:
                channels = channel_count
                channel_label = f"{channel_count} channels"

            audio_info = f"ice-samplerate={sample_rate};ice-bitrate={bitrate};ice-channels={channels}"
            self._render_metadata(codec, bitrate, genre, name, self.current_stream_url or "-", audio_info, description, stream_title)
            self.current_codec = codec
            self.current_bitrate = bitrate
            self._update_current_label()
        except Exception:
            safe_bitrate = normalize_bitrate(self.current_bitrate)
            safe_codec = self.current_codec or "mp3"
            self._render_metadata(
                safe_codec,
                safe_bitrate,
                self.current_genre or "-",
                self.current_station_name or "-",
                self.current_stream_url or "-",
                f"ice-samplerate=44100;ice-bitrate={safe_bitrate};ice-channels=2",
                self.current_description or "-",
                self.last_stream_title,
            )
            self._update_current_label()

    def handle_player_error(self, _error: Any) -> None:
        self.current_label.setText(f"Помилка плеєра {self.media_player.errorString()}")

    def load_data(self) -> None:
        if self.is_loading:
            return

        country_name = self.country_combo.currentText()
        country_code = self.countries.get(country_name, "")
        station_name = self.name_input.text().strip()
        self.is_loading = True
        self.search_btn.setEnabled(False)
        self.current_label.setText("Завантаження станцій...")
        self.status_label.setText(f"Статус: Завантаження | Країна: {country_name}")

        self.loader_thread = QThread(self)
        self.loader_worker = StationsLoader(country_code, station_name)
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

    def on_header_clicked(self, column: int) -> None:
        if column == 4:
            self.table.sortItems(4, self.bitrate_sort_order)
            self.bitrate_sort_order = (
                Qt.SortOrder.AscendingOrder
                if self.bitrate_sort_order == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )
            self._highlight_active_station()
            return

        if column == 5:
            self.table.sortItems(5, self.url_sort_order)
            self.url_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self.url_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            self._highlight_active_station()

    def on_loading_error(self, message: str) -> None:
        self.table.setRowCount(0)
        self.search_btn.setEnabled(True)
        self.current_label.setText(message)
        self.status_label.setText(f"Статус: Помилка | {message}")

    def cleanup_loader(self) -> None:
        if self.loader_worker is not None:
            self.loader_worker.deleteLater()
        if self.loader_thread is not None:
            self.loader_thread.deleteLater()
        self.loader_worker = None
        self.loader_thread = None
        self.is_loading = False

    def play_radio(self, item: QTableWidgetItem) -> None:
        row = item.row()
        name_item = self.table.item(row, 0)
        codec_item = self.table.item(row, 3)
        bitrate_item = self.table.item(row, 4)
        url_item = self.table.item(row, 5)

        if name_item is None or url_item is None:
            self.current_label.setText("Помилка неповні дані станції")
            return

        url = url_item.text().strip()
        name = name_item.text().strip() or "Без назви"

        qurl = QUrl(url)
        if not qurl.isValid() or qurl.scheme() not in {"http", "https"}:
            self.current_label.setText("Помилка некоректний URL потоку")
            return

        station_data = name_item.data(Qt.ItemDataRole.UserRole)
        station_genre = "-"
        station_description = "-"
        if isinstance(station_data, dict):
            station_genre = str(station_data.get("genre") or "-").strip() or "-"
            station_description = str(station_data.get("description") or "-").strip() or "-"

        self.current_stream_url = url
        self.current_station_name = name
        self.current_codec = codec_item.text().strip() if codec_item is not None else "-"
        self.current_bitrate = bitrate_item.text().strip() if bitrate_item is not None else "-"
        self.current_genre = station_genre
        self.current_description = station_description
        self.last_stream_title = "-"
        self.stream_probe_id += 1

        norm_bitrate = normalize_bitrate(self.current_bitrate)
        self._update_current_label()
        self._render_metadata(
            self.current_codec,
            norm_bitrate,
            self.current_genre,
            self.current_station_name,
            self.current_stream_url,
            f"ice-samplerate=44100;ice-bitrate={norm_bitrate};ice-channels=2",
            self.current_description,
            "-",
        )

        self.media_player.stop()
        self.media_player.setSource(qurl)
        self.media_player.play()
        self.play_pause_btn.setText("\u23F8")
        self.metadata_timer.start()
        self.start_stream_title_probe()
        self._highlight_active_station()

    def restart_stream(self) -> None:
        if not self.current_stream_url:
            self.current_label.setText("Немає активного стріму для перезапуску")
            return

        self.last_stream_title = "-"
        self.stream_probe_id += 1
        self.media_player.stop()
        self.media_player.setSource(QUrl(self.current_stream_url))
        self.media_player.play()
        self.play_pause_btn.setText("\u23F8")
        self.metadata_timer.start()
        self.start_stream_title_probe()
        self._highlight_active_station()


    def change_volume(self, value: int) -> None:
        self.audio_output.setVolume(value / 100)

