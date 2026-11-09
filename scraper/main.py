from weekly_series_scraper import main as update_weekly_series
from update_ratings import main as update_ratings
from update_youtube_videos import main as update_youtube_videos


def main():
    print("\n========== WEEKLY SERIES ==========")

    try:
        update_weekly_series()
    except Exception as error:
        print(f"Haftalık dizi tablosu güncellenemedi: {error}")

    print("\n========== DAILY RATINGS ==========")

    try:
        update_ratings()
    except Exception as error:
        print(f"Reyting verileri güncellenemedi: {error}")

    print("\n========== YOUTUBE VIDEOS ==========")

    try:
        update_youtube_videos()
    except Exception as error:
        print(f"YouTube videoları güncellenemedi: {error}")

    print("\n========== ALL TASKS COMPLETED ==========")


if __name__ == "__main__":
    main()
