import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import rating_weekly


class WeeklyRatingsTests(unittest.TestCase):
    def test_seven_daily_lists_are_sorted_without_merging_broadcasts(self):
        sunday = date(2026, 11, 8)
        daily_reports = {}
        for offset in range(7):
            day = sunday - timedelta(days=offset)
            daily_reports[day] = {
                "audiences": {
                    audience: [{
                        "rank": 1,
                        "name": "Same program",
                        "channel": "Channel",
                        "rating": offset + index / 10,
                        "share": 20,
                    }]
                    for index, audience in enumerate(rating_weekly.AUDIENCES)
                }
            }

        report = rating_weekly.build_weekly_report(sunday, daily_reports)

        self.assertEqual(report["weekStart"], "2026-11-02")
        self.assertEqual(report["weekEnd"], "2026-11-08")
        self.assertEqual(report["info"], "")
        for index, audience in enumerate(rating_weekly.AUDIENCES):
            programs = report["audiences"][audience]
            self.assertEqual(len(programs), 7)
            self.assertEqual(
                [program["rating"] for program in programs],
                [offset + index / 10 for offset in range(6, -1, -1)],
            )
            self.assertEqual([program["rank"] for program in programs], list(range(1, 8)))
            self.assertEqual(
                [program["date"] for program in programs],
                [(sunday - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)],
            )
            self.assertTrue(all(program["daily_rank"] == 1 for program in programs))
            self.assertTrue(all(program["share"] == 20 for program in programs))
        self.assertEqual(daily_reports[sunday]["audiences"]["TOTAL"][0]["rank"], 1)

    def test_missing_days_and_audiences_are_reported(self):
        sunday = date(2026, 11, 8)
        report = rating_weekly.build_weekly_report(sunday, {
            sunday: {
                "audiences": {
                    "TOTAL": [{"rank": 1, "rating": 5}],
                    "AB": [],
                }
            }
        })

        self.assertEqual(len(report["audiences"]["TOTAL"]), 1)
        self.assertEqual(report["audiences"]["AB"], [])
        self.assertEqual(report["audiences"]["ABC1"], [])
        self.assertIn("2026-11-08: AB, ABC1", report["info"])
        for offset in range(1, 7):
            self.assertIn((sunday - timedelta(days=offset)).isoformat(), report["info"])

    def test_main_generates_all_sundays_but_not_unfinished_week(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            daily_dir = root / "ratings"
            output_dir = root / "rating_weekly"
            daily_dir.mkdir()
            for day in ("2026-11-01", "2026-11-08", "2026-11-12"):
                (daily_dir / f"{day}.json").write_text(json.dumps({
                    "date": day,
                    "audiences": {
                        audience: [{"rank": 1, "rating": 5}]
                        for audience in rating_weekly.AUDIENCES
                    },
                }), encoding="utf-8")

            with patch("rating_weekly.RATINGS_DIR", daily_dir), patch(
                "rating_weekly.OUTPUT_DIR", output_dir
            ):
                rating_weekly.main()
                files = sorted(output_dir.glob("*.json"))
                self.assertEqual(
                    [file.name for file in files],
                    ["2026-11-01.json", "2026-11-08.json"],
                )
                modified = [file.stat().st_mtime_ns for file in files]
                rating_weekly.main()
                self.assertEqual([file.stat().st_mtime_ns for file in files], modified)
                self.assertEqual(
                    json.loads(files[-1].read_text())["weekEnd"], "2026-11-08"
                )

    def test_invalid_rating_is_not_silently_skipped(self):
        sunday = date(2026, 11, 8)
        with self.assertRaisesRegex(ValueError, "TOTAL"):
            rating_weekly.build_weekly_report(sunday, {
                sunday: {"audiences": {"TOTAL": [{"rating": "invalid"}]}}
            })


if __name__ == "__main__":
    unittest.main()
