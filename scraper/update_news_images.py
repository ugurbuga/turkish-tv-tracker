import argparse
import json
import os
import sys
import time

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT_DIR / "data" / "news.json"

sys.path.insert(0, str(ROOT_DIR / "scraper"))

from crypto_utils import xor_decrypt, xor_encrypt
from news_scraper import fetch_article_detail


ENCRYPTED_ALLOWED_DOMAINS = (
    "FhwAGAwdCUEAA0MAExJNCAof",
    "AwIFRQsaGl4RGEwYBhQNHwQBA1FfXw==",
)

ALLOWED_DOMAINS = tuple(
    xor_decrypt(domain) for domain in ENCRYPTED_ALLOWED_DOMAINS
)


def decrypt_value(value):
    if not value:
        return value
    return xor_decrypt(value)


def update_records(records, limit=None):
    updated = 0
    failed = 0
    skipped = 0

    candidates = records[:limit] if limit else records

    for index, item in enumerate(candidates, 1):
        print(f"\n[{index}/{len(candidates)}] {item.get('sourceTitle', 'Başlıksız')}")

        try:
            encrypted_url = item.get("sourceUrl")

            if not encrypted_url:
                print("ATLANDI: Haber URL'si bulunamadı.")
                skipped += 1
                continue

            source_url = decrypt_value(encrypted_url)
            hostname = urlparse(source_url).hostname or ""

            if hostname not in ALLOWED_DOMAINS:
                print("ATLANDI: Beklenmeyen kaynak:", hostname)
                skipped += 1
                continue

            article = {
                "sourceTitle": item.get("sourceTitle", ""),
                "sourceUrl": source_url,
                "sourceDescription": "",
                "imageUrl": decrypt_value(item.get("imageUrl")),
                "images": [],
                "publishedAt": None,
                "articleText": ""
            }

            result = fetch_article_detail(article)

            if not result.get("articleText", "").strip():
                print("BAŞARISIZ: Haber metni alınamadı; kayıt korunacak.")
                failed += 1
                continue

            image_urls = list(dict.fromkeys(
                url for url in result.get("images", [])
                if isinstance(url, str) and url.startswith("https://")
            ))

            item["images"] = [
                xor_encrypt(url) for url in image_urls
            ]

            print("BAŞARILI:", len(image_urls), "görsel")
            updated += 1

        except Exception as error:
            print("HATA:", repr(error))
            failed += 1

        if index < len(candidates):
            time.sleep(0.7)

    return updated, failed, skipped


def save_records(records):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = DATA_FILE.with_name(
        f"news.backup_{timestamp}.json"
    )
    temp_file = DATA_FILE.with_name("news.json.tmp")

    backup_file.write_bytes(DATA_FILE.read_bytes())
    print("\nYEDEK:", backup_file)

    try:
        with temp_file.open("w", encoding="utf-8") as file:
            json.dump(
                records,
                file,
                ensure_ascii=False,
                indent=2
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_file, DATA_FILE)
        print("JSON başarıyla güncellendi.")

    finally:
        if temp_file.exists():
            temp_file.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Değişiklikleri yedek alarak JSON dosyasına kaydet."
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

    if not DATA_FILE.exists():
        raise SystemExit("data/news.json bulunamadı.")

    with DATA_FILE.open(encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise SystemExit("Beklenmeyen JSON formatı: liste bekleniyordu.")

    print("Toplam arşiv haberi:", len(records))
    print("Mod:", "GERÇEK GÜNCELLEME" if args.apply else "DENEME")

    updated, failed, skipped = update_records(
        records,
        args.limit
    )

    print("\n========== ÖZET ==========")
    print("Başarılı:", updated)
    print("Başarısız:", failed)
    print("Atlanan:", skipped)

    if args.apply and updated:
        save_records(records)
    elif args.apply:
        print("Başarılı kayıt yok; JSON değiştirilmedi.")
    else:
        print("\nDENEME MODU: JSON dosyasına yazılmadı.")
        print("Gerçek güncelleme için --apply kullanın.")


if __name__ == "__main__":
    main()
