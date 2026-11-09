
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API_KEY = os.environ["YOUTUBE_API_KEY"]

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_FILE = ROOT / "data" / "youtube_channels.json"
OUTPUT_FILE = ROOT / "data" / "youtube_videos.json"

MAX_RESULTS = 50


def fetch_videos(channel):
    params = urllib.parse.urlencode({
        "part": "snippet,contentDetails",
        "playlistId": channel["uploadsPlaylistId"],
        "maxResults": MAX_RESULTS,
        "key": API_KEY
    })

    url = f"https://www.googleapis.com/youtube/v3/playlistItems?{params}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TurkishTVTracker/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read())

    videos = []

    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        video_id = content.get("videoId")

        if not video_id:
            continue

        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        )

        videos.append({
            "videoId": video_id,
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "publishedAt": content.get("videoPublishedAt")
                or snippet.get("publishedAt"),
            "thumbnail": thumbnail.get("url"),
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })

    return videos


def main():
    with open(CHANNELS_FILE, encoding="utf-8") as file:
        channels = json.load(file)

    results = []
    failed_channels = []

    for channel in channels:
        try:
            videos = fetch_videos(channel)

            results.append({
                "channelId": channel["channelId"],
                "name": channel["name"],
                "handle": channel["handle"],
                "videoCount": len(videos),
                "videos": videos
            })

            print(f"OK: {channel['name']} - {len(videos)} video")

        except Exception as error:
            failed_channels.append(channel["name"])
            print(f"HATA: {channel['name']} - {error}")

    if failed_channels:
        print("\nBazı kanallar alınamadı. Mevcut JSON korunuyor.")
        return

    payload = {
        "channelCount": len(results),
        "totalVideos": sum(channel["videoCount"] for channel in results),
        "channels": results
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print(f"\nToplam kanal: {len(results)}")
    print(f"Toplam video: {payload['totalVideos']}")
    print(f"Kaydedildi: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
