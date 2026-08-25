"""Helpers for normalizing and reading audio-stream metadata."""

import re

import requests


def normalize_bitrate(bitrate: str) -> str:
    if not bitrate or bitrate == "-":
        return "-"
    try:
        value = float(str(bitrate).strip())
    except (TypeError, ValueError):
        return str(bitrate)
    if value > 2000:
        value /= 1000.0
    return str(int(round(value)))


def clean_stream_title(text: str) -> str:
    cleaned = (text or "").replace("\x00", " ").strip()
    cleaned = cleaned.strip("'\"; ")
    return re.sub(r"\s+", " ", cleaned)


def probe_stream_title(url: str, user_agent: str) -> str:
    """Read the first ICY metadata block and return its stream title, if any."""
    try:
        headers = {"Icy-MetaData": "1", "User-Agent": user_agent}
        with requests.get(url, headers=headers, stream=True, timeout=(5, 10)) as response:
            metaint_raw = response.headers.get("icy-metaint")
            if not metaint_raw:
                return ""
            metaint = int(metaint_raw)
            if metaint <= 0:
                return ""

            response.raw.read(metaint)
            length_byte = response.raw.read(1)
            if not length_byte:
                return ""
            metadata_length = length_byte[0] * 16
            if metadata_length <= 0:
                return ""

            metadata = response.raw.read(metadata_length).decode("latin-1", errors="ignore")
            match = re.search(r"StreamTitle='([^']*)'", metadata, flags=re.IGNORECASE)
            return clean_stream_title(match.group(1)) if match else ""
    except (OSError, ValueError, requests.RequestException):
        return ""
