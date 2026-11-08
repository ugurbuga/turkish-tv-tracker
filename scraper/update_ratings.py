
import time

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from ratings_scraper import (
    fetch_ratings_report,
    parse_ratings_report,
    save_ratings_report,
)


REPORT_TYPES = {
    "TOTAL": "Top10 5+",
    "AB": "Top10 SES AB",
    "ABC1": "Top10 20+ABC1",
}


def main():
    ratings_dir = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "ratings"
    )

    ratings_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    yesterday = today - timedelta(days=1)

    existing_dates = []

    for file in ratings_dir.glob("*.json"):
        try:
            existing_dates.append(
                datetime.strptime(file.stem, "%Y-%m-%d").date()
            )
        except ValueError:
            continue
        
    if existing_dates:
        start_date = min(existing_dates) - timedelta(days=5)
    else:
        start_date = yesterday

    if start_date > yesterday:
        print("Eksik reyting günü bulunmuyor.")
        return

    print(f"Reyting kontrol aralığı: {start_date} - {yesterday}")

    with requests.Session() as session:
        report_date = start_date

        while report_date <= yesterday:
            output_file = ratings_dir / f"{report_date.isoformat()}.json"

            if output_file.exists():
                print(f"Rapor zaten mevcut, atlandı: {report_date}")
                report_date += timedelta(days=1)
                continue

            print(f"\nReyting raporu kontrol ediliyor: {report_date}")

            date_datetime = datetime.combine(
                report_date,
                datetime.min.time()
            )

            audiences = {}
            complete = True

            try:
                for index, (audience, report_type) in enumerate(
                    REPORT_TYPES.items()
                ):
                    print(f"{audience} raporu isteniyor...")

                    html = fetch_ratings_report(
                        session,
                        date_datetime,
                        report_type
                    )

                    programs = parse_ratings_report(html)

                    if not programs:
                        print(
                            f"{audience} raporu henüz yayınlanmamış "
                            "veya boş döndü."
                        )
                        complete = False
                        break

                    audiences[audience] = programs

                    print(
                        f"{audience}: {len(programs)} program bulundu."
                    )

                    if index < len(REPORT_TYPES) - 1:
                        time.sleep(5)

                if complete and len(audiences) == len(REPORT_TYPES):
                    saved_file = save_ratings_report(
                        date_datetime,
                        audiences
                    )
                    print(f"Rapor kaydedildi: {saved_file}")
                else:
                    print(
                        f"{report_date} tamamlanamadı. "
                        "Sonraki kontrolde tekrar denenecek."
                    )

            except Exception as error:
                print(f"{report_date} alınamadı: {error}")
                print("Sonraki kontrolde tekrar denenecek.")

            report_date += timedelta(days=1)
            time.sleep(5)


if __name__ == "__main__":
    main()
