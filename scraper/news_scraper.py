import hashlib
import html
import json
import os
import re
import shutil
import sys
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
DATA_FILE = DATA_DIR / "news.json"
STATE_FILE = DATA_DIR / "news_scraper_state.json"

ENCRYPTED_CATEGORY_URL = "HAEGGxpJRwIDAVpaEAgRGAAcTF5ER1gAFAFFChwFAhcXWREVDhESShZESFkd"
ENCRYPTED_DOMAINS = (
    "FhwAGAwdCUEAA0MAExJNCAof",
    "AwIFRQsaGl4RGEwYBhQNHwQBA1FfXw==",
)
ENCRYPTED_SOURCE_NAME = "NhwAGAwdSGwYAlgaBgCm9A=="

CATEGORY_URL = xor_decrypt(ENCRYPTED_CATEGORY_URL)
ALLOWED_DOMAINS = tuple(xor_decrypt(value) for value in ENCRYPTED_DOMAINS)
SOURCE_NAME = xor_decrypt(ENCRYPTED_SOURCE_NAME)

ENCRYPTED_RELATED_CARD_CLASS = "FhwAGAwdRV8RGkwAFwVOCAQASQ=="
RELATED_CARD_CLASS = xor_decrypt(ENCRYPTED_RELATED_CARD_CLASS)
PAGE_COUNT = 5

PREFERRED_MODELS = [
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
    "models/gemini-2.5-flash-lite",
]

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


def load_scraper_state():
    default_state = {
        "nextBackfillPage": 6,
        "backfillCompleted": False,
    }

    if not STATE_FILE.exists():
        save_scraper_state(default_state)
        return default_state.copy()

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Scraper durum dosyası okunamadı: {STATE_FILE}"
        ) from error

    if not isinstance(state, dict):
        raise RuntimeError("Scraper durum dosyası geçersiz.")

    next_page = state.get("nextBackfillPage")
    completed = state.get("backfillCompleted")

    if (
        isinstance(next_page, bool)
        or not isinstance(next_page, int)
        or next_page < 6
        or not isinstance(completed, bool)
    ):
        raise RuntimeError("Scraper durum dosyasındaki değerler geçersiz.")

    return {
        "nextBackfillPage": next_page,
        "backfillCompleted": completed,
    }


def save_scraper_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    os.replace(temporary_file, STATE_FILE)


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


class PageNotFoundError(requests.RequestException):
    """Listeleme sayfasının gerçekten bulunamadığını belirtir."""


def fetch_listing_page(page_number):
    if page_number == 1:
        url = CATEGORY_URL
    else:
        url = urljoin(CATEGORY_URL, f"page/{page_number}/")

    response = SESSION.get(url, timeout=(15, 40))

    if response.status_code == 404:
        print(f"Sayfa {page_number} bulunamadı (HTTP 404).")
        raise PageNotFoundError(f"Sayfa {page_number} bulunamadı.")

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
            articles = fetch_listing_page(page_number)

            for article in articles:
                all_articles[article["sourceUrl"]] = article

            print("Bulunan:", len(articles))
            print("Benzersiz toplam:", len(all_articles))

        except requests.RequestException as error:
            print(
                f"Sayfa {page_number} hatası:",
                type(error).__name__,
                str(error)[:300]
            )

        time.sleep(1)

    return list(all_articles.values())


def fetch_article_detail(article):
    response = SESSION.get(
        article["sourceUrl"],
        timeout=(15, 40)
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    image_meta = soup.select_one('meta[property="og:image"]')

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
            cover_url = (
                cover.get("data-src")
                or cover.get("data-lazy-src")
                or cover.get("data-original")
                or cover.get("src")
            )

            if not cover_url and cover.get("srcset"):
                cover_url = cover["srcset"].split(",")[0].strip().split(" ")[0]

            if cover_url:
                article["imageUrl"] = urljoin(
                    article["sourceUrl"],
                    cover_url
                )

        seen_images = set()

        for image in content.find_all("img"):
            if image.find_parent(class_=RELATED_CARD_CLASS):
                continue

            image_url = (
                image.get("data-src")
                or image.get("data-lazy-src")
                or image.get("data-original")
                or image.get("src")
            )

            if not image_url and image.get("srcset"):
                image_url = image["srcset"].split(",")[0].strip().split(" ")[0]

            if not image_url:
                continue

            image_url = urljoin(article["sourceUrl"], image_url)

            if image_url == article.get("imageUrl"):
                continue

            if image_url in seen_images:
                continue

            seen_images.add(image_url)
            article["images"].append(image_url)

        text_content = BeautifulSoup(str(content), "html.parser")

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

        paragraphs = [p for p in paragraphs if len(p) > 30]

        article_text = "\n".join(paragraphs)

        if not article_text:
            article_text = clean_text(
                text_content.get_text(" ", strip=True)
            )

        article["articleText"] = article_text[:12000]

    if not article.get("sourceDescription") and article.get("articleText"):
        article["sourceDescription"] = article["articleText"][:1200]

    return article

def get_gemini_model(api_key):
    global GEMINI_MODEL

    if GEMINI_MODEL:
        return GEMINI_MODEL

    response = SESSION.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
        timeout=(15, 40)
    )
    response.raise_for_status()

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
Bir Türk televizyon ve dizi haber uygulamasının editörüsün.

Aşağıdaki haberin içeriğine dayanarak özgün bir Türkçe haber başlığı
ve kısa bir haber özeti hazırla.

Kurallar:
- Yalnızca verilen kaynakta bulunan bilgileri kullan.
- Kaynakta olmayan kişi, tarih, olay veya açıklama ekleme.
- İddiaları kesinleşmiş bilgi gibi sunma.
- Kaynak başlığını aynen kopyalama.
- Başlık doğal, anlaşılır ve haber dilinde olsun.
- Özet 2-3 kısa cümleden oluşsun.
- Gereksiz tekrar, reklam dili ve abartı kullanma.
- Haberde diziyle ilgili açık bir bağlantı yoksa series null olsun.
- Yalnızca geçerli JSON döndür. Markdown kullanma.

Kaynak başlığı:
{article["sourceTitle"]}

Kaynak açıklaması:
{article.get("sourceDescription", "")}

Haber içeriği:
{source_text}

Beklenen JSON:
{{
  "title": "Özgün haber başlığı",
  "summary": "2-3 cümlelik haber özeti",
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

    try:
        response = SESSION.post(
            f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
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
    finally:
        time.sleep(5)

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

    try:
        result = generate_with_gemini(article, api_key)

        title = clean_text(result.get("title"))
        summary = clean_text(result.get("summary"))
        series = result.get("series")

        if not title or not summary:
            raise ValueError("Gemini başlık veya özet üretmedi.")

        print("Gemini başarılı.")

        return {
            "title": title,
            "summary": summary,
            "series": clean_text(series) if series else None,
            "aiProvider": "gemini",
            "aiStatus": "completed",
        }

    except Exception as error:
        message = f"{type(error).__name__}: {error}"

        print("Gemini başarısız:", message[:500])

        return {
            "title": article["sourceTitle"],
            "summary": article.get("sourceDescription", ""),
            "series": None,
            "aiProvider": None,
            "aiStatus": "pending",
            "aiError": message[:1000],
        }


def decode_news_record(item):
    item = dict(item)

    for field in ("sourceUrl", "imageUrl"):
        value = item.get(field)
        if value and not value.startswith(("http://", "https://")):
            item[field] = xor_decrypt(value)

    if item.get("source"):
        item["source"] = SOURCE_NAME

    return item


def encode_news_record(item):
    item = dict(item)

    for field in ("sourceUrl", "imageUrl", "source"):
        value = item.get(field)
        if value:
            item[field] = xor_encrypt(
                SOURCE_NAME if field == "source" else value
            )

    return item


def get_news_day(item):
    published_at = item.get("publishedAt")

    if not published_at or len(published_at) < 10:
        raise ValueError(
            f"Geçersiz publishedAt: {item.get('sourceTitle')}"
        )

    day = published_at[:10]

    datetime.strptime(day, "%Y-%m-%d")

    return day


def load_daily_news():
    news_dir = DATA_DIR / "news"
    records = []

    if not news_dir.exists():
        return records

    for path in sorted(news_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            daily_records = json.load(file)

        if not isinstance(daily_records, list):
            raise ValueError(f"Geçersiz günlük arşiv: {path}")

        records.extend(
            decode_news_record(item) for item in daily_records
        )

    return records


def save_daily_news(news):
    if not news:
        print("Boş arşiv kaydedilmedi; mevcut günlük dosyalar korundu.")
        return

    news_dir = DATA_DIR / "news"
    news_dir.mkdir(parents=True, exist_ok=True)

    deduplicated = {}

    for item in news:
        source_url = normalize_url(item["sourceUrl"])
        item["sourceUrl"] = source_url
        previous = deduplicated.get(source_url)

        if previous is None:
            deduplicated[source_url] = item
            continue

        current_completed = item.get("aiStatus") == "completed"
        previous_completed = previous.get("aiStatus") == "completed"

        if current_completed and not previous_completed:
            deduplicated[source_url] = item
        elif current_completed == previous_completed:
            if (item.get("publishedAt") or "") > (
                previous.get("publishedAt") or ""
            ):
                deduplicated[source_url] = item

    grouped = {}

    for item in deduplicated.values():
        day = get_news_day(item)
        grouped.setdefault(day, []).append(item)

    for day, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: item.get("publishedAt") or "",
            reverse=True,
        )

        destination = news_dir / f"{day}.json"
        temp = destination.with_suffix(".json.tmp")

        with temp.open("w", encoding="utf-8") as file:
            json.dump(
                [encode_news_record(item) for item in ordered],
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(temp, destination)

    # Arşivden çıkarılmış veya tarihi değişmiş kayıtların eski dosyalarını temizle.
    valid_days = {f"{day}.json" for day in grouped}

    for path in news_dir.glob("*.json"):
        if path.name not in valid_days:
            path.unlink()


def load_news_archive():
    daily_news = load_daily_news()

    if daily_news:
        return daily_news

    if not DATA_FILE.exists():
        return []

    with DATA_FILE.open("r", encoding="utf-8") as file:
        legacy_news = json.load(file)

    if not isinstance(legacy_news, list):
        raise ValueError("news.json beklenen liste formatında değil.")

    return [
        decode_news_record(item) for item in legacy_news
    ]



def backup_news_archive(prefix):
    news_dir = DATA_DIR / "news"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if news_dir.exists():
        backup_dir = DATA_DIR / f"news.backup.{prefix}.{timestamp}"
        shutil.copytree(news_dir, backup_dir)
        return backup_dir

    if DATA_FILE.exists():
        backup_file = DATA_DIR / f"news.backup.{prefix}.{timestamp}.json"
        shutil.copy2(DATA_FILE, backup_file)
        return backup_file

    return None


def rebuild_and_merge():
    """Mevcut haberleri günlük arşivde korur ve yeni/bekleyen kayıtları işler."""

    print("\n========== NEWS REBUILD & MERGE ==========")

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY bulunamadı.")

    news = load_news_archive()
    if not news:
        raise SystemExit("Mevcut haber arşivi bulunamadı; merge işlemi iptal edildi.")

    deduplicated = {}
    for item in news:
        source_url = item.get("sourceUrl")
        if not source_url:
            continue

        normalized = normalize_url(source_url)
        item["sourceUrl"] = normalized
        previous = deduplicated.get(normalized)

        if previous is None or (
            previous.get("aiStatus") != "completed"
            and item.get("aiStatus") == "completed"
        ):
            deduplicated[normalized] = item

    news = list(deduplicated.values())
    existing = {
        normalize_url(item["sourceUrl"]): item
        for item in news
    }

    pending_before = sum(
        1 for item in news if item.get("aiStatus") == "pending"
    )

    print("Mevcut benzersiz kayıt:", len(news))
    print("Bekleyen kayıt:", pending_before)

    articles = fetch_all_articles()
    if not articles:
        raise SystemExit("Kaynak taramasında haber bulunamadı; arşiv korundu.")

    backup_file = backup_news_archive("merge")
    if backup_file:
        print("Yedek:", backup_file)

    added = 0
    retried = 0
    completed = 0
    failed = 0
    skipped_completed = 0

    for index, listing_article in enumerate(articles, 1):
        url = normalize_url(listing_article["sourceUrl"])
        listing_article["sourceUrl"] = url
        current = existing.get(url)
        is_new = current is None

        if current and current.get("aiStatus") == "completed":
            skipped_completed += 1
            print(
                f"\n[{index}/{len(articles)}] Tamamlanmış kayıt korunuyor:",
                listing_article["sourceTitle"],
            )
            continue

        if is_new:
            print(
                f"\n[{index}/{len(articles)}] Yeni haber:",
                listing_article["sourceTitle"],
            )
        else:
            retried += 1
            print(
                f"\n[{index}/{len(articles)}] Bekleyen haber yeniden deneniyor:",
                listing_article["sourceTitle"],
            )

        article = dict(listing_article)

        try:
            article = fetch_article_detail(article)
            print("İçerik karakteri:", len(article.get("articleText", "")))
        except requests.RequestException as error:
            print("Detay sayfası alınamadı; kart bilgileri kullanılacak:", str(error)[:300])

        generated = None
        last_result = None

        for attempt in range(5):
            last_result = process_article(article, gemini_key)

            if last_result.get("aiStatus") == "completed":
                generated = last_result
                break

            error_text = last_result.get("aiError", "")
            retryable_errors = (
                "HTTP 429:",
                "HTTP 500:",
                "HTTP 502:",
                "HTTP 503:",
                "HTTP 504:",
            )

            if not any(error in error_text for error in retryable_errors):
                break

            if attempt < 4:
                print(
                    f"Geçici Gemini hatası. 5 saniye sonra tekrar denenecek "
                    f"(deneme {attempt + 2}/5)."
                )
                time.sleep(5)

        if generated:
            ai_fields = generated
            completed += 1
        else:
            ai_fields = last_result or {
                "title": article.get("sourceTitle", ""),
                "summary": article.get("sourceDescription", ""),
                "series": None,
                "aiProvider": None,
                "aiStatus": "pending",
                "aiError": "Gemini işlemi tamamlanamadı.",
            }
            failed += 1

        if current:
            current.update(ai_fields)
            current["sourceTitle"] = (
                article.get("sourceTitle") or current.get("sourceTitle")
            )
            current["source"] = current.get("source") or SOURCE_NAME
            current["sourceUrl"] = url
            current["imageUrl"] = (
                article.get("imageUrl") or current.get("imageUrl")
            )
            current["publishedAt"] = (
                article.get("publishedAt") or current.get("publishedAt")
            )
            current["fetchedAt"] = datetime.now(timezone.utc).isoformat()

            if current.get("aiStatus") == "completed":
                current.pop("aiError", None)
        else:
            current = {
                "id": article_id(url),
                **ai_fields,
                "sourceTitle": article["sourceTitle"],
                "source": SOURCE_NAME,
                "sourceUrl": url,
                "imageUrl": article.get("imageUrl") or None,
                "publishedAt": article.get("publishedAt"),
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
            }
            news.append(current)
            existing[url] = current
            added += 1

        news.sort(
            key=lambda item: item.get("publishedAt") or "",
            reverse=True,
        )

        save_daily_news(news)

        print(
            f"İlerleme: {completed} Gemini başarılı, {failed} başarısız, "
            f"{added} yeni haber."
        )

    print("\n========== MERGE SUMMARY ==========")
    print("Yeni haber:", added)
    print("Yeniden denenen:", retried)
    print("Korunan tamamlanmış kayıt:", skipped_completed)
    print("Bu çalışmada Gemini başarılı:", completed)
    print("Bu çalışmada başarısız:", failed)
    print("Toplam benzersiz arşiv:", len(news))
    print("Arşiv klasörü:", DATA_DIR / "news")



def process_listing_articles(articles, news, api_key, label):
    existing = {
        normalize_url(item["sourceUrl"]): item
        for item in news
        if item.get("sourceUrl")
    }

    seen = set()
    page_success = bool(articles)

    stats = {
        "total": len(articles),
        "added": 0,
        "completed": 0,
        "pending": 0,
        "skipped": 0,
        "invalid_date": 0,
    }

    print(f"\n========== {label} ==========")
    print("Bulunan haber:", len(articles))

    for index, listing_article in enumerate(articles, 1):
        url = normalize_url(listing_article["sourceUrl"])

        if url in seen:
            continue

        seen.add(url)
        listing_article["sourceUrl"] = url

        current = existing.get(url)

        if current and current.get("aiStatus") == "completed":
            stats["skipped"] += 1
            print(
                f"[{index}/{len(articles)}] Tamamlanmış kayıt atlandı:",
                listing_article["sourceTitle"],
            )
            continue

        print(
            f"\n[{index}/{len(articles)}] Haber:",
            listing_article["sourceTitle"],
        )

        article = dict(listing_article)

        if current:
            for field in ("publishedAt", "imageUrl", "sourceDescription"):
                if not article.get(field):
                    article[field] = current.get(field)

        try:
            article = fetch_article_detail(article)
            print(
                "İçerik karakteri:",
                len(article.get("articleText", "")),
            )
        except requests.RequestException as error:
            print(
                "Detay sayfası alınamadı; haber sonraki çalıştırmada denenecek:",
                str(error)[:300],
            )
            stats["pending"] += 1
            page_success = False
            continue
        try:
            get_news_day(article)
        except (ValueError, TypeError) as error:
            print("Haber tarihi geçersiz; kayıt işlenemedi:", str(error))
            stats["invalid_date"] += 1
            page_success = False
            continue

        generated = process_article(article, api_key)

        item = dict(current) if current else {}

        item.update({
            "id": article_id(url),
            **generated,
            "sourceTitle": article["sourceTitle"],
            "source": SOURCE_NAME,
            "sourceUrl": url,
            "imageUrl": article.get("imageUrl") or None,
            "publishedAt": article.get("publishedAt"),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        })

        if current:
            current.update(item)
        else:
            news.append(item)
            existing[url] = item
            stats["added"] += 1

        if item.get("aiStatus") == "completed":
            stats["completed"] += 1
        else:
            stats["pending"] += 1
            page_success = False

        news.sort(
            key=lambda record: record.get("publishedAt") or "",
            reverse=True,
        )

        # Her zaman tam arşiv kaydedilir.
        save_daily_news(news)

    print(f"\n{label} özeti:")
    print("Yeni haber:", stats["added"])
    print("Gemini başarılı:", stats["completed"])
    print("Gemini bekleyen:", stats["pending"])
    print("Tamamlanmış kayıt atlandı:", stats["skipped"])
    print("Geçersiz tarih:", stats["invalid_date"])
    print("Sayfa başarılı:", page_success)

    return page_success, stats


def main():
    print("\n========== NEWS DAILY + BACKFILL ==========")

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY bulunamadı.")

    news = load_news_archive()

    deduplicated = {}
    for item in news:
        source_url = item.get("sourceUrl")
        if not source_url:
            continue

        normalized = normalize_url(source_url)
        item["sourceUrl"] = normalized
        previous = deduplicated.get(normalized)

        if previous is None or (
            previous.get("aiStatus") != "completed"
            and item.get("aiStatus") == "completed"
        ):
            deduplicated[normalized] = item

    news = list(deduplicated.values())
    print("Mevcut arşiv:", len(news))

    # Her çalıştırmada önce güncel haberler taranır.
    print("\n========== LATEST NEWS: PAGE 1 ==========")

    try:
        latest_articles = fetch_listing_page(1)
    except requests.RequestException as error:
        print("Güncel haber sayfası alınamadı:", str(error)[:300])
    else:
        if latest_articles:
            process_listing_articles(
                latest_articles,
                news,
                gemini_key,
                "LATEST NEWS",
            )
        else:
            print("Güncel haber sayfasında haber bulunamadı.")

    # Sıradaki tek backfill sayfası.
    state = load_scraper_state()

    if state["backfillCompleted"]:
        print("\nBackfill daha önce tamamlanmış.")
        return

    page_number = state["nextBackfillPage"]
    print(f"\n========== BACKFILL: PAGE {page_number} ==========")

    try:
        backfill_articles = fetch_listing_page(page_number)

    except PageNotFoundError:
        state["backfillCompleted"] = True
        save_scraper_state(state)
        print("HTTP 404 doğrulandı. Backfill tamamlandı.")

    except requests.RequestException as error:
        print(
            "Backfill sayfası alınamadı; sonraki çalıştırmada tekrar denenecek:",
            str(error)[:300],
        )

    else:
        if not backfill_articles:
            print(
                "Sayfa boş döndü. Durum değiştirilmedi; "
                "sonraki çalıştırmada tekrar denenecek."
            )
            return

        page_success, stats = process_listing_articles(
            backfill_articles,
            news,
            gemini_key,
            f"BACKFILL PAGE {page_number}",
        )

        if page_success:
            state["nextBackfillPage"] = page_number + 1
            save_scraper_state(state)
            print(
                f"Backfill sayfası {page_number} tamamlandı. "
                f"Sıradaki sayfa: {page_number + 1}"
            )
        else:
            print(
                f"Backfill sayfası {page_number} tamamlanamadı. "
                "Aynı sayfa sonraki çalıştırmada tekrar denenecek."
            )

    print("\n========== DAILY SCRAPER SUMMARY ==========")
    print("Toplam benzersiz arşiv:", len(news))
    print("Sonraki backfill sayfası:", state["nextBackfillPage"])
    print("Backfill tamamlandı:", state["backfillCompleted"])
    print("Arşiv klasörü:", DATA_DIR / "news")


if __name__ == "__main__":
    if "--merge" in sys.argv:
        rebuild_and_merge()
    else:
        main()
