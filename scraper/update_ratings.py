import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from ratings_scraper import fetch_ratings_report, parse_ratings_report, save_ratings_report


REPORT_TYPES = {
    "TOTAL": "Top10 5+",
    "AB": "Top10 SES AB",
    "ABC1": "Top10 20+ABC1",
}


def main():
    today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    report_date = datetime.combine(
        today - timedelta(days=1),
        datetime.min.time()
    )

    output_file = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "ratings"
        / f"{report_date.strftime('%Y-%m-%d')}.json"
    )

    if output_file.exists():
        print(f"Rapor zaten mevcut, işlem atlandı: {output_file}")
        return

    print(f"Reyting raporu kontrol ediliyor: {report_date.date()}")

    audiences = {}

    try:
        with requests.Session() as session:
            for index, (audience, report_type) in enumerate(REPORT_TYPES.items()):
                print(f"{audience} raporu isteniyor...")

                html = fetch_ratings_report(
                    session,
                    report_date,
                    report_type
                )

                programs = parse_ratings_report(html)

                if not programs:
                    print(
                        f"{audience} raporu henüz yayınlanmamış "
                        "veya boş döndü. Sonraki kontrolde tekrar denenecek."
                    )
                    return

                audiences[audience] = programs
                print(f"{audience}: {len(programs)} program bulundu.")

                if index < len(REPORT_TYPES) - 1:
                    time.sleep(5)

        if len(audiences) != len(REPORT_TYPES):
            print("Tüm raporlar alınamadı. JSON kaydedilmedi.")
            return

        saved_file = save_ratings_report(report_date, audiences)

        print(f"Tüm raporlar başarıyla kaydedildi: {saved_file}")

    except Exception as error:
        print(f"Reyting raporu alınamadı: {error}")
        print("Sonraki saatlik kontrolde tekrar denenecek.")


if __name__ == "__main__":
    main()
