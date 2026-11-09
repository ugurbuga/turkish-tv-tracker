
import json
import os
import urllib.parse
import urllib.request

API_KEY = os.environ["YOUTUBE_API_KEY"]

CHANNELS = [
    ("Anne Yarısı", "@AnneYarısıDizi"),
    ("Haysiyet", "@HaysiyetKANALD"),
    ("Tuzlu Kahve", "@TuzluKahveStarTV"),
    ("Mehmed: Fetihler Sultanı", "@mehmedfetihlersultani"),
    ("Sevdan Bir Ateş", "@SevdanBirAtesDizi"),
    ("Halef: Köklerin Çağrısı", "@HalefKoklerinCagrisiDizisi"),
    ("Muhtemel Aşk", "@muhtemelaskdizi"),
    ("Taşacak Bu Deniz", "@tasacakbudeniztrt"),
    ("Güller ve Günahlar", "@GüllerveGünahlar"),
    ("Başkalarının Hayatı", "@BaşkalarınınHayatıResmi"),
    ("Gönül Dağı", "@GonulDagiTRT"),
    ("Ömür Usta", "@ÖmürUstaDizi"),
    ("Daha On Yedi", "@DahaOnYediDizisi"),
    ("Kod Adı: Kırlangıç", "@kodadikirlangic"),
    ("Teşkilat", "@TeskilatTRT"),
    ("Altı Üstü İstanbul", "@AltıÜstüİstanbul"),
    ("Uzak Şehir", "@UzakSehirDizi"),
    ("Evlilik Güzeldir", "@evlilikgüzeldirtrt"),
    ("Güneşin Doğduğu Yer", "@GüneşinDoğduğuYeratv"),
    ("Sevdiğim Sensin", "@sevdigimsensinresmi"),
    ("Kızılcık Şerbeti", "@kizilcikserbetidizi"),
    ("Yeraltı", "@Yeraltidizisi"),
]

results = []

for name, handle in CHANNELS:
    params = urllib.parse.urlencode({
        "part": "id,contentDetails,snippet",
        "forHandle": handle,
        "key": API_KEY
    })

    url = f"https://www.googleapis.com/youtube/v3/channels?{params}"

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read())

        items = data.get("items", [])

        if items:
            channel = items[0]
            results.append({
                "name": name,
                "handle": handle,
                "channelId": channel["id"],
                "uploadsPlaylistId": (
                    channel["contentDetails"]["relatedPlaylists"]["uploads"]
                )
            })
            print(f"OK: {name}")
        else:
            results.append({
                "name": name,
                "handle": handle,
                "channelId": None,
                "uploadsPlaylistId": None
            })
            print(f"BULUNAMADI: {name}")

    except Exception as error:
        print(f"HATA: {name} - {error}")

with open("resolved_channels.json", "w", encoding="utf-8") as file:
    json.dump(results, file, ensure_ascii=False, indent=2)

print("\nSonuç: resolved_channels.json")
