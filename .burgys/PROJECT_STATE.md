# Projektzustand

Nur bestaetigter Zustand. Was hier steht, ist nachgeprueft.

**Stand:** 2026-09-20
**Letzter Agent:** Codex (Review)
**Branch:** `codex/bb-review-phase1` (auf `claude/burgys-builds-ios-platform-k53703`)
**Start-Commit:** `514ba0f`

## Was steht

- Buergys Builds v0.1 unter `burgys-builds/` - **IMPLEMENTED und TESTED**
  (223 automatische Tests, gruen, 0 uebersprungen, reine Standardbibliothek)
- Phase-1-Review durch Codex abgeschlossen: 14 Befunde, alle behoben,
  35/35 Mutanten von der Suite gefunden (vorher 22/26)
- Bestandsaufnahme: `docs/INVENTORY.md`
- Zwoelf Dokumente unter `docs/`
- Koordinationsdateien unter `.burgys/`

## Getesteter Stand

| Bereich | Stufe | Belegt durch |
|---|---|---|
| Cost Guard | TESTED | blockiert alle PAID-Ressourcen, faellt bei Unbekanntem geschlossen aus, Freikontingent ohne kostenpflichtigen Fallback, Ledger ueberlebt Neustart |
| Build-Limit | TESTED | 20/24 h, Dry Runs und Preflight zaehlen nicht, aeltere Builds fallen aus dem Fenster |
| Zustandsautomat | TESTED | alle 16 Zustaende, illegale Abkuerzungen abgelehnt, terminale Zustaende sind Sackgassen |
| Queue | TESTED | Prioritaet, ein Job pro Projekt, 6 Threads x 8 Jobs ohne Doppelvergabe |
| Restart-Recovery | TESTED | macOS-Job wird als unterbrochen markiert, **nicht** neu gestartet; lokale Jobs kommen zurueck in die Queue |
| Sperren | TESTED | 8 echte Prozesse, keine doppelte Buildnummer |
| Preflight | TESTED **und gegen die echten Repos gelaufen** | 13 Pruefungen, gruen auf `thy-gnosis-ios` inkl. dessen eigenem `npm run check` |
| Signing-Vorbedingungen | TESTED | abgelaufenes Profil, abgelaufenes Zertifikat, fremdes Team, Ad Hoc ohne Geraete, App Store ohne Apple ID |
| IPA-Inspektion | TESTED **an den echten IPAs** | Bundle ID, Version, Profil, Ablauf, Geraeteanzahl, SHA-256 |
| OTA-Manifest | TESTED | erzeugtes `.plist` ist **byte-identisch** mit dem live ausgelieferten |
| QR-Encoder | TESTED | alle 40 Version/Level-Kombinationen, unabhaengiger Decoder, RS-Syndrome null |
| Agent API | TESTED | Auth, Scopes, Rate Limit, Path Traversal, Body-Grenze, Schwaerzung, Security-Header |
| Log-Schwaerzung | TESTED | Schluesselnamen, PEM, `ghp_`-Token, lange Base64-Bloecke |
| Disk-full | TESTED | blockiert vor der Vergabe, `ENOSPC` raeumt auf |
| Runner-Allowlist | TESTED | nur `STANDARD_MACOS_RUNNERS` erlaubt; fehlendes Label und Larger Runner blockieren |
| Workflow-Haertung | TESTED (statisch) | null `${{ }}` in `run:`-Blocks, Eingabevalidierung, geschuetzte Umgebung |
| Mutationstests | TESTED | 35 Sicherungen kaputtgemacht, 35-mal Rot |
| Artefakt-Download | TESTED | 24 Tests gegen einen Stub der Actions-API, inkl. Ende-zu-Ende-Lauf durch den Controller; Token leakt nicht an den Umleitungs-Host, Zip-Slip und Zip-Bombe abgewehrt |
| Retention | TESTED | raeumt auf, laesst laufende Builds und veroeffentlichte OTA-Releases in Ruhe |
| **Windows** | **UNGEPRUEFT** | Review lief unter Linux; `tests/windows_check.py` wartet auf den HP |
| **Echter iOS-Build** | **NICHT ERREICHT** | kein Mac, kein freigegebener Executor |

## Offene Blocker

1. **Windows-Abnahme steht aus.** `python tests\windows_check.py` auf dem HP.
   Weder Claude noch Codex konnten unter Windows ausfuehren - beide Sitzungen
   liefen in Linux-Containern. Bis zur Ausgabe dieses Skripts gilt Buergys
   Builds unter Windows als ungeprueft.
2. **Kein macOS-Executor freigegeben.** Der GitHub-Weg ist vorbereitet und
   kostenlos (beide App-Repos sind oeffentlich), aber das Einrichten und der
   erste echte Lauf brauchen Sebastians Entscheidung - Auftrag Abschnitt 29.
3. **`local_path` fehlt fuer beide Projekte.** Muss auf dem HP eingetragen
   werden; von hier aus nicht bekannt.
4. **`build_number_floor` unbekannt.** Im Review gezielt gesucht: keine
   Git-Tags, `project.yml` auf `1`, beide IPAs `CFBundleVersion 1`, Codemagic
   setzt die Nummer erst zur Laufzeit. Lokal gibt es **keine** Spur der an App
   Store Connect uebermittelten Nummern. Bleibt Blocker.
5. **Rechner-Bestandsaufnahme fehlt.** `burgys doctor` auf dem HP laufen lassen.
6. ~~BB-I-003 `fetch_artifact`~~ - **erledigt.** Es gibt keinen Codeblocker mehr.

## Naechster Schritt

Sebastian:

1. `docs/INVENTORY.md` lesen - besonders den Befund, dass die ausgelieferte
   iPhone-App einen Stand aelter ist als die Browser-Version
2. Auf dem HP: `python -m bb.cli init`, `doctor`, `local_path` eintragen,
   `preflight thy-gnosis`, dann **`python tests\windows_check.py`** und die
   Ausgabe zurueckgeben
3. `build_number_floor` fuer beide Apps aus App Store Connect ablesen
4. Entscheiden, ob der GitHub-Actions-Weg eingerichtet wird (`MAC_EXECUTOR.md`) -
   inklusive geschuetzter Umgebung `ios-signing` mit Required Reviewers

Danach nur noch BB-005 (Workflow und geschuetzte Umgebung einrichten) und
BB-006 (erster echter Ad-Hoc-Build). Code ist fertig.
