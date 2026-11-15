"""Build Monday-Sunday ratings from daily reports, ending on archived Sundays.

Broadcasts stay separate. Rank is weekly; daily_rank preserves the daily rank.
Missing days or audience lists are described in info.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
RATINGS_DIR = ROOT_DIR / "data" / "ratings"
OUTPUT_DIR = ROOT_DIR / "data" / "rating_weekly"
AUDIENCES = ("TOTAL", "AB", "ABC1")


def build_weekly_report(week_end: date, daily_reports: dict) -> dict:
    if week_end.weekday() != 6:
        raise ValueError("Haftalık raporun son günü pazar olmalı.")

    week_start = week_end - timedelta(days=6)
    audiences = {audience: [] for audience in AUDIENCES}
    missing = []

    for offset in range(7):
        report_date = week_start + timedelta(days=offset)
        report = daily_reports.get(report_date)

        if report is None:
            missing.append(f"{report_date}: günlük reyting verisi eksik.")
            continue

        daily_audiences = report.get("audiences")
        if not isinstance(daily_audiences, dict):
            raise ValueError(f"{report_date}: audiences alanı nesne olmalı.")

        missing_audiences = []
        for audience in AUDIENCES:
            programs = daily_audiences.get(audience)
            if programs is None or programs == []:
                missing_audiences.append(audience)
                continue
            if not isinstance(programs, list):
                raise ValueError(f"{report_date}: {audience} listesi geçersiz.")

            for program in programs:
                if (
                    not isinstance(program, dict)
                    or not isinstance(program.get("rating"), (int, float))
                    or isinstance(program.get("rating"), bool)
                ):
                    raise ValueError(
                        f"{report_date}: {audience} program reytingi geçersiz."
                    )
                audiences[audience].append({
                    **program,
                    "date": report_date.isoformat(),
                    "daily_rank": program.get("rank"),
                })

        if missing_audiences:
            missing.append(
                f"{report_date}: {', '.join(missing_audiences)} listesi eksik."
            )

    for programs in audiences.values():
        programs.sort(key=lambda program: program["rating"], reverse=True)
        for rank, program in enumerate(programs, 1):
            program["rank"] = rank

    return {
        "weekStart": week_start.isoformat(),
        "weekEnd": week_end.isoformat(),
        "source": "Ratings",
        "audiences": audiences,
        "info": " ".join(missing),
    }


def main():
    if not RATINGS_DIR.is_dir():
        raise FileNotFoundError(f"Günlük reyting klasörü bulunamadı: {RATINGS_DIR}")

    daily_reports = {}
    for file_path in sorted(RATINGS_DIR.glob("*.json")):
        report_date = date.fromisoformat(file_path.stem)
        with file_path.open(encoding="utf-8") as file:
            report = json.load(file)
        if not isinstance(report, dict) or report.get("date") != report_date.isoformat():
            raise ValueError(f"Günlük reyting raporu veya tarihi geçersiz: {file_path}")
        daily_reports[report_date] = report

    sundays = sorted(day for day in daily_reports if day.weekday() == 6)
    if not sundays:
        print("Verisi bulunan pazar günü yok; haftalık rapor oluşturulmadı.")
        return

    reports = [build_weekly_report(day, daily_reports) for day in sundays]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0

    for report in reports:
        output_file = OUTPUT_DIR / f"{report['weekEnd']}.json"
        content = json.dumps(report, ensure_ascii=False, indent=4)
        if output_file.exists() and output_file.read_text(encoding="utf-8") == content:
            continue

        temp_file = output_file.with_suffix(".tmp")
        temp_file.write_text(content, encoding="utf-8")
        os.replace(temp_file, output_file)
        updated += 1

    print(
        f"Haftalık reyting: {len(reports)} hafta, "
        f"{updated} dosya güncellendi, "
        f"{sum(bool(report['info']) for report in reports)} eksik hafta."
    )
    print(f"Son hafta: {reports[-1]['weekStart']} - {reports[-1]['weekEnd']}")


if __name__ == "__main__":
    main()
