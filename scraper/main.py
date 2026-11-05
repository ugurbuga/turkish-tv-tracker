import base64
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SECRET_KEY = "turkish-tv-tracker-2026"
ENCRYPTED_URL = "HAEGGxpJRwJFRh1FFggZAkscSEYfXxsfFBwKBR8JXw=="

ENCRYPTED_ATV_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsTFRVFFRxK"
ENCRYPTED_NOW_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVscDhRFFRxK"
ENCRYPTED_KANAL_D_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsZAA0KCRYDQl5V"
ENCRYPTED_SHOW_TV_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsBCQwcEQQDQl5V"
ENCRYPTED_STAR_TV_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsBFQIZEQQDQl5V"
ENCRYPTED_TRT1_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsGExdaSwJDVQ=="
ENCRYPTED_TV8_LOGO = "HAEGGxpJRwJFRh1FFggZAkscSEYfW1sVEhcYW1wDTBoXQVsGF1tFFRxK"

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

CHANNEL_LOGOS = {
    "atv": ENCRYPTED_ATV_LOGO,
    "NOW": ENCRYPTED_NOW_LOGO,
    "Kanal D": ENCRYPTED_KANAL_D_LOGO,
    "Show TV": ENCRYPTED_SHOW_TV_LOGO,
    "Star TV": ENCRYPTED_STAR_TV_LOGO,
    "TRT 1": ENCRYPTED_TRT1_LOGO,
    "TV8": ENCRYPTED_TV8_LOGO,
}

TURKISH_TRANSLATION = str.maketrans({
    "ç": "C",
    "Ç": "C",
    "ğ": "G",
    "Ğ": "G",
    "ı": "I",
    "I": "I",
    "İ": "I",
    "i": "I",
    "ö": "O",
    "Ö": "O",
    "ş": "S",
    "Ş": "S",
    "ü": "U",
    "Ü": "U",
})

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


def xor_encrypt(value):
    if value is None:
        return None

    key = SECRET_KEY.encode("utf-8")
    payload = value.encode("utf-8")
    encrypted = bytes(
        byte ^ key[index % len(key)]
        for index, byte in enumerate(payload)
    )
    return base64.b64encode(encrypted).decode("ascii")


def xor_decrypt(value):
    if value is None:
        return None

    key = SECRET_KEY.encode("utf-8")
    encrypted = base64.b64decode(value.encode("ascii"))
    decrypted = bytes(
        byte ^ key[index % len(key)]
        for index, byte in enumerate(encrypted)
    )
    return decrypted.decode("utf-8")


def normalize_text(value):
    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return normalized.translate(TURKISH_TRANSLATION).upper()


def detect_status(text):
    normalized = normalize_text(text)

    if "FINAL" in normalized:
        return "Final"
    if "BU HAFTA YOK" in normalized:
        return "Bu hafta yok"
    if "YENI BOLUM" in normalized:
        return "Yeni Bölüm"
    if "YENI" in normalized and "BOLUM" in normalized:
        return "Yeni Bölüm"

    return None


def fetch_page():
    resolved_url = xor_decrypt(ENCRYPTED_URL)

    response = requests.get(
        resolved_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,"
                "image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
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


def extract_series_blocks(cell):
    html = str(cell)
    blocks = [html]

    if "---" in html:
        blocks = re.split(r"<br\s*/?>\s*---\s*<br\s*/?>", html, flags=re.IGNORECASE)

    parsed_blocks = []
    for block in blocks:
        if not block.strip():
            continue

        block_soup = BeautifulSoup(block, "html.parser")
        if not block_soup.get_text(strip=True):
            continue

        if block_soup.find("a", href=True):
            parsed_blocks.append(block_soup)

    return parsed_blocks


def resolve_channel_logo(channel):
    encrypted = CHANNEL_LOGOS.get(channel)
    if not encrypted:
        return None
    return xor_decrypt(encrypted)


def parse_series(cell, channel, date_info):
    items = []

    for block in extract_series_blocks(cell):
        link = block.find("a", href=True)
        if not link:
            continue

        name = link.get_text(strip=True)
        if not name:
            continue

        text = block.get_text(" ", strip=True)

        time_match = re.search(
            r"\b(\d{2}:\d{2})\b",
            text
        )

        episode_match = re.search(
            r"(\d+\.?\s*Bölüm)",
            text,
            re.IGNORECASE
        )

        image = block.find("img")

        items.append({
            "name": name,
            "url": xor_encrypt(link.get("href")) if link.get("href") else None,
            "image": xor_encrypt(image.get("src")) if image and image.get("src") else None,
            "channel": channel,
            "channelLogo": xor_encrypt(resolve_channel_logo(channel)) if resolve_channel_logo(channel) else None,
            "day": date_info["day"],
            "date": date_info["date"],
            "time": time_match.group(1) if time_match else None,
            "episode": episode_match.group(1) if episode_match else None,
            "status": detect_status(text),
        })

    return items


def prepare_for_storage(data):
    prepared = {
        "lastUpdated": data["lastUpdated"],
        "seriesCount": data["seriesCount"],
        "series": []
    }

    for item in data["series"]:
        prepared_item = dict(item)
        prepared_item["url"] = item.get("url")
        prepared_item["image"] = item.get("image")
        prepared_item["channelLogo"] = item.get("channelLogo")
        prepared["series"].append(prepared_item)

    return prepared


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
            for item in parse_series(
                cells[index + 1],
                channel,
                date_info
            ):
                series.append(item)

    if not series:
        raise RuntimeError(
            "Hiçbir dizi bulunamadı. JSON güncellenmedi!"
        )

    return {
        "lastUpdated": datetime.now(
            ZoneInfo("Europe/Istanbul")
        ).isoformat(timespec="seconds"),
        "seriesCount": len(series),
        "series": series
    }


def main():
    data = scrape()
    payload = prepare_for_storage(data)

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(f"Toplam {len(payload['series'])} yayın kaydı bulundu.")
    print(f"JSON kaydedildi: {OUTPUT}")


if __name__ == "__main__":
    main()
