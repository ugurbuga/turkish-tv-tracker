
import base64
import json
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# Base64 ile gizlenmiş adresler.
_ENDPOINT = "aHR0cHM6Ly90aWFrLmNvbS50ci9pY2VyaWsvY2VrLnBocA=="
_BASE_URL = "aHR0cDovL3RpYWsuY29tLnRyLw=="
_ORIGIN = "aHR0cHM6Ly90aWFrLmNvbS50cg=="


def _decode(value: str) -> str:
    return base64.b64decode(value).decode("utf-8")


def fetch_ratings_report(
    session: requests.Session,
    date: datetime,
    report_type: str = "Top10 5+"
) -> str:

    payload = {
        "nere": "tablo",
        "tarih": f"{date.month}.{date.day}.{date.year}",
        "lang": "tr",
        "url": _decode(_BASE_URL),
        "dosya": report_type
    }

    headers = {
        "Origin": _decode(_ORIGIN),
        "X-Requested-With": "XMLHttpRequest"
    }

    response = session.post(
        _decode(_ENDPOINT),
        data=payload,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def parse_ratings_report(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table")

    if table is None:
        raise ValueError("Reyting rapor tablosu bulunamadı!")

    programs = []

    for row in table.find_all("tr"):
        cells = row.find_all("td")

        if len(cells) != 7:
            continue

        rank_text = cells[0].get_text(strip=True)

        if not rank_text.isdigit():
            continue

        program = {
            "rank": int(rank_text),
            "name": cells[1].get_text(strip=True),
            "channel": cells[2].get_text(strip=True),
            "start_time": cells[3].get_text(strip=True),
            "end_time": cells[4].get_text(strip=True),
            "rating": float(cells[5].get_text(strip=True)),
            "share": float(cells[6].get_text(strip=True))
        }

        programs.append(program)

    return programs


def save_ratings_report(date: datetime, audiences: dict) -> Path:
    result = {
        "date": date.strftime("%Y-%m-%d"),
        "source": "Ratings",
        "audiences": audiences
    }

    output_dir = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "ratings"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{date.strftime('%Y-%m-%d')}.json"

    with output_file.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=4)

    return output_file
