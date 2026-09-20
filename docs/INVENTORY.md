# Bestandsaufnahme

Stand: 2026-09-20. Erhoben von Claude (Lead) in einer Cloud-Sitzung.

## Wie diese Aufnahme entstanden ist - und was fehlt

Wichtig vorweg, damit niemand diese Liste fuer vollstaendiger haelt als sie ist:

Diese Sitzung lief **nicht auf Sebastians HP**, sondern in einem Linux-Container
in der Cloud. Alles, was den Rechner selbst betrifft - Windows-Version, CPU, RAM,
Speicher, installierte Flutter-/Dart-/Node-/gh-Versionen, PowerShell, vorhandene
SSH-Konfiguration, lokale Klone, lokale Zertifikate - **konnte von hier aus nicht
gemessen werden**. Diese Punkte stehen unten unter *unbekannt*, nicht unter
*vorhanden*.

Dafuer gibt es jetzt ein Werkzeug, das genau diese Luecke schliesst. Auf dem HP:

```
python -m bb.cli doctor --out ..\docs\INVENTORY_HP.md
```

Das schreibt System, Werkzeuge, Apple-Werkzeuge und SSH-Schluessel*namen* in eine
Datei. Schluesselinhalte werden nie ausgegeben.

Gemessen wurde dagegen alles, was im Git liegt: die Repositories, die
Codemagic-Konfigurationen, die ausgelieferten IPAs und deren
Provisioning-Profile. Das ist die Substanz der Liste unten.

---

## vorhanden und verwendbar

### Repositories

| Repo | Sichtbarkeit | Inhalt |
|---|---|---|
| `band-apps-install` | **public** | OTA-Installationsseite (GitHub Pages), die beiden IPAs, die `.plist`-Manifeste, Browser-Versionen beider Apps, `sync_web.py` |
| `thy-gnosis-ios` | **public** | Die App. UIKit + `WKWebView`, Web-App gebuendelt in `web/`, XcodeGen |
| `days-of-ruin-ios` | **public** | Dieselbe Struktur, andere Band |

Dass beide App-Repos **oeffentlich** sind, ist der wichtigste Einzelbefund dieser
Aufnahme - siehe `COST_MODEL.md`.

### Struktur der beiden App-Repos (identisch)

```
App/          AppDelegate.swift, WebViewController.swift, PrivacyInfo.xcprivacy,
              Assets.xcassets/AppIcon.appiconset/Icon-1024.png
web/          index.html (eine Datei, ~56-64 KB), img/, fonts/  -> Ressourcen-Ordner
feed/feed.json  Konzerte und News, wird zur Laufzeit von raw.githubusercontent nachgeladen
project.yml   XcodeGen-Definition (kein .xcodeproj im Repo, wird generiert)
codemagic.yaml  zwei Workflows: ios-testflight, ios-adhoc
scripts/preflight.cjs   eigener Preflight des Projekts, laeuft unter Node
package.json  "check": "node scripts/preflight.cjs"
```

Kein Flutter, kein CocoaPods, kein SPM, kein Fastfile, kein Podfile, keine
`ExportOptions.plist` im Repo, keine GitHub Actions Workflows. Die Apps sind
native Swift-Huellen um eine gebuendelte Web-App - technisch sehr genuegsam.

### Signing (aus den ausgelieferten IPAs gelesen, nicht geraten)

| | Thy Gnosis | Days of Ruin |
|---|---|---|
| Bundle ID | `com.sebastianbuergy.thygnosis` | `com.sebastianbuergy.daysofruin` |
| Version / Build | 1.0 / 1 | 1.0 / 1 |
| Team | Sebastian Buergy, `38A4N26LD5` | dito |
| Ad-Hoc-Profil | `ThyGnosis ios_app_adhoc 20260913` | `DaysOfRuin ios_app_adhoc 20260913` |
| Profil laeuft ab | **2027-08-14** | **2027-08-14** |
| Zertifikat | `Apple Distribution: Sebastian Brgy (38A4N26LD5)`, gueltig bis 2027-08-14 | dito (dasselbe Zertifikat) |
| Registrierte Geraete | 2 | 2 |
| `get-task-allow` | false (Distribution, korrekt) | false |
| Minimum iOS | 16.0 | 16.0 |
| Gebaut mit | Xcode 26.6 / iphoneos26.5 SDK | dito |
| IPA-Groesse | 5'137'349 Bytes | 4'378'036 Bytes |

Die Geraete-UDIDs wurden bewusst **nicht** notiert - nur ihre Anzahl. Sie
identifizieren Sebastians und Lynns iPhones.

Beide Apps teilen sich dasselbe Distribution-Zertifikat, das in Codemagic unter
dem Namen `gosafehome-distribution` liegt. Es laeuft in beiden Profilen am
**14. August 2027** ab; ein zweites, aelteres Zertifikat mit Ablauf 26. Juli 2027
steckt ebenfalls in den Profilen.

### App Store Connect

| App | Apple ID | App-Store-Profil |
|---|---|---|
| Thy Gnosis | `6811436478` | `ThyGnosis ios_app_store 20260912` |
| Days of Ruin | `6811437685` | `DaysOfRuin ios_app_store 20260912` |

Beide App-Datensaetze wurden am 12.09.2026 angelegt. Ob und was bereits
eingereicht wurde, war von hier aus nicht feststellbar.

### OTA

Laeuft und ist die Grundlage, auf der Buergys Builds aufsetzt:

- `index.html` mit zwei `itms-services://`-Buttons
- `thy-gnosis.plist`, `days-of-ruin.plist` - Manifeste im Standardformat
- Beide IPAs direkt im Repo, ueber GitHub Pages per HTTPS erreichbar
- Icons `*-icon.png`
- Browser-Versionen unter `/thy-gnosis/` und `/days-of-ruin/`, per `sync_web.py`
  aus dem `web/`-Ordner der App-Repos erzeugt, mit `noindex`

### Codemagic

`instance_type: mac_mini_m2`, `max_build_duration: 30`, Xcode `latest`, Node 24.
Pro App zwei Workflows:

- **`ios-testflight`** - App-Store-Signierung, `xcode-project build-ipa`,
  Verifikation per PlistBuddy/codesign, Upload nach TestFlight (`submit_to_app_store: false`)
- **`ios-adhoc`** - Ad-Hoc-Profil, gleiche Schritte, prueft zusaetzlich dass das
  Profil `ProvisionedDevices` enthaelt, benennt die IPA auf `<slug>.ipa` um

Die Verifikationsschritte in diesen Workflows sind gut und wurden in Buergys
Builds uebernommen (`bb/verify.py`) - dort laufen sie zusaetzlich auf Windows.

---

## ersetzen

| Heute | Ersetzt durch | Warum |
|---|---|---|
| Codemagic `ios-adhoc` | Buergys Builds + macOS-Executor | Das ist das Ziel des Auftrags |
| IPA von Hand aus den Artefakten kopieren | `bb.ota` erzeugt Manifest, Pruefsumme und Seite | Der README-Satz "die .ipa hier ersetzen, bundle-version hochzaehlen, committen" ist genau der Handgriff, der schiefgeht |
| `bundle-version` manuell hochzaehlen | `bb.manifest.BuildNumbers` | s. *Drift* unten |
| Kein Log, keine Buildhistorie | Audit-Log, Manifest, Dashboard | Bisher gibt es keine Spur, welcher Commit in welcher IPA steckt |
| Kein SHA-256 auf der Installationsseite | `bb.ota` | Man kann heute nicht pruefen, ob die IPA die ist, die man meint |

---

## Drift, die jetzt schon da ist

Aufgefallen beim Vergleich von Repo-Stand und ausgelieferter IPA:

1. **Die ausgelieferte iPhone-App ist eine Version hinter der Browser-Version.**
   Nachgerechnet, nicht vermutet:

   | | Groesse | SHA-256 (Anfang) |
   |---|---|---|
   | `web/index.html` **in der ausgelieferten `thy-gnosis.ipa`** | 55'844 B | `763e2efc41799f4a` |
   | `web/index.html` im Repo auf `main` (Commit `242f5e4`) | 57'952 B | `86d261ed51c89d6a` |
   | veroeffentlichte Browser-Version `/thy-gnosis/index.html` | 58'199 B | `75ec2268d7a5ba4e` |

   Die IPA wurde am **12.09.2026 21:58** gebaut, der QA-Fixes-Commit ist vom
   **13.09.2026 16:24**. Die Browser-Version wurde am selben Tag um 16:24
   aktualisiert (`fa99ef8`), die IPA nicht.

   Das heisst konkret: **wer die App auf dem iPhone installiert, testet einen
   anderen Stand als wer sie im Browser oeffnet** - ohne Countdown in Schweizer
   Zeit, ohne die groesseren Tipp-Flaechen, ohne den Offline-Hinweis im Player.

   Und: weder die `.plist`, noch die Installationsseite, noch die IPA selbst
   sagen, aus welchem Commit sie stammt. Genau diese Luecke schliesst das
   Build-Manifest (`commit`, `artifact_sha256`) und die neue Installationsseite,
   die Commit und Pruefsumme anzeigt.
2. **Buildnummer steht auf 1.** `CURRENT_PROJECT_VERSION: '1'` in `project.yml`,
   `CFBundleVersion 1` in beiden IPAs. Codemagic patcht die Nummer zur Laufzeit
   mit seiner eigenen `$BUILD_NUMBER`. Welche Nummern bereits an App Store
   Connect gegangen sind, ist von aussen nicht sichtbar. Buergys Builds
   verweigert deshalb einen `APP_STORE_RELEASE`-Build, solange kein
   `build_number_floor` konfiguriert ist - siehe `SIGNING.md`.
3. **Der Days-of-Ruin-Button ist noch pink.** Commit `218d93c`
   ("Days of Ruin: Giftgruen statt Pink") hat die CSS-Variable `--dor` auf
   `#a3ff12` gesetzt, der Installations-Button in `index.html` traegt aber
   weiterhin ein Inline-`style="background:#e8317e"`. Die Regel `.dor .go` greift
   nicht, weil der Link kein Kind des `.dor`-Blocks ist. Nicht angefasst: die
   Seite ist live und der Auftrag sagt "bestehende Projekte nicht beschaedigen".
   Steht in `.burgys/KNOWN_ISSUES.md`.

---

## unbekannt (nur auf dem HP zu klaeren)

- Windows-Version, CPU, RAM, freier Speicher
- Flutter- und Dart-Version (in beiden App-Repos irrelevant - dort steckt kein Flutter)
- Node-/npm-Version auf dem HP (Codemagic nutzt Node 24)
- GitHub CLI (`gh`) installiert?
- PowerShell-Version
- Python-Version auf dem HP (`sync_web.py` braucht Pillow, also ist eines da)
- Vorhandene lokale Klone und ihre Pfade -> werden fuer `local_path` in
  `config/projects.json` gebraucht
- SSH-Konfiguration und vorhandene Schluessel
- Lokal installierte Zertifikate / `.p12`-Dateien
- Welche Codemagic-Builds bereits an App Store Connect gingen (Buildnummern)
- Stand von **Buergys Agent** - im gesamten erreichbaren Git ist davon nichts zu
  finden. Buergys Builds bringt die API mit, an die er sich spaeter haengt
  (`AGENT_API.md`), koppelt aber nichts an etwas, das es noch nicht gibt.

## blockiert

| Was | Warum | Was es loesen wuerde |
|---|---|---|
| Echter iOS-Build | Kein Mac, kein freigegebener macOS-Executor | Sebastians Freigabe fuer den GitHub-Actions-Weg (kostenlos, s. `COST_MODEL.md`) |
| IPA-Signierung | Buergys Builds haelt keine privaten Schluessel | Zertifikat + Profil als GitHub-Secrets im jeweiligen App-Repo |
| App-Store-Upload | Buildnummern-Historie unbekannt + Freigabe noetig | `build_number_floor` setzen, dann bewusst ausloesen |
| Zugriff auf die uebrigen ~23 Repos | Diese Sitzung war auf `band-apps-install` beschraenkt; die beiden App-Repos wurden gezielt dazugeholt | Weitere Repos einzeln freigeben, wenn sie migriert werden sollen |

---

## Werkzeuge in dieser Sitzung (nicht der HP)

Nur zur Einordnung, welche Umgebung die Tests gesehen haben:
Ubuntu 24.04, Python 3.11.15, Node 22.22.2, npm 10.9.7, git 2.43.
Kein Flutter, kein Dart, kein `gh`, kein Xcode, kein `qrencode`.

Dass Buergys Builds unter Python 3.11 **ohne eine einzige externe Abhaengigkeit**
laeuft, ist Absicht: auf dem HP soll ein blankes Python reichen.
