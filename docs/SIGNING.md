# Signing

## Grundsatz

Signing wird nie improvisiert. Buergys Builds haelt **keine privaten Schluessel**
- weder `.p12`, noch Passwoerter, noch App-Store-Connect-Keys. Es kennt nur die
*Namen* des Profils und des Zertifikats und prueft damit Widersprueche. Die
Schluessel selbst liegen dort, wo der Executor laeuft.

Bei einem Widerspruch: **STOP**. Kein Fallback, kein "nimm halt das andere
Profil", kein automatisches Loeschen oder Neuanlegen von Zertifikaten.

## Die drei Modi

| Modus | Profil | Geraete | Ergebnis |
|---|---|---|---|
| `DEVELOPMENT` | Development | registriert | Debug auf dem eigenen Geraet |
| `AD_HOC` | Ad Hoc | **muss Geraete listen** | IPA fuer OTA |
| `APP_STORE_RELEASE` | App Store | keine | IPA fuer App Store Connect |

## Was vor dem Build geprueft wird (Windows, kostenlos)

`bb/preflight.py::_check_signing`:

- Ist fuer diesen Modus ueberhaupt Signing konfiguriert? Wenn nein: FAIL.
- `profile_name` und `certificate_common_name` vorhanden?
- Nennt das Zertifikat die konfigurierte Team-ID?
- Profil abgelaufen? Zertifikat abgelaufen? **Warnung ab 30 Tagen Restlaufzeit.**
- Ad Hoc ohne `expects_provisioned_devices`? Dann ist es das falsche Profil.
- App Store ohne `app_store_apple_id`? Der Upload wuerde scheitern.

## Was nach dem Build geprueft wird (ebenfalls Windows)

`bb/verify.py` liest die fertige IPA - `plistlib` fuer Info.plist, der
XML-Anteil von `embedded.mobileprovision` fuer das Profil - und vergleicht mit
dem, was bestellt war:

- Bundle ID
- Buildnummer und Version - genau die, die Buergys Builds vergeben hat
- Codesignatur vorhanden
- `web/index.html` im Bundle (bei WebView-Apps waere die App sonst leer)
- Verteilungsart: Ad Hoc muss Geraete listen, App Store darf keine haben
- Profilname genau der konfigurierte
- Team-ID
- Profil nicht abgelaufen

Erst wenn das durch ist, gilt der Build als `SUCCESS`. Ein Executor, der Erfolg
meldet und nichts liefert, wird `FAILED` - dafuer gibt es einen eigenen Test.

## Der heutige Stand (aus den IPAs gelesen)

| | Thy Gnosis | Days of Ruin |
|---|---|---|
| Team | `38A4N26LD5` (Sebastian Buergy) | dito |
| Ad-Hoc-Profil | `ThyGnosis ios_app_adhoc 20260913` | `DaysOfRuin ios_app_adhoc 20260913` |
| Ablauf | 2027-08-14 | 2027-08-14 |
| Zertifikat | `Apple Distribution: Sebastian Brgy (38A4N26LD5)` | dasselbe |
| Geraete | 2 | 2 |

Beide Apps teilen sich ein Distribution-Zertifikat (in Codemagic als
`gosafehome-distribution` abgelegt). Das ist normal und in Ordnung - es heisst
nur, dass sein Ablauf am 14.08.2027 **beide** Apps gleichzeitig betrifft.

## Buildnummern - die Stelle, die wehtun kann

`CFBundleVersion` muss fuer App Store Connect **streng monoton** steigen. Wer
eine kleinere Nummer hochlaedt, bekommt eine Ablehnung.

Codemagic hat bisher seine eigene `$BUILD_NUMBER` eingesetzt. Welche Nummern
dabei schon bei Apple angekommen sind, ist im Repository nicht sichtbar - in
`project.yml` steht `CURRENT_PROJECT_VERSION: '1'`, und die ausgelieferten IPAs
tragen `CFBundleVersion 1`.

Deshalb:

> **`APP_STORE_RELEASE` wird verweigert, solange `build_number_floor` fehlt.**

```json
"build_number_floor": 42
```

Die Zahl ist die hoechste Buildnummer, die fuer diese App je an App Store
Connect ging. Sie steht in App Store Connect unter der App > TestFlight >
iOS-Builds. Buergys Builds vergibt danach `max(zuletzt_vergeben, floor) + 1` und
zaehlt monoton weiter - auch ueber Neustarts, auch bei parallelen Prozessen
(beides getestet).

Fuer `AD_HOC` ist das unkritisch: dort zaehlt nur, dass iOS die neue Version als
neuer erkennt.

## Secrets

Niemals:

- im Repository
- in einem Log
- in einer Statusdatei oder einem Manifest
- in einem Claude-/Codex-Handoff

`bb/redact.py` schwaerzt auf dem Weg nach draussen: nach Schluesselname
(`*token*`, `*secret*`, `*password*`, `*private_key*`, `*p12*`, `asc_key*`, ...)
und nach Muster (PEM-Bloecke, `ghp_`/`gho_`-Token, lange Base64-Bloecke,
`KEY=value`-Zuweisungen). Das laeuft im Audit-Log, im Build-Manifest, in jeder
API-Antwort und in den Build-Logs. Getestet.

Wo die Schluessel liegen:

- **GitHub-Executor**: als Repository-Secrets im App-Repo. Der Workflow legt
  einen temporaeren Keychain an und loescht ihn im `always()`-Schritt.
- **Local-Executor**: im Login-Keychain des Mac mini.
- **Zugang zu GitHub**: ein Token in einer Datei ausserhalb des Repos,
  `token_file` in `executor_config`.
- **Agent-Tokens**: `~/.burgys/agent_token`, beim ersten Start erzeugt, unter
  POSIX auf `0600` gesetzt. `burgys init` warnt, wenn die Rechte zu weit sind.

## Wenn ein Zertifikat ablaeuft

Der Preflight warnt 30 Tage vorher und scheitert danach. Dann - von Hand, in
dieser Reihenfolge:

1. Neues Zertifikat und neue Profile im Apple Developer Portal anlegen.
2. **Das alte Zertifikat nicht widerrufen**, solange eine Version im Store oder
   auf einem Geraet davon abhaengt.
3. Neue Secrets im Executor hinterlegen.
4. `profile_name`, `expires`, `certificate_expires` in `config/projects.json`
   nachziehen.
5. Preflight laufen lassen, dann einen Ad-Hoc-Build, dann auf einem echten
   iPhone installieren.

Buergys Builds macht davon nichts selbst. Aenderungen an Zertifikaten und
Provisioning sind in Abschnitt 29 des Auftrags ausdruecklich Sebastians Sache.
