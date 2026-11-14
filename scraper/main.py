from weekly_series_scraper import main as update_weekly_series
from update_ratings import main as update_ratings
from update_tv_series import main as update_tv_series
from update_youtube_videos import main as update_youtube_videos
from news_scraper import main as update_news


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

    print("\n========== TV SERIES METADATA ==========")
    try:
        update_tv_series()
    except Exception as error:
        print(f"Dizi detayları güncellenemedi: {error}")


    print("\n========== DAILY NEWS ==========")
    try:
        update_news()
    except Exception as error:
        print(f"Haber verileri güncellenemedi: {error}")

    print("\n========== YOUTUBE VIDEOS ==========")

    try:
        update_youtube_videos()
    except Exception as error:
        print(f"YouTube videoları güncellenemedi: {error}")

    print("\n========== ALL TASKS COMPLETED ==========")


if __name__ == "__main__":
    main()
