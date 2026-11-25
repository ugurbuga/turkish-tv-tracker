import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

import news_scraper


class NewsScraperRetryTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "sourceTitle": "Test news",
            "sourceUrl": "https://example.com/news/",
            "articleText": "Article text " * 10,
            "_archiveDate": "2026-11-15",
        }

    def test_failed_or_invalid_ai_responses_retry_ten_times(self):
        for response in (RuntimeError("AI unavailable"), {"title": "", "content": ""}):
            with self.subTest(response=response), patch(
                "news_scraper.generate_with_gemini"
            ) as generate, patch("news_scraper.time.sleep") as sleep:
                if isinstance(response, Exception):
                    generate.side_effect = response
                else:
                    generate.return_value = response

                result = news_scraper.process_article(self.article, "test-key")

                self.assertEqual(generate.call_count, 10)
                self.assertEqual(sleep.call_args_list, [call(5)] * 9)
                self.assertEqual(result["aiStatus"], "pending")

    def test_pending_article_is_retried_and_updated_without_duplicate(self):
        current = {**self.article, "aiStatus": "pending"}
        records = [current]
        existing = {self.article["sourceUrl"]: current}
        with patch(
            "news_scraper.fetch_article_detail", return_value=dict(self.article)
        ), patch(
            "news_scraper.generate_with_gemini",
            side_effect=[
                RuntimeError("AI unavailable"),
                {"title": "Title", "content": "Content", "series": None},
            ],
        ) as generate, patch("news_scraper.time.sleep") as sleep, patch(
            "news_scraper.save_daily_news"
        ) as save:
            success = news_scraper.process_listing_page(
                1, [dict(self.article)], records, existing, "test-key"
            )

        self.assertTrue(success)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(5)])
        self.assertEqual(len(records), 1)
        self.assertEqual(current["aiStatus"], "completed")
        save.assert_called_once_with(records)

    def test_successful_ai_response_does_not_wait(self):
        with patch(
            "news_scraper.generate_with_gemini",
            return_value={"title": "Title", "content": "Content"},
        ) as generate, patch("news_scraper.time.sleep") as sleep:
            result = news_scraper.process_article(self.article, "test-key")

        self.assertEqual(result["aiStatus"], "completed")
        generate.assert_called_once()
        sleep.assert_not_called()

    def test_main_checks_entire_archive_once_per_run(self):
        for fail in (False, True):
            with self.subTest(fail=fail), TemporaryDirectory() as directory:
                root = Path(directory)
                pending = {**self.article, "aiStatus": "pending"}
                other = {
                    **pending,
                    "sourceUrl": "https://example.com/older-news/",
                }
                completed = {
                    **self.article,
                    "sourceUrl": "https://example.com/completed/",
                    "aiStatus": "completed",
                }
                (root / "2026-11-15.json").write_text(
                    json.dumps([pending, completed]), encoding="utf-8"
                )
                (root / "2026-11-14.json").write_text(
                    json.dumps([other]), encoding="utf-8"
                )

                with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                    "news_scraper.DATA_DIR", root
                ), patch("news_scraper.NEWS_DIR", root), patch(
                    "news_scraper.request_listing_with_retry",
                    side_effect=lambda _page: [dict(pending)],
                ) as listing, patch(
                    "news_scraper.fetch_article_detail",
                    side_effect=lambda article: {
                        **article, "articleText": "Article text " * 10
                    },
                ) as fetch, patch(
                    "news_scraper.generate_with_gemini",
                    return_value={"title": "Title", "content": "Content"},
                    side_effect=RuntimeError("AI unavailable") if fail else None,
                ) as generate, patch("news_scraper.time.sleep"), patch("builtins.print"):
                    news_scraper.main()
                    news_scraper.main()
                    saved = news_scraper.load_news_archive()

                self.assertEqual(fetch.call_count, 4 if fail else 2)
                self.assertEqual(generate.call_count, 40 if fail else 2)
                self.assertEqual(
                    sum(item["aiStatus"] == "pending" for item in saved),
                    2 if fail else 0,
                )
                self.assertEqual(len(saved), 3)
                self.assertEqual(
                    listing.call_args_list,
                    [call(1), call(1)],
                )

    def test_completed_article_is_not_reprocessed(self):
        current = {**self.article, "aiStatus": "completed"}
        with patch("news_scraper.fetch_article_detail") as fetch:
            success = news_scraper.process_listing_page(
                1,
                [dict(self.article)],
                [current],
                {self.article["sourceUrl"]: current},
                "test-key",
            )

        self.assertTrue(success)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
