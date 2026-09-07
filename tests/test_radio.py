"""Unit tests for RadioPlayer that do not require a network connection."""

import os
import unittest
from unittest.mock import Mock, patch

import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTableWidgetItem

from radio_player import api, metadata
from radio_player.app import RadioApp
from radio_player.widgets import BitrateItem


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.closed = False

    def get(self, *_args, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


class StationsLoaderTests(unittest.TestCase):
    def test_loader_filters_deduplicates_and_sorts_api_response(self):
        response = FakeResponse(
            [
                {
                    "name": "Zulu",
                    "url": "https://example.com/z",
                    "country": "UA",
                    "tags": "rock",
                    "codec": "MP3",
                    "bitrate": 128,
                },
                {"name": "Duplicate", "url_resolved": "HTTPS://EXAMPLE.COM/Z", "country": "UA"},
                {"name": "Alpha", "url_resolved": "https://example.com/a", "state": "Kyiv"},
                {"name": "No stream", "country": "UA"},
            ]
        )
        session = FakeSession(response=response)
        loader = api.StationsLoader("UA", "")
        stations, errors = [], []
        loader.finished.connect(stations.append)
        loader.error.connect(errors.append)

        with patch.object(api, "build_session", return_value=session):
            loader.run()

        self.assertEqual(errors, [])
        self.assertTrue(session.closed)
        self.assertEqual([station["name"] for station in stations[0]], ["Alpha", "Zulu"])
        self.assertEqual(stations[0][0]["description"], "Kyiv")

    def test_loader_reports_invalid_api_payload(self):
        loader = api.StationsLoader("", "")
        errors = []
        loader.error.connect(errors.append)

        with patch.object(api, "build_session", return_value=FakeSession(FakeResponse({"stations": []}))):
            loader.run()

        self.assertEqual(errors, ["Некоректна відповідь API"])

    def test_loader_reports_network_error(self):
        loader = api.StationsLoader("", "")
        errors = []
        loader.error.connect(errors.append)

        with patch.object(
            api,
            "build_session",
            return_value=FakeSession(error=requests.ConnectionError("offline")),
        ):
            loader.run()

        self.assertEqual(len(errors), 1)
        self.assertIn("Помилка мережі", errors[0])


class CountriesLoaderTests(unittest.TestCase):
    def test_country_loader_builds_prioritized_country_list(self):
        response = FakeResponse(
            [
                {"name": "Ukraine", "iso_3166_1": "UA"},
                {"name": "United Kingdom", "iso_3166_1": "GB"},
                {"name": "Australia", "iso_3166_1": "AU"},
                {"name": "Brazil", "iso_3166_1": "BR"},
                {"name": "Canada", "iso_3166_1": "CA"},
                {"name": "Denmark", "iso_3166_1": "DK"},
                {"name": "Estonia", "iso_3166_1": "EE"},
                {"name": "France", "iso_3166_1": "FR"},
                {"name": "Greece", "iso_3166_1": "GR"},
                {"name": "Hungary", "iso_3166_1": "HU"},
                {"name": "India", "iso_3166_1": "IN"},
            ]
        )
        countries, errors = [], []
        loader = api.CountriesLoader()
        loader.finished.connect(countries.append)
        loader.error.connect(errors.append)

        with patch.object(api, "build_session", return_value=FakeSession(response)):
            loader.run()

        self.assertEqual(errors, [])
        self.assertEqual(countries[0]["Всі країни"], "")
        self.assertEqual(countries[0]["Британія"], "GB")
        self.assertEqual(countries[0]["Australia"], "AU")


class ApiDataCleaningTests(unittest.TestCase):
    def test_clean_stations_prefers_resolved_url_and_uses_safe_defaults(self):
        stations = api.clean_stations(
            [
                {
                    "name": "  Beta FM  ",
                    "url": "https://fallback.example/stream",
                    "url_resolved": " https://resolved.example/stream ",
                    "country": " ",
                    "tags": "",
                    "codec": "",
                    "bitrate": None,
                },
                {"name": "Alpha FM", "url": "https://alpha.example/stream"},
            ]
        )

        self.assertEqual([station["name"] for station in stations], ["Alpha FM", "Beta FM"])
        self.assertEqual(stations[1]["url"], "https://resolved.example/stream")
        self.assertEqual(stations[1]["country"], "-")
        self.assertEqual(stations[1]["genre"], "-")
        self.assertEqual(stations[1]["codec"], "-")
        self.assertEqual(stations[1]["bitrate"], "-")

    def test_clean_countries_normalizes_codes_and_rejects_small_payload(self):
        with self.assertRaisesRegex(ValueError, "недостатньо країн"):
            api.clean_countries([{"name": "Ukraine", "iso_3166_1": "ua"}])

        payload = [
            {"name": f"Country {index}", "iso_3166_1": f"x{index}"}
            for index in range(10)
        ]
        countries = api.clean_countries(payload)

        self.assertEqual(countries["Country 0"], "X0")
        self.assertEqual(list(countries)[0], "Всі країни")


class MetadataTests(unittest.TestCase):
    def test_normalize_bitrate_handles_kilobits_bits_and_invalid_values(self):
        self.assertEqual(metadata.normalize_bitrate("128"), "128")
        self.assertEqual(metadata.normalize_bitrate("128000"), "128")
        self.assertEqual(metadata.normalize_bitrate("128.5"), "128")
        self.assertEqual(metadata.normalize_bitrate("unknown"), "unknown")
        self.assertEqual(metadata.normalize_bitrate("-"), "-")

    def test_clean_stream_title_removes_control_characters_quotes_and_extra_space(self):
        self.assertEqual(
            metadata.clean_stream_title("  '\x00Artist   –   Track; '  "),
            "Artist – Track",
        )

    def test_probe_stream_title_returns_empty_string_for_invalid_metadata_interval(self):
        response = Mock()
        response.headers = {"icy-metaint": "not-a-number"}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.object(metadata.requests, "get", return_value=response):
            self.assertEqual(metadata.probe_stream_title("https://example.com/stream", "test-agent"), "")


class UiBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(RadioApp, "load_countries"), patch.object(RadioApp, "load_data"):
            self.window = RadioApp()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_metadata_html_is_escaped(self):
        self.window._render_metadata(
            "mp3",
            "128",
            "<genre>",
            "Station",
            "https://example.com",
            "-",
            "<script>alert(1)</script>",
            "-",
        )

        rendered = self.window.metadata_label.text()
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_bitrate_items_sort_numerically(self):
        items = [BitrateItem("320"), BitrateItem("64"), BitrateItem("128")]
        self.assertEqual([item.text() for item in sorted(items)], ["64", "128", "320"])

    def test_url_header_sorts_the_url_column(self):
        self.window.table.setSortingEnabled(False)
        self.window.table.setRowCount(2)
        self.window.current_stream_url = ""
        self.window.table.setItem(0, 0, QTableWidgetItem("Alpha"))
        self.window.table.setItem(0, 5, QTableWidgetItem("https://z.example"))
        self.window.table.setItem(1, 0, QTableWidgetItem("Zulu"))
        self.window.table.setItem(1, 5, QTableWidgetItem("https://a.example"))

        self.window.on_header_clicked(5)

        self.assertEqual(self.window.table.item(0, 5).text(), "https://a.example")


if __name__ == "__main__":
    unittest.main(verbosity=2)
