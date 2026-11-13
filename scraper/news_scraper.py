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
TEMP_FILE = DATA_DIR / "news.rebuild.json"

ENCRYPTED_CATEGORY_URL = "HAEGGxpJRwIDAVpaEAgRGAAcTF5ER1gAFAFFChwFAhcXWREVDhESShZESFkd"
ENCRYPTED_DOMAINS = (
    "FhwAGAwdCUEAA0MAExJNCAof",
    "AwIFRQsaGl4RGEwYBhQNHwQBA1FfXw==",
)
ENCRYPTED_SOURCE_NAME = "NhwAGAwdSGwYAlgaBgCm9A=="

CATEGORY_URL = xor_decrypt(ENCRYPTED_CATEGORY_URL)
ALLOWED_DOMAINS = tuple(xor_decrypt(value) for value in ENCRYPTED_DOMAINS)
SOURCE_NAME = xor_decrypt(ENCRYPTED_SOURCE_NAME)
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


def fetch_listing_page(page_number):
    if page_number == 1:
        url = CATEGORY_URL
    else:
        url = urljoin(CATEGORY_URL, f"page/{page_number}/")

    response = SESSION.get(url, timeout=(15, 40))

    if response.status_code == 404:
        print(f"Sayfa {page_number} bulunamadı.")
        return []

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

    # Open Graph görseli
    image_meta = soup.select_one(
        'meta[property="og:image"]'
    )

    if image_meta and image_meta.get("content"):
        article["imageUrl"] = urljoin(
            article["sourceUrl"],
            image_meta["content"]
        )

    # Yayın tarihi
    for selector in (
        'meta[property="article:published_time"]',
        'meta[name="date"]',
        'meta[itemprop="datePublished"]',
    ):
        element = soup.select_one(selector)

        if element and element.get("content"):
            article["publishedAt"] = (
                parse_date(element["content"])
                or article["publishedAt"]
            )
            break

    if not article["publishedAt"]:
        time_element = soup.find("time")

        if time_element:
            article["publishedAt"] = parse_date(
                time_element.get("datetime")
                or time_element.get_text(" ", strip=True)
            )

    # Makale gövdesi
    selectors = [
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

    if content:
        for unwanted in content.select(
            "script, style, nav, footer, iframe, "
            ".sharedaddy, .jp-relatedposts, .related-posts, "
            ".ads, .advertisement, .social-share"
        ):
            unwanted.decompose()

        paragraphs = [
            clean_text(p.get_text(" ", strip=True))
            for p in content.find_all("p")
        ]

        paragraphs = [
            p for p in paragraphs
            if len(p) > 30
        ]

        article_text = "\n".join(paragraphs)

        if not article_text:
            article_text = clean_text(content.get_text(" ", strip=True))

        article["articleText"] = article_text[:12000]

    if not article["sourceDescription"] and article["articleText"]:
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


def save_temp_news(news):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    encrypted_news = [encode_news_record(item) for item in news]

    with TEMP_FILE.open("w", encoding="utf-8") as file:
        json.dump(encrypted_news, file, ensure_ascii=False, indent=2)

def rebuild_and_merge():
    """Rescan the first PAGE_COUNT listing pages and merge into news.json.

    Completed AI records are preserved. Pending records are retried, and
    previously unseen source URLs are added. The JSON is atomically saved
    after each processed article.
    """
    print("\n========== NEWS REBUILD & MERGE ==========")

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY bulunamadı.")

    if not DATA_FILE.exists():
        raise SystemExit("Mevcut news.json bulunamadı; merge işlemi iptal edildi.")

    with DATA_FILE.open("r", encoding="utf-8") as file:
        news = json.load(file)

    if not isinstance(news, list):
        raise SystemExit("news.json beklenen liste formatında değil.")

    news = [decode_news_record(item) for item in news]

    # Normalize and deduplicate existing URLs. If duplicates exist, prefer
    # a completed record so a successful AI result is never discarded.
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
    existing = {normalize_url(item["sourceUrl"]): item for item in news}

    pending_before = sum(
        1 for item in news if item.get("aiStatus") == "pending"
    )
    print("Mevcut benzersiz kayıt:", len(news))
    print("Bekleyen kayıt:", pending_before)

    articles = fetch_all_articles()
    if not articles:
        raise SystemExit("Kaynak taramasında haber bulunamadı; news.json korunuyor.")

    # Take one backup before the first possible modification.
    backup_file = DATA_DIR / (
        "news.backup.merge."
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".json"
    )
    shutil.copy2(DATA_FILE, backup_file)
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
        for attempt in range(4):
            last_result = process_article(article, gemini_key)
            if last_result.get("aiStatus") == "completed":
                generated = last_result
                break

            error_text = last_result.get("aiError", "")
            if "HTTP 429" not in error_text:
                break

            if attempt < 3:
                wait_seconds = 60 * (2 ** attempt)
                print(
                    f"Gemini 429 limiti. {wait_seconds} saniye bekleniyor "
                    f"(deneme {attempt + 1}/4)."
                )
                time.sleep(wait_seconds)

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
            # Keep stable identity/source fields and update the AI result.
            current.update(ai_fields)
            current["sourceTitle"] = article.get("sourceTitle") or current.get("sourceTitle")
            current["source"] = current.get("source") or SOURCE_NAME
            current["imageUrl"] = article.get("imageUrl") or current.get("imageUrl")
            current["publishedAt"] = article.get("publishedAt") or current.get("publishedAt")
            current["fetchedAt"] = datetime.now(timezone.utc).isoformat()
            current.pop("aiError", None) if current.get("aiStatus") == "completed" else None
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
        save_temp_news(news)
        os.replace(TEMP_FILE, DATA_FILE)

        print(
            f"İlerleme: {completed} Gemini başarılı, {failed} başarısız, "
            f"{added} yeni haber."
        )

        if index < len(articles):
            time.sleep(20)

    print("\n========== MERGE SUMMARY ==========")
    print("Yeni haber:", added)
    print("Yeniden denenen:", retried)
    print("Korunan tamamlanmış kayıt:", skipped_completed)
    print("Bu çalışmada Gemini başarılı:", completed)
    print("Bu çalışmada başarısız:", failed)
    print("Toplam benzersiz arşiv:", len(news))
    print("Dosya:", DATA_FILE)


def main():
    print("\n========== NEWS FULL REBUILD ==========")

    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        raise SystemExit("GEMINI_API_KEY bulunamadı.")

    articles = fetch_all_articles()

    if not articles:
        raise SystemExit(
            "Hiç haber bulunamadı. Mevcut news.json korunuyor."
        )

    print("\n========== ARTICLE DETAILS ==========")
    print("Detayları alınacak haber:", len(articles))

    detailed_articles = []

    for index, article in enumerate(articles, 1):
        print(
            f"\nDetay {index}/{len(articles)}:",
            article["sourceTitle"]
        )

        try:
            article = fetch_article_detail(article)
            detailed_articles.append(article)
            print("İçerik karakteri:", len(article["articleText"]))

        except requests.RequestException as error:
            print("Detay sayfası alınamadı:", type(error).__name__)

            # RSS/kategori kartındaki bilgilerle yine de işlemeyi dene.
            detailed_articles.append(article)

        time.sleep(0.7)

    # Yayın tarihine göre yeni haberler önce.
    detailed_articles.sort(
        key=lambda item: item.get("publishedAt") or "",
        reverse=True
    )

    print("\n========== GEMINI PROCESSING ==========")
    print("Toplam haber:", len(detailed_articles))

    news = []
    completed = 0
    pending = 0

    if TEMP_FILE.exists():
        TEMP_FILE.unlink()

    for index, article in enumerate(detailed_articles, 1):
        print(f"\nHaber {index}/{len(detailed_articles)}")

        generated = process_article(article, gemini_key)

        item = {
            "id": article_id(article["sourceUrl"]),
            **generated,
            "sourceTitle": article["sourceTitle"],
            "source": SOURCE_NAME,
            "sourceUrl": article["sourceUrl"],
            "imageUrl": article.get("imageUrl") or None,
            "publishedAt": article.get("publishedAt"),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }

        news.append(item)

        if item["aiStatus"] == "completed":
            completed += 1
        else:
            pending += 1

        # İşlem yarıda kesilirse yeni arşiv geçici dosyada kalır.
        save_temp_news(news)

        time.sleep(2)

    if not news:
        raise SystemExit("Yeni haber arşivi boş. Mevcut dosya korunuyor.")

    # Eski dosyanın yedeğini al.
    if DATA_FILE.exists():
        backup_file = DATA_DIR / (
            "news.backup."
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )

        shutil.copy2(DATA_FILE, backup_file)
        print("\nEski haberlerin yedeği:", backup_file)

    # Yeni arşivi atomik olarak devreye al.
    os.replace(TEMP_FILE, DATA_FILE)

    print("\n========== REBUILD SUMMARY ==========")
    print("Toplam haber:", len(news))
    print("Gemini başarılı:", completed)
    print("Gemini bekleyen:", pending)
    print("AI sağlayıcı: Yalnızca Gemini")
    print("Dosya:", DATA_FILE)


if __name__ == "__main__":
    if "--merge" in sys.argv:
        rebuild_and_merge()
    else:
        main()
