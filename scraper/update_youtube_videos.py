
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API_KEY = os.environ["YOUTUBE_API_KEY"]

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_FILE = ROOT / "data" / "tv_series.json"
OUTPUT_DIR = ROOT / "data" / "youtubevideos"

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
            thumbnails.get("maxres")
            or thumbnails.get("standard")
            or thumbnails.get("high")
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


def save_channel_videos(channel, videos):
    output_path = ROOT / channel["videosPath"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "channelId": channel["channelId"],
        "name": channel["name"],
        "handle": channel["handle"],
        "videoCount": len(videos),
        "videos": videos
    }

    temp_path = output_path.with_suffix(".tmp")

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    temp_path.replace(output_path)


def main():
    with open(CHANNELS_FILE, encoding="utf-8") as file:
        channels = json.load(file)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failed_channels = []

    for channel in channels:
        channel["videosPath"] = (
            f"data/youtubevideos/{channel['channelId']}.json"
        )

        try:
            videos = fetch_videos(channel)
            save_channel_videos(channel, videos)

            success_count += 1

            print(
                f"OK: {channel['name']} - "
                f"{len(videos)} video"
            )

        except Exception as error:
            failed_channels.append(channel["name"])
            print(f"HATA: {channel['name']} - {error}")

    with open(CHANNELS_FILE, "w", encoding="utf-8") as file:
        json.dump(channels, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print("\n--- SONUÇ ---")
    print(f"Başarılı kanal: {success_count}/{len(channels)}")
    print(f"Başarısız kanal: {len(failed_channels)}")

    if failed_channels:
        print("Hata alınan kanallar:")
        for name in failed_channels:
            print(f"- {name}")

    print(f"Video klasörü: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
