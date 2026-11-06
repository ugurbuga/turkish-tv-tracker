from weekly_series_scraper import main as update_weekly_series
from update_ratings import main as update_ratings


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

    print("\n========== ALL TASKS COMPLETED ==========")


if __name__ == "__main__":
    main()
