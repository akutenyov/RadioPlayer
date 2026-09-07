"""Radio Browser API access and background loaders."""

from collections.abc import Iterable

import requests
from PyQt6.QtCore import QObject, pyqtSignal
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://de1.api.radio-browser.info/json/stations/search"
COUNTRIES_URL = "https://de1.api.radio-browser.info/json/countries"
MAX_STATIONS = 2000
DEFAULT_TIMEOUT_SECONDS = 8
APP_VERSION = "2.7"


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.2, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": f"RadioPlayer/{APP_VERSION}"})
    return session


def default_country_map() -> dict[str, str]:
    return {
        "Всі країни": "",
        "Україна": "UA",
        "США": "US",
        "Німеччина": "DE",
        "Британія": "GB",
        "Польща": "PL",
    }


def clean_stations(data: Iterable[object]) -> list[dict[str, str]]:
    """Convert an API response into unique, display-ready station records."""
    cleaned: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for station in data:
        if not isinstance(station, dict):
            continue

        url = (station.get("url_resolved") or station.get("url") or "").strip()
        if not url or url.lower() in seen_urls:
            continue
        seen_urls.add(url.lower())
        cleaned.append(
            {
                "name": (station.get("name") or "Без назви").strip(),
                "country": (station.get("country") or "-").strip() or "-",
                "genre": (station.get("tags") or "-").strip() or "-",
                "codec": str(station.get("codec") or "-").strip() or "-",
                "bitrate": str(station.get("bitrate") if station.get("bitrate") is not None else "-"),
                "url": url,
                "description": str(
                    station.get("homepage")
                    or station.get("favicon")
                    or station.get("state")
                    or station.get("country")
                    or "-"
                ).strip()
                or "-",
            }
        )
    return sorted(cleaned, key=lambda station: station["name"].lower())


def clean_countries(data: Iterable[object]) -> dict[str, str]:
    fetched: dict[str, str] = {"Всі країни": ""}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        code = str(item.get("iso_3166_1") or "").strip().upper()
        if len(code) == 2 and name:
            fetched[name] = code

    if len(fetched) <= 10:
        raise ValueError("API повернув недостатньо країн")

    ordered = {
        "Всі країни": "",
        "Україна": fetched.get("Україна", "UA"),
        "США": fetched.get("США", "US"),
        "Німеччина": fetched.get("Німеччина", "DE"),
        "Британія": fetched.get("United Kingdom") or fetched.get("Great Britain") or "GB",
    }
    for name, code in sorted(fetched.items(), key=lambda item: item[0].lower()):
        if name not in ordered and name not in {"United Kingdom", "Great Britain"}:
            ordered[name] = code
    return ordered


class StationsLoader(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, country_code: str, station_name: str):
        super().__init__()
        self.country_code = country_code
        self.station_name = station_name

    def run(self) -> None:
        params = {"name": self.station_name, "hidebroken": "true", "limit": MAX_STATIONS}
        if self.country_code:
            params["countrycode"] = self.country_code

        session = build_session()
        try:
            response = session.get(API_URL, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                self.error.emit("Некоректна відповідь API")
                return
            self.finished.emit(clean_stations(data))
        except requests.RequestException as exc:
            self.error.emit(f"Помилка мережі: {exc}")
        except ValueError:
            self.error.emit("Помилка обробки JSON")
        finally:
            session.close()


class CountriesLoader(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self) -> None:
        session = build_session()
        try:
            response = session.get(COUNTRIES_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                self.error.emit("Некоректна відповідь API країн")
                return
            self.finished.emit(clean_countries(data))
        except requests.RequestException as exc:
            self.error.emit(f"Помилка завантаження країн: {exc}")
        except ValueError as exc:
            self.error.emit(str(exc))
        finally:
            session.close()
