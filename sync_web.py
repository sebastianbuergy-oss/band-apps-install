"""Publish the browser version of a band app next to the iPhone installer.

Android users (and anyone without an iPhone) open the same app in the browser:
https://sebastianbuergy-oss.github.io/band-apps-install/<folder>/

The page is a straight copy of the app's bundled web/ folder plus a web app
manifest (so Chrome on Android offers "Zum Startbildschirm hinzufügen") and a
noindex tag, because this is a pre-release test copy for the band.

    python sync_web.py thy-gnosis      # copy, then commit and push yourself
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APPS = {
    "thy-gnosis": {"repo": "thy-gnosis-ios", "name": "Thy Gnosis", "bg": "#0b0b0d"},
    "days-of-ruin": {"repo": "days-of-ruin-ios", "name": "Days of Ruin", "bg": "#000000"},
}


def publish(folder: str) -> None:
    app = APPS[folder]
    src = ROOT / app["repo"] / "web"
    dst = HERE / folder
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    icon_src = ROOT / app["repo"] / "App" / "Assets.xcassets" / "AppIcon.appiconset" / "Icon-1024.png"
    icon = Image.open(icon_src).convert("RGB")
    for size in (180, 192, 512):
        icon.resize((size, size), Image.LANCZOS).save(dst / f"icon-{size}.png", optimize=True)

    manifest = {
        "name": app["name"],
        "short_name": app["name"],
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": app["bg"],
        "theme_color": app["bg"],
        "lang": "de",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (dst / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index = dst / "index.html"
    html = index.read_text(encoding="utf-8")
    anchor = '<meta name="color-scheme" content="dark">'
    if anchor not in html:
        raise SystemExit(f"{folder}: head anchor not found, page layout changed")
    extra = (
        '\n<meta name="robots" content="noindex,nofollow">'
        f'\n<meta name="theme-color" content="{app["bg"]}">'
        '\n<link rel="manifest" href="manifest.webmanifest">'
        '\n<link rel="apple-touch-icon" href="icon-180.png">'
        '\n<link rel="icon" type="image/png" href="icon-192.png">'
    )
    index.write_text(html.replace(anchor, anchor + extra, 1), encoding="utf-8", newline="\n")
    print(f"{folder}: {sum(1 for _ in dst.rglob('*') if _.is_file())} files -> {dst}")


if __name__ == "__main__":
    for name in sys.argv[1:] or ["thy-gnosis"]:
        publish(name)
