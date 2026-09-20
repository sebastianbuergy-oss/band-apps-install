"""OTA distribution (master brief, section 10).

Sebastian installs straight onto his registered iPhones, so OTA is a
first-class output, not an afterthought: checksum, size, manifest, install
page and QR code are produced for every ad-hoc build.

Nothing here publishes over the live install page by itself.  Output lands
in ``data/ota/<build_id>/`` and only a configured ``ota_publish_dir`` plus
an explicit publish step copies it anywhere - priority 3 of the brief is
"bestehende Projekte nicht beschaedigen".
"""
from __future__ import annotations

import datetime as _dt
import html
import shutil
from pathlib import Path
from typing import Any

from . import qr
from .errors import ValidationError
from .ipa import distribution_kind, inspect
from .projects import MODE_AD_HOC

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict>
          <key>kind</key><string>software-package</string>
          <key>url</key><string>{ipa_url}</string>
        </dict>
        <dict>
          <key>kind</key><string>display-image</string>
          <key>url</key><string>{icon_url}</string>
        </dict>
        <dict>
          <key>kind</key><string>full-size-image</string>
          <key>url</key><string>{icon_url}</string>
        </dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key><string>{bundle_id}</string>
        <key>bundle-version</key><string>{bundle_version}</string>
        <key>kind</key><string>software</string>
        <key>title</key><string>{title}</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
"""


def _plist_escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def manifest_plist(*, bundle_id: str, bundle_version: str, title: str,
                   ipa_url: str, icon_url: str) -> str:
    """The itms-services manifest, byte-compatible with the live one."""
    for url in (ipa_url, icon_url):
        if not url.startswith("https://"):
            raise ValidationError(
                f"OTA braucht HTTPS, bekommen: {url!r}. iOS installiert nichts ueber http."
            )
    return PLIST_TEMPLATE.format(
        ipa_url=_plist_escape(ipa_url), icon_url=_plist_escape(icon_url),
        bundle_id=_plist_escape(bundle_id),
        bundle_version=_plist_escape(bundle_version),
        title=_plist_escape(title),
    )


def install_url(base_url: str, plist_name: str) -> str:
    base = base_url.rstrip("/")
    return f"itms-services://?action=download-manifest&url={base}/{plist_name}"


def check_publishable(project, manifest, ipa_info: dict) -> list:
    """Reasons this artifact must not be published.  Empty list means go."""
    problems = []
    if manifest.get("dry_run"):
        problems.append(
            "Dry-Run-Build: es existiert keine IPA. Ein Mock wird nie als "
            "installierbarer Build veroeffentlicht."
        )
    if manifest.get("mode") != MODE_AD_HOC:
        problems.append(f"Modus {manifest.get('mode')} ist nicht fuer OTA vorgesehen")
    if ipa_info.get("bundle_id") != project.bundle_id:
        problems.append(
            f"IPA meldet Bundle ID {ipa_info.get('bundle_id')}, erwartet "
            f"{project.bundle_id}"
        )
    if not ipa_info.get("has_code_signature"):
        problems.append("IPA hat keine Codesignatur")
    profile = ipa_info.get("profile") or {}
    kind = distribution_kind(ipa_info)
    if kind != "AD_HOC":
        problems.append(
            f"Die IPA ist als {kind} signiert, nicht Ad Hoc - sie wuerde sich "
            "auf Sebastians iPhone nicht installieren lassen"
        )
    if profile.get("expired"):
        problems.append(f"Provisioning Profile ist am {profile.get('expires')} abgelaufen")
    if not profile.get("provisioned_device_count"):
        problems.append("Profil listet keine registrierten Geraete")
    expected = (project.signing.get(MODE_AD_HOC) or {}).get("profile_name")
    if expected and profile.get("name") and profile["name"] != expected:
        problems.append(
            f"Profil {profile['name']!r} statt des konfigurierten {expected!r}"
        )
    return problems


class OtaRelease:
    def __init__(self, data: dict) -> None:
        self.data = data

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def to_dict(self) -> dict:
        return dict(self.data)


def prepare(project, manifest, ipa_path, *, base_url: str, out_dir,
            ipa_info: dict | None = None) -> OtaRelease:
    """Produce everything the install page needs, next to the build.

    Raises :class:`ValidationError` listing *every* reason at once, so a
    broken release is diagnosed in one pass instead of five.
    """
    ipa_path = Path(ipa_path)
    info = ipa_info or inspect(ipa_path)
    problems = check_publishable(project, manifest, info)
    if problems:
        raise ValidationError(
            "OTA abgelehnt:\n  - " + "\n  - ".join(problems)
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ota = project.ota
    slug = ota.get("slug") or project.id
    plist_name = ota.get("plist") or f"{slug}.plist"
    ipa_name = ota.get("ipa") or f"{slug}.ipa"
    icon_name = ota.get("icon") or f"{slug}-icon.png"
    base = base_url.rstrip("/")

    plist = manifest_plist(
        bundle_id=project.bundle_id,
        # The page and the IPA must agree; iOS shows this string while
        # installing and uses it to decide whether it is an upgrade.
        bundle_version=str(info.get("version") or project.marketing_version),
        title=ota.get("title") or project.name,
        ipa_url=f"{base}/{ipa_name}",
        icon_url=f"{base}/{icon_name}",
    )
    (out / plist_name).write_text(plist, encoding="utf-8", newline="\n")

    link = install_url(base, plist_name)
    page_url = f"{base}/"
    matrix = qr.encode(page_url, "M")
    (out / "qr.svg").write_text(qr.to_svg(matrix), encoding="utf-8", newline="\n")
    (out / "qr.png").write_bytes(qr.to_png(matrix))

    release = OtaRelease({
        "build_id": manifest.get("build_id"),
        "project": project.id,
        "app": ota.get("title") or project.name,
        "slug": slug,
        "bundle_id": project.bundle_id,
        "version": info.get("version"),
        "build_number": info.get("build_number"),
        "commit": manifest.get("commit"),
        "commit_short": (manifest.get("commit") or "")[:8],
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "ipa_name": ipa_name,
        "ipa_sha256": info.get("sha256"),
        "ipa_bytes": info.get("bytes"),
        "ipa_mb": round((info.get("bytes") or 0) / 1024 / 1024, 1),
        "plist_name": plist_name,
        "icon_name": icon_name,
        "install_url": link,
        "page_url": page_url,
        "qr_svg": "qr.svg",
        "profile_name": (info.get("profile") or {}).get("name"),
        "profile_expires": (info.get("profile") or {}).get("expires"),
        "device_count": (info.get("profile") or {}).get("provisioned_device_count"),
        "minimum_os": info.get("minimum_os"),
    })
    from .store import write_json

    write_json(out / "release.json", release.to_dict())
    shutil.copy2(ipa_path, out / ipa_name)
    return release


# --------------------------------------------------------------------------
# install page
# --------------------------------------------------------------------------

ACCENTS = {"thy-gnosis": "#b23a3a", "days-of-ruin": "#a3ff12"}


def _accent(slug: str) -> tuple:
    colour = ACCENTS.get(slug, "#ff7a1a")
    # Light accents need dark text on the button, dark accents need white.
    dark_text = colour.lower() in ("#a3ff12",)
    return colour, ("#000" if dark_text else "#fff")


def render_install_page(releases: list, *, title: str = "Band-Apps installieren",
                        subtitle: str = "Direkt aufs iPhone, ohne TestFlight. "
                                        "Diese Seite in Safari oeffnen.") -> str:
    """The OTA page from section 10: app, version, build, commit, date, QR."""
    cards = []
    for rel in releases:
        data = rel.to_dict() if isinstance(rel, OtaRelease) else dict(rel)
        colour, text_colour = _accent(data.get("slug", ""))
        e = lambda k, d="": html.escape(str(data.get(k, d) or d))  # noqa: E731
        created = str(data.get("created_at") or "")[:10]
        cards.append(f"""
  <section class="app">
    <header>
      <img src="{e('icon_name')}" alt="{e('app')}" width="66" height="66">
      <div>
        <h2>{e('app')}</h2>
        <p class="meta">Version {e('version')} &middot; Build {e('build_number')}</p>
      </div>
    </header>
    <a class="go" style="background:{colour};color:{text_colour}"
       href="{html.escape(data.get('install_url', ''))}">{e('app')} installieren</a>
    <dl>
      <div><dt>Commit</dt><dd><code>{e('commit_short')}</code></dd></div>
      <div><dt>Erstellt</dt><dd>{html.escape(created)}</dd></div>
      <div><dt>Groesse</dt><dd>{e('ipa_mb')} MB</dd></div>
      <div><dt>iOS</dt><dd>ab {e('minimum_os')}</dd></div>
      <div class="wide"><dt>SHA-256</dt><dd><code>{e('ipa_sha256')}</code></dd></div>
    </dl>
  </section>""")

    qr_block = ""
    if releases:
        first = releases[0].to_dict() if isinstance(releases[0], OtaRelease) else dict(releases[0])
        matrix = qr.encode(first.get("page_url") or "https://example.invalid", "M")
        qr_block = f"""
  <section class="qr">
    <h2>Diese Seite auf einem anderen iPhone oeffnen</h2>
    {qr.to_svg(matrix, module=6, dark='#f2efe9', light='#141417')}
    <p class="meta">Mit der Kamera scannen.</p>
  </section>"""

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#0a0a0c;--card:#141417;--line:#2a2a31;--text:#f2efe9;--muted:#9b9ba3}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 padding:calc(28px + env(safe-area-inset-top)) 18px calc(40px + env(safe-area-inset-bottom))}}
main{{max-width:520px;margin:0 auto}}
h1{{font-size:26px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}}
.sub{{color:var(--muted);margin:0 0 28px}}
.app{{background:var(--card);border:1px solid var(--line);padding:16px;margin-bottom:22px}}
.app header{{display:flex;gap:16px;align-items:center}}
.app img{{flex:none;border-radius:14px;border:1px solid var(--line)}}
.app h2{{font-size:19px;line-height:1.2;margin:0}}
.meta{{color:var(--muted);font-size:14px;margin:2px 0 0}}
.go{{display:block;text-align:center;text-decoration:none;font-weight:600;
 letter-spacing:.04em;padding:13px;margin:16px 0 0}}
.go:active{{opacity:.8}}
dl{{margin:16px 0 0;font-size:13.5px;display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}}
dl>div.wide{{grid-column:1 / -1}}
dt{{color:var(--muted);margin:0}}
dd{{margin:2px 0 0}}
code{{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 word-break:break-all;color:var(--text)}}
.qr{{background:var(--card);border:1px solid var(--line);padding:16px;text-align:center}}
.qr h2{{font-size:15px;margin:0 0 12px;font-weight:600}}
.qr svg{{max-width:220px;height:auto}}
ol{{color:var(--muted);font-size:14.5px;padding-left:20px;margin:26px 0 0}}
li{{margin-bottom:8px}}
.note{{margin-top:26px;padding-top:18px;border-top:1px solid var(--line);
 color:var(--muted);font-size:13.5px}}
@media (max-width:360px){{dl{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="sub">{html.escape(subtitle)}</p>
{"".join(cards)}
{qr_block}
  <ol>
    <li>Auf &laquo;Installieren&raquo; tippen, dann im Hinweis von iOS nochmals auf &laquo;Installieren&raquo;.</li>
    <li>Die App landet auf dem Home-Bildschirm und startet direkt. Kein Profil, kein Vertrauen-Dialog noetig.</li>
    <li>Falls nichts passiert: Seite in Safari oeffnen, nicht in einer anderen App.</li>
  </ol>
  <p class="note">Ad hoc signiert fuer die registrierten iPhones. Auf anderen
  Geraeten bricht die Installation ab. Neue Version? Einfach nochmals
  installieren, sie ueberschreibt die alte. Die SHA-256-Summe oben gehoert zur
  IPA, die diese Seite anbietet.</p>
</main>
</body>
</html>
"""
