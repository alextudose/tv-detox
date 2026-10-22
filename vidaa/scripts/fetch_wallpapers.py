"""Nature wallpapers from Wikimedia Commons (Quality/Featured images, free
licenses only) with the credit the home screen shows for each photo.

  python scripts/fetch_wallpapers.py candidates out.json   # list, for review
  python scripts/fetch_wallpapers.py download picks.json   # fetch the chosen ones
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "vidaa-detox/0.1 (personal TV home screen; github.com/alextudose/tv-detox)"
WEB = Path(__file__).resolve().parent.parent / "web"
QUERIES = ["Retezat lake", "Bucegi mountains", "Danube Delta", "Piatra Craiului", "Fagaras mountains",
           "Apuseni", "Ceahlau", "Rodna mountains", "Transfagarasan", "Bicaz gorge", "Maramures landscape",
           "Ciucas mountains", "Lake Balea", "Cheile Turzii", "Carpathians autumn forest"]
FREE = re.compile(r"^(CC0|CC BY(-SA)? [0-9.]+|Public domain|PD)", re.IGNORECASE)
QUALITY = ("Quality_images", "Featured_pictures_on_Wikimedia_Commons")


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def usable(info: dict) -> bool:
    """Landscape enough to fill a 16:9 screen, big enough, freely licensed."""
    meta = info.get("extmetadata", {})
    license_name = meta.get("LicenseShortName", {}).get("value", "")
    return (info["width"] >= 1920 and info["width"] / info["height"] >= 1.45
            and bool(FREE.match(license_name)))


def credit(title: str, info: dict) -> dict:
    meta = info.get("extmetadata", {})
    place = plain(meta.get("ObjectName", {}).get("value", "")) or Path(title).stem.removeprefix("File:")
    return {"title": title, "place": re.sub(r"[_]+", " ", place)[:60],
            "author": plain(meta.get("Artist", {}).get("value", ""))[:48],
            "license": meta.get("LicenseShortName", {}).get("value", ""),
            "source": info["descriptionurl"], "thumb": info.get("thumburl", info["url"])}


def _api(params: dict, attempts: int = 5) -> dict:
    url = API + "?" + urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    for attempt in range(attempts):
        time.sleep(1.5)  # stay well under Wikimedia's rate limits
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))


def candidates(out: str) -> None:
    found, seen = [], set()
    for query in QUERIES:
        reply = _api({"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 10,
                      "gsrsearch": f"{query} incategory:{'|'.join(QUALITY)}", "prop": "imageinfo",
                      "iiprop": "url|size|extmetadata", "iiurlwidth": 640})
        for page in reply.get("query", {}).get("pages", []):
            info = (page.get("imageinfo") or [{}])[0]
            if page["title"] not in seen and info and usable(info):
                seen.add(page["title"])
                found.append({"query": query, **credit(page["title"], info)})
    Path(out).write_text(json.dumps(found, indent=1, ensure_ascii=False))
    print(len(found), "candidates ->", out)


def download(picks: str) -> None:
    chosen = json.loads(Path(picks).read_text())
    (WEB / "wallpapers").mkdir(exist_ok=True)
    credits = []
    for n, pick in enumerate(chosen, 1):
        info = _api({"action": "query", "titles": pick["title"], "prop": "imageinfo",
                     "iiprop": "url|size|extmetadata", "iiurlwidth": 2400})["query"]["pages"][0]["imageinfo"][0]
        raw = WEB / "wallpapers" / f"{n:02d}.src"
        req = urllib.request.Request(info["thumburl"], headers={"User-Agent": UA})
        raw.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        out = WEB / "wallpapers" / f"{n:02d}.jpg"
        # cover-crop to 1920x1080, progressive JPEG around 250-400 KB
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf",
                        "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
                        "-q:v", "4", str(out)], check=True)
        raw.unlink()
        entry = credit(pick["title"], info)
        credits.append({"file": f"wallpapers/{out.name}", "place": pick.get("place") or entry["place"],
                        "author": pick.get("author") or entry["author"], "license": entry["license"], "source": entry["source"]})
        print(out.name, out.stat().st_size // 1024, "KB", credits[-1]["place"])
    (WEB / "wallpapers" / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    {"candidates": candidates, "download": download}[sys.argv[1]](sys.argv[2])
