"""Safe rendering of stream metadata in a Qt rich-text label."""

from __future__ import annotations

import html

from PyQt6.QtWidgets import QLabel


class MetadataView:
    """Render only changed metadata and escape all stream-controlled values."""

    def __init__(self, label: QLabel) -> None:
        self.label = label
        self._last_snapshot = ""

    def render(
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
            ("Codec", codec), ("Bitrate", bitrate), ("Genre", genre), ("Name", name),
            ("Url", url), ("Audio-info", audio_info), ("Description", description), ("StreamTitle", stream_title),
        ]
        snapshot = "\n".join(f"{key}={value}" for key, value in rows)
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot
        html_rows = []
        for key, value in rows:
            safe_value = html.escape(str(value)).replace("\n", "<br>")
            html_rows.append(
                f"<tr><td style='padding-right:10px; vertical-align:top; font-size:10pt;'><b>{key}</b></td>"
                f"<td style='vertical-align:top; font-size:10pt;'>{safe_value}</td></tr>"
            )
        self.label.setText("<table cellspacing='0' cellpadding='0'>" + "".join(html_rows) + "</table>")
