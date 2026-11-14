import base64
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from crypto_utils import xor_encrypt, xor_decrypt


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
NEWS_DIR = DATA_DIR / "news"
STATE_FILE = DATA_DIR / "news_scraper_state.json"

CATEGORY_URL = base64.b64decode(
    "aHR0cHM6Ly93d3cuYmlyc2VuYWx0dW50YXMuY29tL2NhdGVnb3J5L2Rpemkv"
).decode("utf-8")

ALLOWED_DOMAINS = {
    base64.b64decode("Ymlyc2VuYWx0dW50YXMuY29t").decode("utf-8"),
    base64.b64decode("d3d3LmJpcnNlbmFsdHVudGFzLmNvbQ==").decode("utf-8"),
}

RELATED_CARD_CLASS = base64.b64decode(
    "Ymlyc2VuLXJlbGF0ZWQtY2FyZA=="
).decode("utf-8")

SOURCE_NAME = "News"
PAGE_COUNT = 1
BACKFILL_START_PAGE = 6
RETRY_ATTEMPTS = 5
RETRY_DELAY = 5
GEMINI_DELAY = 5

PREFERRED_MODELS = [
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
    "models/gemini-2.5-flash-lite",
]

GEMINI_MODELS_URL = base64.b64decode(
    "aHR0cHM6Ly9nZW5lcmF0aXZlbGFuZ3VhZ2UuZ29vZ2xlYXBpcy5jb20vdjFiZXRhL21vZGVscw=="
).decode("utf-8")

GEMINI_API_BASE = base64.b64decode(
    "aHR0cHM6Ly9nZW5lcmF0aXZlbGFuZ3VhZ2UuZ29vZ2xlYXBpcy5jb20vdjFiZXRhLw=="
).decode("utf-8")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

GEMINI_MODEL = None

load_dotenv(dotenv_path=ROOT_DIR / ".env")


def request_with_retry(method, url, **kwargs):
    last_error = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = method(url, **kwargs)
            response.raise_for_status()
            return response

        except requests.RequestException as error:
            last_error = error

            print(
                f"İstek hatası ({attempt}/{RETRY_ATTEMPTS}): "
                f"{type(error).__name__}: {str(error)[:250]}"
            )

            if attempt < RETRY_ATTEMPTS:
                print(f"{RETRY_DELAY} saniye sonra tekrar denenecek.")
                time.sleep(RETRY_DELAY)

    raise last_error


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", value).strip()


def article_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def normalize_url(url):
    url = urldefrag(url.strip())[0]
    parsed = urlparse(url)

    return parsed._replace(
        query="",
        fragment=""
    ).geturl().rstrip("/") + "/"



def decode_url_value(value, field_name="URL", normalize=False):
    if not value:
        return value

    value = str(value).strip()
    parsed = urlparse(value)

    if parsed.scheme in ("http", "https") and parsed.netloc:
        return normalize_url(value) if normalize else value

    candidates = [value]
    if value.endswith("/"):
        candidates.append(value[:-1])

    for candidate in candidates:
        try:
            decoded = xor_decrypt(candidate)
            parsed = urlparse(decoded)

            if parsed.scheme in ("http", "https") and parsed.netloc:
                return normalize_url(decoded) if normalize else decoded
        except Exception:
            continue

    raise ValueError(f"{field_name} çözülemedi.")


def decode_source_url(value):
    if not value:
        raise ValueError("sourceUrl boş.")

    return decode_url_value(
        value,
        field_name="sourceUrl",
        normalize=True
    )


def encode_url_value(value, field_name="URL", normalize=False):
    if not value:
        return value

    decoded = decode_url_value(
        value,
        field_name=field_name,
        normalize=normalize
    )

    return xor_encrypt(decoded)


def decode_image_fields(item):
    if item.get("imageUrl"):
        item["imageUrl"] = decode_url_value(
            item["imageUrl"],
            field_name="imageUrl"
        )

    images = item.get("images")
    if isinstance(images, list):
        item["images"] = [
            decode_url_value(image, field_name="images")
            if image else image
            for image in images
        ]

    return item


def is_article_url(url):
    parsed = urlparse(url)

    if parsed.hostname not in ALLOWED_DOMAINS:
        return False

    path = parsed.path.lower()

    if "/category/" in path or "/page/" in path:
        return False

    return "/dizi/" in path and path != "/dizi/"


def parse_date(value):
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        pass

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).isoformat()
    except (TypeError, ValueError):
        return None


def get_archive_date(item):
    for field in ("publishedAt", "fetchedAt"):
        value = item.get(field)

        if not value:
            continue

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).date().isoformat()
        except (TypeError, ValueError):
            continue

    return datetime.now(timezone.utc).date().isoformat()


def get_image_from_card(card, page_url):
    if not card:
        return None

    image = card.find("img")

    if not image:
        return None

    image_url = (
        image.get("data-src")
        or image.get("data-lazy-src")
        or image.get("data-original")
        or image.get("src")
    )

    if not image_url and image.get("srcset"):
        image_url = image["srcset"].split(",")[0].strip().split(" ")[0]

    if not image_url:
        return None

    return urljoin(page_url, image_url)


def fetch_listing_page(page_number):
    if page_number == 1:
        url = CATEGORY_URL
    else:
        url = urljoin(CATEGORY_URL, f"page/{page_number}/")

    response = SESSION.get(
        url,
        timeout=(15, 40)
    )

    if response.status_code == 404:
        print(f"Sayfa {page_number} bulunamadı.")
        return None

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    seen = set()

    cards = soup.select("article, .jeg_post, .post")

    for card in cards:
        link = card.select_one(
            ".jeg_post_title a, .entry-title a, h2 a, h3 a"
        )

        if not link:
            continue

        title = clean_text(link.get_text())

        article_url = normalize_url(
            urljoin(url, link.get("href", ""))
        )

        if not title or not is_article_url(article_url):
            continue

        if article_url in seen:
            continue

        seen.add(article_url)

        date_element = card.find("time")
        date = None

        if date_element:
            date = parse_date(
                date_element.get("datetime")
                or date_element.get_text(" ", strip=True)
            )

        description_element = card.select_one(
            ".jeg_post_excerpt, .entry-summary, .post-excerpt"
        )

        description = (
            clean_text(description_element.get_text())
            if description_element else ""
        )

        articles.append({
            "sourceTitle": title,
            "sourceUrl": article_url,
            "sourceDescription": description[:1500],
            "imageUrl": get_image_from_card(card, url),
            "images": [],
            "publishedAt": date,
            "articleText": "",
        })

    return articles


def fetch_all_articles():
    print("\n========== CATEGORY SCAN ==========")

    all_articles = {}

    for page_number in range(1, PAGE_COUNT + 1):
        print(f"\nSayfa {page_number}/{PAGE_COUNT} taranıyor...")

        try:
            articles = request_listing_with_retry(page_number)

            if articles is None:
                continue

            for article in articles:
                all_articles[article["sourceUrl"]] = article

            print("Bulunan:", len(articles))
            print("Benzersiz toplam:", len(all_articles))

        except Exception as error:
            print(
                f"Sayfa {page_number} taranamadı:",
                type(error).__name__,
                str(error)[:300]
            )

    return list(all_articles.values())


def request_listing_with_retry(page_number):
    last_error = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return fetch_listing_page(page_number)

        except requests.RequestException as error:
            last_error = error

            print(
                f"Liste sayfası hatası ({attempt}/{RETRY_ATTEMPTS}):",
                str(error)[:250]
            )

            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    raise last_error


def get_image_url(image, page_url):
    image_url = (
        image.get("data-src")
        or image.get("data-lazy-src")
        or image.get("data-original")
        or image.get("src")
    )

    if not image_url and image.get("srcset"):
        image_url = (
            image["srcset"].split(",")[0].strip().split(" ")[0]
        )

    if not image_url:
        return None

    image_url = urljoin(page_url, image_url)

    if not image_url.startswith(("http://", "https://")):
        return None

    return image_url


def fetch_article_detail(article):
    response = request_with_retry(
        SESSION.get,
        article["sourceUrl"],
        timeout=(15, 40)
    )

    soup = BeautifulSoup(response.text, "html.parser")

    image_meta = soup.select_one(
        'meta[property="og:image"]'
    )

    if image_meta and image_meta.get("content"):
        article["imageUrl"] = urljoin(
            article["sourceUrl"],
            image_meta["content"]
        )

    for selector in (
        'meta[property="article:published_time"]',
        'meta[name="date"]',
        'meta[itemprop="datePublished"]',
    ):
        element = soup.select_one(selector)

        if element and element.get("content"):
            article["publishedAt"] = (
                parse_date(element["content"])
                or article.get("publishedAt")
            )
            break

    if not article.get("publishedAt"):
        time_element = soup.find("time")

        if time_element:
            article["publishedAt"] = parse_date(
                time_element.get("datetime")
                or time_element.get_text(" ", strip=True)
            )

    selectors = [
        ".ba-entry-content",
        ".entry-content",
        ".jeg_post_content",
        ".post-content",
        ".td-post-content",
        ".article-content",
        "article .content",
        "main article",
        "article",
    ]

    content = None

    for selector in selectors:
        candidates = soup.select(selector)

        if candidates:
            candidate = max(
                candidates,
                key=lambda item: len(item.get_text(" ", strip=True))
            )

            if len(candidate.get_text(" ", strip=True)) > 200:
                content = candidate
                break

    article["images"] = []

    if content:
        cover = content.select_one("img.wp-post-image")

        if not article.get("imageUrl") and cover:
            article["imageUrl"] = get_image_url(
                cover,
                article["sourceUrl"]
            )

        seen_images = set()

        for image in content.find_all("img"):
            if image.find_parent(class_=RELATED_CARD_CLASS):
                continue

            image_url = get_image_url(
                image,
                article["sourceUrl"]
            )

            if not image_url:
                continue

            if image_url == article.get("imageUrl"):
                continue

            if image_url in seen_images:
                continue

            seen_images.add(image_url)
            article["images"].append(image_url)

        text_content = BeautifulSoup(
            str(content),
            "html.parser"
        )

        for unwanted in text_content.select(
            "script, style, nav, footer, iframe, "
            ".sharedaddy, .jp-relatedposts, .related-posts, "
            ".ads, .advertisement, .social-share, "
            f".{RELATED_CARD_CLASS}"
        ):
            unwanted.decompose()

        paragraphs = [
            clean_text(p.get_text(" ", strip=True))
            for p in text_content.find_all("p")
        ]

        paragraphs = [
            paragraph
            for paragraph in paragraphs
            if len(paragraph) > 30
        ]

        article_text = "\n".join(paragraphs)

        if not article_text:
            article_text = clean_text(
                text_content.get_text(" ", strip=True)
            )

        article["articleText"] = article_text[:12000]

    if (
        not article.get("sourceDescription")
        and article.get("articleText")
    ):
        article["sourceDescription"] = (
            article["articleText"][:1200]
        )

    return article


def get_gemini_model(api_key):
    global GEMINI_MODEL

    if GEMINI_MODEL:
        return GEMINI_MODEL

    response = request_with_retry(
        SESSION.get,
        GEMINI_MODELS_URL,
        headers={"x-goog-api-key": api_key},
        timeout=(15, 40)
    )

    models = response.json().get("models", [])

    available = {
        model["name"]
        for model in models
        if "generateContent" in model.get(
            "supportedGenerationMethods", []
        )
    }

    for preferred in PREFERRED_MODELS:
        if preferred in available:
            GEMINI_MODEL = preferred
            print("Gemini modeli:", GEMINI_MODEL)
            return GEMINI_MODEL

    raise RuntimeError("Tercih edilen Gemini modelleri bulunamadı.")


def build_prompt(article):
    source_text = (
        article.get("articleText")
        or article.get("sourceDescription")
        or article["sourceTitle"]
    )

    return f"""
Bir Türk televizyon ve dizi haber uygulamasının profesyonel editörüsün.

Görevin, aşağıdaki kaynak haber metnini özgün bir Türkçe haber içeriğine
dönüştürmek ve haber için yeni bir başlık oluşturmaktır.

Kurallar:
- Kaynak metni özetleme; haberin tamamını özgün biçimde yeniden yaz.
- Kaynaktaki cümleleri farklı, doğal ve akıcı ifadelerle yeniden kur.
- Ürettiğin haberin metin uzunluğu, kaynak haber metninin %50 ile %150'si
  arasında olmalıdır. Bu sınırın dışına çıkma.
- Uzunluğu hesaplarken HTML etiketlerini dikkate alma; yalnızca okuyucuya
  görünen metni esas al.
- Kaynak metin kısaysa gereksiz yere uzatma; uzunsa önemli ayrıntıları
  atlayarak aşırı kısaltma.
- Kaynaktaki önemli bilgileri, ayrıntıları, açıklamaları ve olayların
  sıralamasını koru.
- Yalnızca kaynakta bulunan bilgileri kullan. Yeni bilgi, kişi, tarih,
  olay, açıklama veya yorum ekleme.
- Kaynaktaki iddiaların kesinlik derecesini koru. İddiaları doğrulanmış
  bilgi gibi sunma.
- Kaynak başlığını aynen kopyalama; özgün, doğal ve haber diline uygun
  yeni bir başlık oluştur.
- İçeriği okunabilir paragraflara ayır.
- Gerektiğinde ara başlıklar kullanarak içeriğin okunabilirliğini artır.
- HTML etiketleri kullanabilirsin. <p>, <h2>, <h3>, <strong>,
  <ul>, <ol> ve <li> etiketleri serbesttir.
- HTML etiketlerini yalnızca içerik yapısını ve okunabilirliği
  iyileştirmek için kullan. Gereksiz biçimlendirme yapma.
- Markdown kullanma.
- Haberde diziyle açık ve doğrudan bir bağlantı yoksa series null olsun.
- Yalnızca istenen alanları içeren geçerli JSON döndür.
- JSON dışında hiçbir açıklama veya metin yazma.

Kaynak başlığı:
{article["sourceTitle"]}

Kaynak açıklaması:
{article.get("sourceDescription", "")}

Haber içeriği:
{source_text}

Beklenen JSON:
{{
  "title": "Özgün haber başlığı",
  "content": "<p>Özgün biçimde yeniden yazılmış haber içeriği...</p>",
  "series": null
}}
""".strip()


def parse_ai_json(value):
    value = value.strip()
    value = re.sub(r"^```(?:json)?\s*", "", value)
    value = re.sub(r"\s*```$", "", value)

    match = re.search(r"\{.*\}", value, re.DOTALL)

    if not match:
        raise ValueError("Gemini yanıtında JSON bulunamadı.")

    result = json.loads(match.group(0))

    if not isinstance(result, dict):
        raise ValueError("Gemini JSON çıktısı nesne değil.")

    return result


def generate_with_gemini(article, api_key):
    model = get_gemini_model(api_key)

    response = SESSION.post(
        f"{GEMINI_API_BASE}{model}:generateContent",
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "contents": [{
                "parts": [{
                    "text": build_prompt(article)
                }]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json",
                "maxOutputTokens": 1024,
            },
        },
        timeout=(15, 90)
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    data = response.json()
    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError(
            f"Gemini yanıtında candidate yok: {str(data)[:500]}"
        )

    parts = candidates[0].get("content", {}).get("parts", [])

    content = "".join(
        part.get("text", "")
        for part in parts
    )

    return parse_ai_json(content)


def process_article(article, api_key):
    print("\nGemini işliyor:", article["sourceTitle"])

    last_error = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            result = generate_with_gemini(article, api_key)

            print(f"Gemini sonrası bekleme: {GEMINI_DELAY} saniye.")
            time.sleep(GEMINI_DELAY)

            title = clean_text(result.get("title"))
            content = result.get("content")
            series = result.get("series")

            if (
                not title
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError(
                    "Gemini başlık veya haber içeriği üretmedi."
                )

            print("Gemini başarılı.")

            return {
                "title": title,
                "content": content.strip(),
                "series": clean_text(series) if series else None,
                "aiProvider": "gemini",
                "aiStatus": "completed",
            }

        except Exception as error:
            last_error = error

            print(
                f"Gemini hatası ({attempt}/{RETRY_ATTEMPTS}):",
                type(error).__name__,
                str(error)[:400]
            )

            if attempt < RETRY_ATTEMPTS:
                print(f"{RETRY_DELAY} saniye sonra tekrar denenecek.")
                time.sleep(RETRY_DELAY)

    message = (
        f"{type(last_error).__name__}: {last_error}"
        if last_error else "Gemini işlemi tamamlanamadı."
    )

    return {
        "title": article["sourceTitle"],
        "content": "",
        "series": None,
        "aiProvider": None,
        "aiStatus": "pending",
        "aiError": message[:1000],
    }


def load_news_archive():
    NEWS_DIR.mkdir(parents=True, exist_ok=True)

    records = []

    for file_path in sorted(NEWS_DIR.glob("*.json")):
        try:
            with file_path.open("r", encoding="utf-8") as file:
                daily_records = json.load(file)

            if not isinstance(daily_records, list):
                print("Geçersiz arşiv dosyası atlandı:", file_path.name)
                continue

            for item in daily_records:
                if not isinstance(item, dict):
                    continue

                item["_archiveDate"] = file_path.stem
                records.append(item)

        except (OSError, json.JSONDecodeError) as error:
            print(
                "Arşiv okunamadı:",
                file_path.name,
                str(error)[:250]
            )

    deduplicated = {}

    for item in records:
        source_url = item.get("sourceUrl")

        if not source_url:
            continue

        normalized = decode_source_url(source_url)
        item["sourceUrl"] = normalized

        decode_image_fields(item)

        previous = deduplicated.get(normalized)

        if previous is None:
            deduplicated[normalized] = item
        elif (
            previous.get("aiStatus") != "completed"
            and item.get("aiStatus") == "completed"
        ):
            deduplicated[normalized] = item

    return list(deduplicated.values())


def save_daily_news(records):
    NEWS_DIR.mkdir(parents=True, exist_ok=True)

    grouped = {}

    for item in records:
        if not isinstance(item, dict):
            continue

        archive_date = (
            item.get("_archiveDate")
            or get_archive_date(item)
        )

        grouped.setdefault(archive_date, []).append(item)

    for archive_date, daily_records in grouped.items():
        daily_records.sort(
            key=lambda item: item.get("publishedAt") or "",
            reverse=True
        )

        clean_records = []

        for item in daily_records:
            saved_item = dict(item)
            if saved_item.get("sourceUrl"):
                saved_item["sourceUrl"] = encode_url_value(
                    saved_item["sourceUrl"],
                    field_name="sourceUrl",
                    normalize=True
                )

            if saved_item.get("imageUrl"):
                saved_item["imageUrl"] = encode_url_value(
                    saved_item["imageUrl"],
                    field_name="imageUrl"
                )

            images = saved_item.get("images")
            if isinstance(images, list):
                saved_item["images"] = [
                    encode_url_value(image, field_name="images")
                    if image else image
                    for image in images
                ]

            saved_item.pop("_archiveDate", None)
            saved_item.pop("summary", None)
            saved_item.pop("articleText", None)
            clean_records.append(saved_item)

        target_file = NEWS_DIR / f"{archive_date}.json"
        temp_file = NEWS_DIR / f"{archive_date}.tmp"

        with temp_file.open("w", encoding="utf-8") as file:
            json.dump(
                clean_records,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, target_file)


def load_state():
    if not STATE_FILE.exists():
        return {
            "nextBackfillPage": BACKFILL_START_PAGE,
            "backfillCompleted": False,
        }

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("Durum dosyası nesne değil.")

        return {
            "nextBackfillPage": max(
                BACKFILL_START_PAGE,
                int(state.get(
                    "nextBackfillPage",
                    state.get("nextPage", BACKFILL_START_PAGE)
                ))
            ),
            "backfillCompleted": bool(
                state.get(
                    "backfillCompleted",
                    state.get("completed", False)
                )
            ),
        }

    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("Tarama durumu okunamadı:", str(error))
        return {
            "nextBackfillPage": BACKFILL_START_PAGE,
            "backfillCompleted": False,
        }


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    os.replace(temp_file, STATE_FILE)


def upsert_pending(article, records, existing, error):
    url = normalize_url(article["sourceUrl"])
    current = existing.get(url)

    if current is None:
        current = {
            "id": article_id(url),
            "title": article.get("sourceTitle", ""),
            "content": "",
            "series": None,
            "aiProvider": None,
            "aiStatus": "pending",
            "sourceTitle": article.get("sourceTitle", ""),
            "source": SOURCE_NAME,
            "sourceUrl": url,
            "sourceDescription": article.get("sourceDescription", ""),
            "imageUrl": article.get("imageUrl"),
            "images": article.get("images", []),
            "publishedAt": article.get("publishedAt"),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }

        records.append(current)
        existing[url] = current

    current["aiStatus"] = "pending"
    current["aiError"] = str(error)[:1000]
    current["sourceTitle"] = (
        article.get("sourceTitle")
        or current.get("sourceTitle")
    )
    current["sourceDescription"] = (
        article.get("sourceDescription")
        or current.get("sourceDescription", "")
    )
    current["imageUrl"] = (
        article.get("imageUrl")
        or current.get("imageUrl")
    )
    current["images"] = article.get(
        "images",
        current.get("images", [])
    )
    current["publishedAt"] = (
        article.get("publishedAt")
        or current.get("publishedAt")
    )
    current["_archiveDate"] = (
        current.get("_archiveDate")
        or get_archive_date(article)
    )

    save_daily_news(records)


def process_listing_page(page_number, articles, records, existing, api_key):

    articles = sorted(
        articles,
        key=lambda item: item.get("publishedAt") or "",
        reverse=True
    )

    print(f"\n========== LİSTE SAYFASI {page_number} ==========")

    all_success = True

    for index, listing_article in enumerate(articles, 1):
        url = normalize_url(listing_article["sourceUrl"])
        listing_article["sourceUrl"] = url

        current = existing.get(url)

        if current:
            print(
                f"\n[{index}/{len(articles)}] "
                "Daha önce arşivlenmiş haber atlanıyor:",
                listing_article["sourceTitle"]
            )

        else:
            is_new = current is None

            print(
                f"\n[{index}/{len(articles)}] "
                f"{'Yeni haber' if is_new else 'Bekleyen haber'}:",
                listing_article["sourceTitle"]
            )

            article = dict(listing_article)

            try:
                article = fetch_article_detail(article)

                if len(article.get("articleText", "").strip()) < 50:
                    raise ValueError(
                        "Haber detayından yeterli metin alınamadı."
                    )

                print(
                    "İçerik karakteri:",
                    len(article.get("articleText", ""))
                )

                generated = process_article(article, api_key)

                if generated.get("aiStatus") == "completed":
                    archive_date = (
                        current.get("_archiveDate")
                        if current else get_archive_date(article)
                    )

                    if current:
                        current.update(generated)
                        current["sourceTitle"] = article["sourceTitle"]
                        current["source"] = SOURCE_NAME
                        current["sourceUrl"] = url
                        current["sourceDescription"] = article.get(
                            "sourceDescription", ""
                        )
                        current["imageUrl"] = (
                            article.get("imageUrl")
                            or current.get("imageUrl")
                        )
                        current["images"] = article.get("images", [])
                        current["publishedAt"] = (
                            article.get("publishedAt")
                            or current.get("publishedAt")
                        )
                        current["fetchedAt"] = (
                            datetime.now(timezone.utc).isoformat()
                        )
                        current["_archiveDate"] = archive_date
                        current.pop("aiError", None)

                    else:
                        current = {
                            "id": article_id(url),
                            **generated,
                            "sourceTitle": article["sourceTitle"],
                            "source": SOURCE_NAME,
                            "sourceUrl": url,
                            "sourceDescription": article.get(
                                "sourceDescription", ""
                            ),
                            "imageUrl": article.get("imageUrl"),
                            "images": article.get("images", []),
                            "publishedAt": article.get("publishedAt"),
                            "fetchedAt": datetime.now(timezone.utc).isoformat(),
                            "_archiveDate": archive_date,
                        }

                        records.append(current)
                        existing[url] = current

                    save_daily_news(records)
                    print("Haber arşive kaydedildi.")

                else:
                    all_success = False
                    upsert_pending(
                        article,
                        records,
                        existing,
                        generated.get("aiError", "Gemini başarısız.")
                    )

            except Exception as error:
                all_success = False

                print(
                    "Haber işlenemedi:",
                    type(error).__name__,
                    str(error)[:400]
                )

                upsert_pending(
                    article,
                    records,
                    existing,
                    error
                )


    return all_success


def main():
    print("\n========== NEWS SCRAPER ==========")

    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY bulunamadı.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NEWS_DIR.mkdir(parents=True, exist_ok=True)

    records = load_news_archive()

    existing = {
        normalize_url(item["sourceUrl"]): item
        for item in records
        if item.get("sourceUrl")
    }

    print("Mevcut arşiv kaydı:", len(records))
    print(
        "Bekleyen kayıt:",
        sum(1 for item in records if item.get("aiStatus") == "pending")
    )

    # Her çalışmada ilk güncel liste sayfasını tara.
    print("\n========== GÜNCEL HABERLER ==========")

    for page_number in range(1, PAGE_COUNT + 1):
        print(f"\nGüncel sayfa {page_number}/{PAGE_COUNT}")

        try:
            articles = request_listing_with_retry(page_number)

            if articles is None:
                continue

            process_listing_page(
                page_number,
                articles,
                records,
                existing,
                gemini_key
            )

        except Exception as error:
            print(
                f"Güncel sayfa {page_number} tamamlanamadı:",
                type(error).__name__,
                str(error)[:300]
            )

    # Her çalışmada sıradaki tek eski sayfayı tara.
    state = load_state()

    if state["backfillCompleted"]:
        print("\nEski haber taraması daha önce tamamlanmış.")
        print("Sonraki sayfa:", state["nextBackfillPage"])

    else:
        page_number = state["nextBackfillPage"]

        print("\n========== ESKİ HABER TARAMASI ==========")
        print("Sıradaki eski sayfa:", page_number)

        try:
            articles = request_listing_with_retry(page_number)

            if articles is None:
                state["backfillCompleted"] = True
                save_state(state)
                print("Eski haberlerin sonuna ulaşıldı.")

            else:
                page_success = process_listing_page(
                    page_number,
                    articles,
                    records,
                    existing,
                    gemini_key
                )

                if page_success:
                    state["nextBackfillPage"] = page_number + 1
                    save_state(state)

                    print(
                        "Eski sayfa tamamlandı. Sonraki sayfa:",
                        state["nextBackfillPage"]
                    )

                else:
                    print(
                        "Eski sayfada başarısız haber var. "
                        "Sayfa imleci ilerletilmedi."
                    )

        except Exception as error:
            print(
                "Eski sayfa tamamlanamadı; aynı sayfa korunacak:",
                type(error).__name__,
                str(error)[:300]
            )

    save_daily_news(records)

    completed = sum(
        1 for item in records
        if item.get("aiStatus") == "completed"
    )

    pending = sum(
        1 for item in records
        if item.get("aiStatus") == "pending"
    )

    print("\n========== NEWS SCRAPER SUMMARY ==========")
    print("Toplam benzersiz haber:", len(records))
    print("Tamamlanan:", completed)
    print("Bekleyen:", pending)
    print("Eski haber sıradaki sayfa:", state["nextBackfillPage"])
    print("Eski haber taraması tamamlandı:", state["backfillCompleted"])
    print("Arşiv klasörü:", NEWS_DIR)


if __name__ == "__main__":
    main()
