# RadioPlayer

RadioPlayer is a desktop internet-radio application written in Python with PyQt6. It searches the public [Radio Browser](https://www.radio-browser.info/) catalogue and plays HTTP(S) audio streams.

The interface is currently in Ukrainian.

## Screenshot

![RadioPlayer interface](screen_s_rp.jpg)

## Features

- Search stations by country and name.
- Browse up to 2,000 available stations per search.
- Sort stations by bitrate and stream URL.
- Play, pause, restart, and adjust stream volume.
- Display stream metadata, including codec, bitrate, genre, URL, and the current track title when available.
- Load stations and countries in background threads to keep the interface responsive.
- Continue to offer a short country list if the countries API is unavailable.

## Requirements

- Python 3.10 or later
- Windows, macOS, or Linux with multimedia support provided by Qt
- Internet connection for station discovery and playback

Python dependencies are listed in `requirements.txt`.

## Continuous integration

GitHub Actions runs the offline unit-test suite on every push and pull request
using Python 3.12 on Windows, the primary target platform for this application.

## Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the application dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python radio.py
```

If you use an existing virtual environment, invoke its interpreter directly:

```powershell
.\.venv\Scripts\python.exe radio.py
```

## Tests

The test suite runs without internet access and covers API response handling,
duplicate stream removal, network errors, metadata escaping, and table sorting.

```powershell
python -m unittest discover -s tests -v
```

## Build a Windows executable

Install PyInstaller, then use the maintained spec file:

```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm RadioPlayer.spec
```

The executable will be created in the `dist` directory. You can also build directly from the source file:

```powershell
pyinstaller --noconfirm --onefile --windowed --name RadioPlayer --icon radio_antenna_graphite.ico radio.py
```

Publish the generated executable as a GitHub Release asset instead of adding it
to the Git repository. The local `RadioPlayer_v2.exe` is intentionally ignored.

## Project files

| File | Purpose |
| --- | --- |
| `radio.py` | Application entry point. |
| `radio_player/api.py` | Radio Browser API client and background loaders. |
| `radio_player/metadata.py` | Stream metadata parsing and normalization. |
| `radio_player/widgets.py` | Custom Qt table widgets. |
| `radio_player/app.py` | Main-window UI and playback controller. |
| `requirements.txt` | Runtime Python dependencies. |
| `tests/test_radio.py` | Offline unit tests. |
| `RadioPlayer.spec` | PyInstaller build configuration. |
| `radio_antenna_graphite.ico` | Icon used for the Windows executable. |

## Notes

Station details and stream availability are supplied by third-party radio stations through the Radio Browser API. A stream may be unavailable, change its URL, or omit metadata at any time.
