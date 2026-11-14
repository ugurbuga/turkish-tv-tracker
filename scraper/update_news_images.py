import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scraper"))

from news_scraper import (
    ALLOWED_DOMAINS,
    backup_news_archive,
    fetch_article_detail,
    load_news_archive,
    save_daily_news,
)


def update_records(records, limit=None):
    updated = 0
    failed = 0
    skipped = 0

    candidates = records[:limit] if limit else records

    for index, item in enumerate(candidates, 1):
        print(
            f"\n[{index}/{len(candidates)}] "
            f"{item.get('sourceTitle', 'Başlıksız')}"
        )

        try:
            source_url = item.get("sourceUrl")
            if not source_url:
                print("ATLANDI: Haber URL'si bulunamadı.")
                skipped += 1
                continue

            hostname = urlparse(source_url).hostname or ""
            if hostname not in ALLOWED_DOMAINS:
                print("ATLANDI: Beklenmeyen kaynak:", hostname)
                skipped += 1
                continue

            article = {
                "sourceTitle": item.get("sourceTitle", ""),
                "sourceUrl": source_url,
                "sourceDescription": item.get("sourceDescription", ""),
                "imageUrl": item.get("imageUrl"),
                "images": item.get("images", []),
                "publishedAt": item.get("publishedAt"),
                "articleText": "",
            }

            result = fetch_article_detail(article)

            found_images = result.get("images", [])
            if not isinstance(found_images, list):
                found_images = []

            existing_images = item.get("images", [])
            if not isinstance(existing_images, list):
                existing_images = []

            merged = []
            seen = set()

            for url in existing_images + found_images:
                if (
                    isinstance(url, str)
                    and url.startswith(("https://", "http://"))
                    and url not in seen
                    and url != result.get("imageUrl")
                ):
                    seen.add(url)
                    merged.append(url)

            item["images"] = merged

            if result.get("imageUrl"):
                item["imageUrl"] = result["imageUrl"]

            print("BAŞARILI:", len(merged), "görsel")
            updated += 1

        except Exception as error:
            print("HATA:", repr(error))
            failed += 1

        if index < len(candidates):
            time.sleep(0.7)

    return updated, failed, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Günlük haber arşivindeki görselleri günceller."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Yedek alarak günlük arşive kaydet."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="İşlenecek maksimum haber sayısı."
    )

    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit en az 1 olmalı.")

    records = load_news_archive()
    if not records:
        raise SystemExit("Günlük veya eski haber arşivi bulunamadı.")

    print("Toplam arşiv haberi:", len(records))
    print("Mod:", "GERÇEK GÜNCELLEME" if args.apply else "DENEME")

    updated, failed, skipped = update_records(records, args.limit)

    print("\n========== ÖZET ==========")
    print("Başarılı:", updated)
    print("Başarısız:", failed)
    print("Atlanan:", skipped)

    if args.apply and updated:
        backup = backup_news_archive("images")
        if backup:
            print("YEDEK:", backup)

        save_daily_news(records)
        print("Günlük haber arşivi güncellendi.")
    elif args.apply:
        print("Başarılı kayıt yok; arşiv değiştirilmedi.")
    else:
        print("\nDENEME MODU: Arşive yazılmadı.")
        print("Gerçek güncelleme için --apply kullanın.")


if __name__ == "__main__":
    main()
