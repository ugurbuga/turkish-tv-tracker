import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://1001dizi.net/m-kanallar"
OUTPUT = Path("data/series.json")

CHANNELS = [
    "atv",
    "NOW",
    "Kanal D",
    "Show TV",
    "Star TV",
    "TRT 1",
    "TV8"
]

MONTHS = {
    "Ocak": 1,
    "Şubat": 2,
    "Mart": 3,
    "Nisan": 4,
    "Mayıs": 5,
    "Haziran": 6,
    "Temmuz": 7,
    "Ağustos": 8,
    "Eylül": 9,
    "Ekim": 10,
    "Kasım": 11,
    "Aralık": 12
}

def fetch_page():
    response = requests.get(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=30
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def parse_date(text):
    match = re.search(
        r"(\d{1,2})\s+(\w+)\s+(\w+)",
        text
    )

    if not match:
        return None

    day, month, weekday = match.groups()

    year = datetime.now(
        ZoneInfo("Europe/Istanbul")
    ).year

    return {
        "date": datetime(
            year,
            MONTHS[month],
            int(day)
        ).date().isoformat(),
        "day": weekday
    }


def parse_series(cell, channel, date_info):
    link = cell.find("a")

    if not link:
        return None

    name = link.get_text(strip=True)

    if not name:
        return None

    text = cell.get_text(" ", strip=True)

    time_match = re.search(
        r"\b(\d{2}:\d{2})\b",
        text
    )

    episode_match = re.search(
        r"(\d+\.?\s*Bölüm)",
        text,
        re.IGNORECASE
    )

    status = None

    if "FİNAL" in text.upper():
        status = "Final"
    elif "BU HAFTA YOK" in text.upper():
        status = "Bu hafta yok"
    elif "YENİ BÖLÜM" in text.upper():
        status = "Yeni Bölüm"

    image = cell.find("img")

    return {
        "name": name,
        "url": link.get("href"),
        "image": image.get("src") if image else None,
        "channel": channel,
        "day": date_info["day"],
        "date": date_info["date"],
        "time": time_match.group(1) if time_match else None,
        "episode": episode_match.group(1) if episode_match else None,
        "status": status
    }


def scrape():
    soup = fetch_page()

    table = soup.find("table")

    if not table:
        raise RuntimeError("Dizi tablosu bulunamadı!")

    rows = table.find_all("tr")

    series = []

    for row in rows:
        cells = row.find_all("td", recursive=False)

        if len(cells) != 8:
            continue

        date_info = parse_date(
            cells[0].get_text(" ", strip=True)
        )

        if not date_info:
            continue

        for index, channel in enumerate(CHANNELS):
            item = parse_series(
                cells[index + 1],
                channel,
                date_info
            )

            if item:
                series.append(item)

    if not series:
        raise RuntimeError(
            "Hiçbir dizi bulunamadı. JSON güncellenmedi!"
        )

    return {
        "source": "1001dizi.net",
        "url": URL,
        "lastUpdated": datetime.now(
            ZoneInfo("Europe/Istanbul")
        ).isoformat(timespec="seconds"),
        "seriesCount": len(series),
        "series": series
    }


def main():
    data = scrape()

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(f"Toplam {len(data['series'])} yayın kaydı bulundu.")
    print(f"JSON kaydedildi: {OUTPUT}")


if __name__ == "__main__":
    main()
