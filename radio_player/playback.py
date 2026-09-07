"""Playback primitives that keep Qt multimedia lifecycle out of the main window."""

from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from .metadata import probe_stream_title


class PlaybackEngine(QObject):
    """Own the media objects and safely report background ICY title probes."""

    metadata_changed = pyqtSignal()
    player_error = pyqtSignal(str)
    title_probed = pyqtSignal(int, str)

    def __init__(self, user_agent: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._user_agent = user_agent
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.errorOccurred.connect(lambda _error: self.player_error.emit(self.player.errorString()))
        self.player.metaDataChanged.connect(self.metadata_changed)

        self.metadata_timer = QTimer(self)
        self.metadata_timer.setInterval(2000)
        self.metadata_timer.timeout.connect(self.metadata_changed)

    def set_volume(self, value: int) -> None:
        self.audio_output.setVolume(value / 100)

    def play(self, url: QUrl) -> None:
        self.player.stop()
        self.player.setSource(url)
        self.player.play()
        self.metadata_timer.start()

    def resume(self) -> None:
        self.player.play()
        self.metadata_timer.start()

    def pause(self) -> None:
        self.player.pause()

    def start_title_probe(self, url: str, probe_id: int) -> None:
        """Probe outside Qt's GUI thread; the signal queues the result back safely.

        A probe cannot be cancelled while ``requests`` is reading a stream.  The caller
        therefore advances ``probe_id`` for every station change and ignores stale output.
        """
        if not url:
            return
        threading.Thread(
            target=self._probe_title_worker,
            args=(url, probe_id),
            daemon=True,
            name="radio-title-probe",
        ).start()

    def _probe_title_worker(self, url: str, probe_id: int) -> None:
        title = probe_stream_title(url, self._user_agent)
        if title:
            self.title_probed.emit(probe_id, title)
