#!/usr/bin/env python3
"""Download poster images for Turkish TV Tracker series.

Run from the repository root:
    python3 download_series_posters.py

Images are saved under assets/series/ and a mapping is written to
assets/series/series_images.json.
"""
from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OUTPUT_DIR = Path("assets/series")

POSTERS = {
    "Anne Yarısı": ("anne-yarisi.jpg", "https://nezaman.be/uploads/series/r/r-2026-94001-anne-yarisi.jpg"),
    "Haysiyet": ("haysiyet.jpg", "https://static.birgun.net/resim/haber/2026/09/12/yeni-dizi-haysiyetin-reyting-orani-kac-oldu.jpg"),
    "Tuzlu Kahve": ("tuzlu-kahve.jpg", "https://tr.web.img2.acsta.net/img/fd/e1/fde1d6f9f77e74c634215a95d83c3c0e.jpg"),
    "Mehmed: Fetihler Sultanı": ("mehmed-fetihler-sultani.jpg", "https://galeri14.uludagsozluk.com/896/mehmed-fetihler-sultani-dizisi_2349396.jpg"),
    "Sevdan Bir Ateş": ("sevdan-bir-ates.jpg", "https://www.gazetekritik.com/cropImages/1280x/uploads/haberler/2026/8/1208-murat-unalmis-kimdir-yeni-dizisi-sevdan-bir-ates-ne-zaman-basliyor.jpg"),
    "Halef: Köklerin Çağrısı": ("halef-koklerin-cagrisi.jpg", "https://images.justwatch.com/poster/335866061/s718/sezon-1.jpg"),
    "Muhtemel Aşk": ("muhtemel-ask.jpg", "https://artworks.thetvdb.com/banners/v4/series/479050/posters/6a289785e9db2.jpg"),
    "Taşacak Bu Deniz": ("tasacak-bu-deniz.jpg", "https://i0.wp.com/turkision.com/wp-content/uploads/2025/10/watch-tasacak-bu-deniz-with-english-subtitles.jpg?fit=650%2C900&ssl=1"),
    "Güller ve Günahlar": ("guller-ve-gunahlar.jpg", "https://gunaydinsamsuncom.teimg.com/gunaydinsamsun-com/uploads/2025/09/agency/dha/guller-ve-gunahlar-dan-yeni-afis.jpg"),
    "Başkalarının Hayatı": ("baskalarinin-hayati.jpg", "https://media.startv.com.tr/star-tv/images/1%28267%29.jpg"),
    "Gönül Dağı": ("gonul-dagi.jpg", "https://pbs.twimg.com/media/G0FvINUX0AAx0jx?format=jpg&name=large"),
    "Ömür Usta": ("omur-usta.webp", "https://cdn.bingebase.com/seasons/355232/posters/sqt4CJDdGsUuxlruiKbVauF0wcF.webp"),
    "Daha On Yedi": ("daha-on-yedi.jpg", "https://image.kanald.com.tr/i/kanald/100/0x0/6a0d5e88573a03dd661c97aa.jpg"),
    "Kod Adı: Kırlangıç": ("kod-adi-kirlangic.jpg", "https://img.dizi.la/uploads/76873/F-AKtE4WIAEdzvd.jpeg"),
    "Teşkilat": ("teskilat.jpg", "https://m.media-amazon.com/images/M/MV5BNDE3MzI5ZDItYzRhMC00MTVkLTk0OWQtMmJjYjc3OTM0NmNlXkEyXkFqcGc%40._V1_FMjpg_UX1000_.jpg"),
    "Altı Üstü İstanbul": ("alti-ustu-istanbul.jpg", "https://image.tmdb.org/t/p/original/qnImGr6hA1GJb0IBxulxoOswF6D.jpg"),
    "Uzak Şehir": ("uzak-sehir.jpg", "https://image.kanald.com.tr/i/kanald/100/0x0/6729d430f072a7bd36dcbc20.jpg"),
    "Evlilik Güzeldir": ("evlilik-guzeldir.jpg", "https://tr.web.img3.acsta.net/img/ea/3c/ea3c75ca09203cd2307faecfb968b8a8.jpg"),
    "Güneşin Doğduğu Yer": ("gunesin-dogdugu-yer.webp", "https://tr.canlitv.watch/blogres/gunesin-dogdugu-yer-dizisi-afisi-1780840300.webp"),
    "Sevdiğim Sensin": ("sevdigim-sensin.jpg", "https://pictures.betaseries.com/fonds/poster/d29ffccbe0e797b9e16001998610c999.jpg"),
    "Kızılcık Şerbeti": ("kizilcik-serbeti.jpg", "https://artworks.thetvdb.com/banners/v4/series/425337/posters/66e57a3ca84b6.jpg"),
    "Yeraltı": ("yeralti.jpg", "https://fav10.net/forum/attachments/1001533344-jpg.138666/"),
}

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    success = 0

    for name, (filename, url) in POSTERS.items():
        destination = OUTPUT_DIR / filename
        request = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TurkishTVTracker/1.0)"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                data = response.read()

            if not data or not (
                data.startswith(b"\xff\xd8\xff")
                or data.startswith(b"\x89PNG\r\n\x1a\n")
                or data.startswith(b"RIFF") and data[8:12] == b"WEBP"
                or data.startswith(b"GIF8")
            ):
                raise ValueError(f"Yanıt görsel değil (Content-Type: {content_type})")

            destination.write_bytes(data)
            manifest[name] = f"assets/series/{filename}"
            success += 1
            print(f"OK  {name}: {len(data) / 1024:.1f} KB")
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
            print(f"ERR {name}: {error}")
        time.sleep(0.25)

    manifest_path = OUTPUT_DIR / "series_images.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nTamamlandı: {success}/{len(POSTERS)} görsel indirildi.")
    print(f"Eşleştirme dosyası: {manifest_path}")

if __name__ == "__main__":
    main()
