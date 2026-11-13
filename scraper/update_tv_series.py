
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parent.parent

SERIES_FILE = ROOT_DIR / "data" / "tv_series.json"
IMAGES_FILE = ROOT_DIR / "data" / "series_images.json"

DIZI_BASE_URL = "https://1001dizi.net"
TELEVIZYON_BASE_URL = "https://televizyon.com.tr"

DIZI_LIST_URL = f"{DIZI_BASE_URL}/diziler"
TELEVIZYON_CALENDAR_URL = (
    f"{TELEVIZYON_BASE_URL}/haftalik-dizi-takvimi"
)

TELEVIZYON_URL_OVERRIDES = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 25
REQUEST_DELAY = 0.7

ALIASES = {
    "Halef: Köklerin Çağrısı": ["Halef"],
    "Kod Adı: Kırlangıç": ["Kod Adı Kırlangıç"],
    "Daha On Yedi": ["Daha 17"],
}

BASE_FIELDS = [
    "name",
    "handle",
    "channelId",
    "uploadsPlaylistId",
    "videosPath",
    "posterPath",
]

METADATA_FIELDS = [
    "seasonCount",
    "productionCompany",
    "director",
    "writers",
    "history",
    "synopsis",
    "genre",
    "cast",
]


def normalize_name(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.lower().replace("ı", "i")
    return re.sub(r"[^a-z0-9]", "", value)


def get_soup(session, url):
    response = session.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def read_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_if_changed(path, data):
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    if path.exists():
        current = path.read_text(encoding="utf-8")

        if current == serialized:
            print(f"Değişiklik yok: {path.name}")
            return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")

    print(f"Güncellendi: {path.name}")
    return True


def get_series_aliases(name):
    return [name] + ALIASES.get(name, [])


def extract_labeled_values(block):
    result = {}

    for strong in block.find_all("strong"):
        label = strong.get_text(" ", strip=True)
        next_element = strong.next_sibling

        while next_element is not None:
            if getattr(next_element, "name", None) == "br":
                break

            if getattr(next_element, "name", None) in (
                "strong", "h2", "h3"
            ):
                break

            value = (
                next_element.get_text(" ", strip=True)
                if hasattr(next_element, "get_text")
                else str(next_element).strip()
            )

            if value:
                result[label.rstrip(":")] = value
                break

            next_element = next_element.next_sibling

    return result


def extract_heading_content(block, keywords):
    for heading in block.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(" ", strip=True).lower()

        if not any(keyword in heading_text for keyword in keywords):
            continue

        values = []

        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in (
                "h2", "h3", "h4"
            ):
                break

            if getattr(sibling, "name", None) == "br":
                continue

            value = (
                sibling.get_text(" ", strip=True)
                if hasattr(sibling, "get_text")
                else str(sibling).strip()
            )

            if value:
                values.append(value)

        return " ".join(values).strip() or None

    return None


def extract_history(block):
    for heading in block.find_all(["h2", "h3", "h4"]):
        if "tarihçe" not in heading.get_text(
            " ", strip=True
        ).lower():
            continue

        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in (
                "h2", "h3", "h4"
            ):
                break

            if getattr(sibling, "name", None) == "ul":
                return [
                    item.get_text(" ", strip=True)
                    for item in sibling.find_all(
                        "li", recursive=False
                    )
                ]

    return []


def split_people(value):
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[,;\n]+", value)
        if item.strip()
    ]


def scrape_1001_series_list(session):
    print("\n[1001DIZI] Dizi listesi alınıyor...")

    soup = get_soup(session, DIZI_LIST_URL)
    result = {}

    for item in soup.select("li"):
        title_link = item.select_one("h2.catg_titile a[href]")

        if not title_link:
            continue

        name = title_link.get_text(" ", strip=True)

        result[normalize_name(name)] = {
            "name": name,
            "url": urljoin(DIZI_BASE_URL, title_link["href"])
        }

    print(f"[1001DIZI] {len(result)} dizi bulundu.")
    return result


def scrape_1001_detail(session, item):
    soup = get_soup(session, item["url"])
    block = soup.select_one(".single_page_content")

    if not block:
        raise ValueError(
            f"Detay içeriği bulunamadı: {item['url']}"
        )

    labeled = extract_labeled_values(block)

    return {
        "seasonCount": (
            int(labeled["Sezon"])
            if labeled.get("Sezon", "").isdigit()
            else None
        ),
        "productionCompany": (
            labeled.get("Yapım Firması", "").rstrip(" »")
            or None
        ),
        "director": split_people(labeled.get("Yönetmen")),
        "writers": split_people(labeled.get("Senaryo")),
        "history": extract_history(block),
        "synopsis": extract_heading_content(
            block, ["konusu"]
        ),
        "genre": labeled.get("Tür"),
    }


def scrape_televizyon_series_urls(session):
    print("\n[TELEVIZYON] Dizi sayfaları aranıyor...")

    soup = get_soup(session, TELEVIZYON_CALENDAR_URL)
    result = {}

    for link in soup.select('a[href^="/dizi/"]'):
        name = link.get_text(" ", strip=True)

        if not name:
            continue

        normalized = normalize_name(name)
        url = urljoin(TELEVIZYON_BASE_URL, link["href"])

        result[normalized] = url

        print(
            f"[TELEVIZYON] TAKVİM DİZİSİ: "
            f"'{name}' -> '{normalized}' -> {url}"
        )

    print(
        f"[TELEVIZYON] {len(result)} dizi sayfası bulundu."
    )

    return result


def extract_televizyon_cast(soup):
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(
            " ", strip=True
        ).lower()

        if "oyuncu kadrosu" not in heading_text:
            continue

        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in (
                "h2", "h3", "h4"
            ):
                break

            if getattr(sibling, "name", None) != "div":
                continue

            cast = []

            for card in sibling.find_all(
                "div", recursive=False
            ):
                actor_element = card.select_one(
                    ".text-base.font-medium"
                )

                character_element = card.select_one(
                    ".text-xs"
                )

                if not actor_element:
                    continue

                actor = actor_element.get_text(
                    " ", strip=True
                )

                character = (
                    character_element.get_text(
                        " ", strip=True
                    )
                    if character_element else ""
                )

                character = re.sub(
                    r"\s*karakteri\s*$",
                    "",
                    character,
                    flags=re.IGNORECASE
                ).strip()

                if actor:
                    cast.append({
                        "character": character or None,
                        "actor": actor
                    })

            return cast

    return []


def find_televizyon_url(name, television_urls):
    aliases = get_series_aliases(name)

    for alias in aliases:
        normalized = normalize_name(alias)
        url = television_urls.get(normalized)

        if url:
            print(
                f"[TELEVIZYON] EŞLEŞME: "
                f"'{name}' == '{alias}' "
                f"-> '{normalized}'"
            )
            return url, "TAKVİM"

    print(
        f"[TELEVIZYON] TAKVİMDE EŞLEŞME YOK: "
        f"'{name}' -> "
        f"{[normalize_name(alias) for alias in aliases]}"
    )

    override_url = TELEVIZYON_URL_OVERRIDES.get(name)

    if override_url:
        return override_url, "OVERRIDE"

    slug = unicodedata.normalize("NFKD", name)
    slug = "".join(
        char for char in slug
        if not unicodedata.combining(char)
    )
    slug = slug.lower().replace("ı", "i")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")

    generated_url = f"{TELEVIZYON_BASE_URL}/dizi/{slug}"

    print(
        f"[TELEVIZYON] OTOMATİK URL: "
        f"'{name}' -> '{slug}' -> {generated_url}"
    )

    return generated_url, "OTOMATİK"

def main():
    print("\n========== TV SERIES DATA UPDATE ==========")

    series = read_json(SERIES_FILE, [])
    images = read_json(IMAGES_FILE, {})

    if not series:
        raise ValueError(
            "tv_series.json boş veya bulunamadı."
        )

    session = requests.Session()

    source_list = {}
    television_urls = {}

    try:
        source_list = scrape_1001_series_list(session)
    except Exception as error:
        print(f"[1001DIZI] Liste alınamadı: {error}")

    try:
        television_urls = scrape_televizyon_series_urls(
            session
        )
    except Exception as error:
        print(f"[TELEVIZYON] Liste alınamadı: {error}")

    for target in series:
        name = target["name"]

        cleaned = {
            key: target[key]
            for key in BASE_FIELDS
            if key in target
        }

        # Önceki metadata verilerini koru.
        for key in METADATA_FIELDS:
            if key in target:
                cleaned[key] = target[key]

        # 1001dizi verileri
        source_item = next(
            (
                source_list.get(normalize_name(alias))
                for alias in get_series_aliases(name)
                if source_list.get(normalize_name(alias))
            ),
            None
        )

        if source_item:
            try:
                detail = scrape_1001_detail(
                    session, source_item
                )

                cleaned.update(detail)

                print(f"[1001DIZI] OK: {name}")

            except Exception as error:
                print(
                    f"[1001DIZI] HATA: {name} - {error}"
                )
        else:
            print(f"[1001DIZI] BULUNAMADI: {name}")

        time.sleep(REQUEST_DELAY)

        # Televizyon.com.tr oyuncu kadrosu
        television_url, url_source = find_televizyon_url(
            name,
            television_urls
        )

        print(
            f"[TELEVIZYON] URL DENENİYOR "
            f"({url_source or 'KAYNAK BULUNAMADI'}): "
            f"{name} -> {television_url or 'URL BULUNAMADI'}"
        )

        if television_url:
            try:
                soup = get_soup(session, television_url)
                cast = extract_televizyon_cast(soup)

                if cast:
                    cleaned["cast"] = cast

                    print(
                        f"[TELEVIZYON] OK: {name} "
                        f"({len(cast)} oyuncu)"
                    )
                else:
                    print(
                        f"[TELEVIZYON] KADRO BULUNAMADI: "
                        f"{name} - mevcut veri korundu."
                    )

            except Exception as error:
                print(
                    f"[TELEVIZYON] HATA: {name} - {error} "
                    f"(mevcut kadro korundu)"
                )

        else:
            print(
                f"[TELEVIZYON] BULUNAMADI: {name} "
                f"(mevcut kadro korundu)"
            )

        time.sleep(REQUEST_DELAY)

        poster = images.get(name)

        if poster:
            cleaned["posterPath"] = poster

        target.clear()
        target.update(cleaned)

    write_json_if_changed(SERIES_FILE, series)

    print("\n========== UPDATE COMPLETED ==========")


if __name__ == "__main__":
    main()
