
import time
from datetime import date, datetime, timedelta

import requests

from ratings_scraper import (
    fetch_ratings_report,
    parse_ratings_report,
    save_ratings_report
)


# ==================================================
# TARİH AYARLARI (Dahil)
# ==================================================

START_DATE = "2026-10-07"
END_DATE = "2026-11-05"
MIN_DATE = date(2023, 1, 1)

# ==================================================

REPORT_TYPES = {
    "TOTAL": "Top10 5+",
    "AB": "Top10 SES AB",
    "ABC1": "Top10 20+ABC1"
}

REQUEST_INTERVAL = 3


def main():
    start_date = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    end_date = datetime.strptime(END_DATE, "%Y-%m-%d").date()

    if start_date < MIN_DATE:
        raise ValueError("2023-01-01 öncesi için reyting verisi bulunmuyor!")
    if start_date > end_date:
        raise ValueError("Başlangıç tarihi bitiş tarihinden büyük olamaz!")

    total_days = (end_date - start_date).days + 1
    total_requests = total_days * len(REPORT_TYPES)

    completed_requests = 0
    successful_days = 0
    failed_days = 0

    print("=" * 50)
    print("RATINGS DATE RANGE FETCH")
    print("=" * 50)
    print(f"Tarih aralığı: {START_DATE} - {END_DATE}")
    print(f"Toplam gün: {total_days}")
    print(f"Toplam istek: {total_requests}")
    print(f"İstek aralığı: {REQUEST_INTERVAL} saniye")
    print("=" * 50)

    with requests.Session() as session:

        for day_index in range(total_days):
            report_date = datetime.combine(
                start_date + timedelta(days=day_index),
                datetime.min.time()
            )

            print(f"\n[{day_index + 1}/{total_days}] {report_date.date()}")

            audiences = {}
            day_success = True

            for audience, report_type in REPORT_TYPES.items():
                completed_requests += 1

                print(
                    f"  [{completed_requests}/{total_requests}] "
                    f"{audience} çekiliyor...",
                    end=" ",
                    flush=True
                )

                try:
                    html = fetch_ratings_report(
                        session,
                        report_date,
                        report_type
                    )

                    programs = parse_ratings_report(html)

                    if not programs:
                        raise ValueError("Program verisi bulunamadı!")

                    audiences[audience] = programs

                    print(f"OK ({len(programs)} program)")

                except Exception as error:
                    day_success = False
                    print(f"HATA: {error}")

                if completed_requests < total_requests:
                    time.sleep(REQUEST_INTERVAL)

            if day_success and len(audiences) == len(REPORT_TYPES):
                output_file = save_ratings_report(report_date, audiences)
                successful_days += 1
                print(f"  Kaydedildi: {output_file.name}")
            else:
                failed_days += 1
                print("  Gün tamamlanamadı. JSON dosyası kaydedilmedi.")

    print("\n" + "=" * 50)
    print("İŞLEM TAMAMLANDI")
    print("=" * 50)
    print(f"Başarılı gün: {successful_days}")
    print(f"Hatalı gün: {failed_days}")
    print(f"Tamamlanan istek: {completed_requests}/{total_requests}")


if __name__ == "__main__":
    main()
