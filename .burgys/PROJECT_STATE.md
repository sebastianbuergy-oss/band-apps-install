# Projektzustand

Nur bestaetigter Zustand. Was hier steht, ist nachgeprueft.

**Stand:** 2026-09-20
**Letzter Agent:** Claude (Lead)
**Branch:** `claude/burgys-builds-ios-platform-k53703`
**Start-Commit:** `fa99ef8`

## Was steht

- Buergys Builds v0.1 unter `burgys-builds/` - **IMPLEMENTED und TESTED**
  (137 automatische Tests, gruen, reine Standardbibliothek)
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
| **Echter iOS-Build** | **NICHT ERREICHT** | kein Mac, kein freigegebener Executor |

## Offene Blocker

1. **Kein macOS-Executor freigegeben.** Der GitHub-Weg ist vorbereitet und
   kostenlos (beide App-Repos sind oeffentlich), aber das Einrichten und der
   erste echte Lauf brauchen Sebastians Entscheidung - Auftrag Abschnitt 29.
2. **`local_path` fehlt fuer beide Projekte.** Muss auf dem HP eingetragen
   werden; von hier aus nicht bekannt.
3. **`build_number_floor` unbekannt.** Blockiert `APP_STORE_RELEASE`, bis die
   hoechste bereits verwendete Buildnummer aus App Store Connect bekannt ist.
4. **Rechner-Bestandsaufnahme fehlt.** `burgys doctor` auf dem HP laufen lassen.

## Naechster Schritt

Sebastian:

1. `docs/INVENTORY.md` lesen - besonders den Befund, dass die ausgelieferte
   iPhone-App einen Stand aelter ist als die Browser-Version
2. Auf dem HP: `python -m bb.cli init`, `doctor`, `local_path` eintragen,
   `preflight thy-gnosis`
3. Entscheiden, ob der GitHub-Actions-Weg eingerichtet wird (`MAC_EXECUTOR.md`)

Danach: BB-004 (Workflow einrichten) und BB-005 (erster echter Ad-Hoc-Build).
