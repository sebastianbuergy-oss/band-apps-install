# Bekannte Probleme

---

## BB-I-001 - Der Days-of-Ruin-Button ist noch pink

**Offen. Nicht angefasst, weil live.**

Commit `218d93c` ("Days of Ruin: Giftgruen statt Pink") hat in `index.html` die
CSS-Variable `--dor` auf `#a3ff12` gesetzt. Der Installations-Button traegt aber
weiterhin `style="background:#e8317e"` inline, und die Regel `.dor .go` greift
nicht, weil der Link kein Kind des `.dor`-Blocks ist, sondern dessen Geschwister.

Der Button ist also weiterhin pink - die Absicht des Commits ist nicht
angekommen.

*Einzeiler:* in `index.html` beim Days-of-Ruin-Link `background:#e8317e` durch
`background:#a3ff12;color:#000` ersetzen.

*Warum nicht gemacht:* Die Seite ist live und nicht Teil des Auftrags. Die neue
OTA-Seite in `bb/ota.py` verwendet bereits das Giftgruen.

---

## BB-I-009 - Jede SHA-256 wurde beim Speichern geschwaerzt

**BEHOBEN (Codex, 2026-09-21). War ein echter Datenverlust.**

Das Schwaerzungsmuster fuer "base64-aehnliche Blobs" (`[A-Za-z0-9+/]{60,}`)
passte auf **jede SHA-256-Hexsumme** - die ist 64 Zeichen lang. Folge:

- `artifact_sha256` im gespeicherten Manifest wurde zu `[REDACTED]`, obwohl
  Abschnitt 14 des Auftrags genau dieses Feld verlangt
- dasselbe fuer `ota.ipa_sha256`
- die Installationsseite haette `[REDACTED]` als Pruefsumme angezeigt
- nach einem Neustart war die Summe unwiederbringlich weg

Warum es kein Test bemerkt hat: das Manifest-Objekt im Speicher behaelt den
echten Wert, geschwaerzt wird erst beim `save()` und in `to_dict()`. Alle
bestehenden Tests prueften gegen das lebende Objekt. Aufgefallen ist es erst,
als `burgys publish` das Manifest **von der Platte** las.

*Behoben:* Hexsummen kanonischer Laenge (64/96/128) werden nicht mehr
geschwaerzt. Echtes Schluesselmaterial - gemischte Schreibweise, `+/=`, andere
Laengen - weiterhin schon. Tests gibt es jetzt an der Persistenz-Grenze, nicht
nur im Speicher.

---

## BB-I-010 - Ein Test hatte ein Datum fest verdrahtet

**BEHOBEN (Codex, 2026-09-21).**

`test_github_executor.py` verglich gegen `BB-20260920-TST-001`. Am 21. erzeugte
der Controller `BB-20260921-...`, der Stub antwortete mit dem alten Namen,
`poll` fand den Run nie und drehte mit `poll_interval=0` eine Endlosschleife,
bis der Stub-Server blockierte. Die Suite lief von 33s auf ueber 600s.

Zwei Lehren, beide umgesetzt:

1. Die Build-ID wird jetzt aus dem heutigen Datum abgeleitet, und der Stub
   antwortet ueber die ID, die tatsaechlich dispatcht wurde.
2. **Echte Haertung:** `_await` klemmt das Poll-Intervall auf mindestens
   0,25 s. Eine Endlosschleife gegen `api.github.com` waere ein sicherer Weg,
   rate-limitiert oder gesperrt zu werden.

---

## BB-I-007 - Windows nie ausgefuehrt (loest BB-I-006 ab)

**Offen. Wichtigster Blocker. Aufgabe BB-013.**

Weder Claudes Implementierungs-Sitzung noch Codex' Review-Sitzung lief unter
Windows - beide waren Linux-Container ohne `cmd.exe`, PowerShell oder Wine.

Statisch geprueft und sauber: keine `fcntl`/`pwd`/`grp`/Signal-Nutzung,
`os.replace` statt `rename`, `mkdir`-Locks statt POSIX-Locks, `pathlib`
durchgaengig, Pfadkomponenten lehnen `/` und `\` gleichermassen ab, jedes
`open()` mit explizitem `encoding`, Schreibvorgaenge mit `newline="\n"`.

Gemessen ist davon **nichts**. `burgys-builds/tests/windows_check.py` misst es:

```
cd burgys-builds
python tests\windows_check.py
```

Solange die Ausgabe fehlt, ist "laeuft auf dem HP" eine Behauptung.

---

## BB-I-008 - Export-Methode koennte mit neuem Xcode brechen

**Offen. Risiko fuer den ersten echten Build. Aufgabe BB-015.**

Xcode 15.3 hat die Export-Methoden `ad-hoc` und `app-store` zugunsten von
`release-testing` und `app-store-connect` als veraltet markiert. Beide
Schreibweisen werden derzeit akzeptiert, aber der Runner nutzt Xcode 26.

Codemagic umgeht das, weil dort `xcode-project build-ipa` die Methode selbst
waehlt. Der eigene Workflow ruft `xcodebuild -exportArchive` direkt auf und
muss sie benennen.

*Abgefedert:* Das Template liest `BURGYS_EXPORT_METHOD_ADHOC` bzw.
`BURGYS_EXPORT_METHOD_STORE` und nutzt sonst die alten Namen. Umschalten geht
ohne Workflow-Aenderung.

*Beim ersten Lauf darauf achten:* Scheitert `-exportArchive` mit einer Meldung
ueber eine unbekannte Methode, ist das die Ursache.

---

## BB-I-002 - Aufbewahrung raeumte nicht auf

**BEHOBEN (Codex, 2026-09-20, BB-008).**

`bb/retention.py` wertet die Konfiguration jetzt aus. `burgys retention` zeigt
an, `--apply` raeumt auf. Laufende Builds, veroeffentlichte OTA-Releases und die
neuesten N Artefakte je Projekt werden nie angefasst. Das Dashboard zeigt, wie
viel freizumachen waere. 13 Tests, alle Schutzregeln mutationsgeprueft.

---

## BB-I-003 - `fetch_artifact` fehlte im GitHub-Executor

**BEHOBEN (Codex, 2026-09-20, BB-011). Blockierte BB-006.**

Implementiert samt der beiden Fallen dieser API: das Token wandert nicht mit
der 302-Umleitung zum Blob-Host, und das Zip aus dem Netz wird nicht
vertraut (Pfadpruefung, Groessen- und Eintragsdeckel, SHA-256-Abgleich gegen
die Sidecar-Datei).

24 Tests gegen einen lokalen Stub der Actions-API, darunter ein
Ende-zu-Ende-Lauf durch den Controller: Dispatch, Poll, Download,
IPA-Verifikation, OTA-Release mit QR. Damit ist der Weg vollstaendig - es
fehlt nur noch ein echter Mac am anderen Ende.

---

## BB-I-004 - Die ausgelieferte iPhone-App ist einen Stand hinter der Browser-Version

**Offen. Kein Fehler in Buergys Builds - der Befund, wegen dessen es existiert.**

Gemessen am 2026-09-20:

| | Groesse | SHA-256 (Anfang) |
|---|---|---|
| `web/index.html` in `thy-gnosis.ipa` | 55'844 B | `763e2efc41799f4a` |
| `web/index.html` auf `main` (`242f5e4`) | 57'952 B | `86d261ed51c89d6a` |
| veroeffentlichte Browser-Version | 58'199 B | `75ec2268d7a5ba4e` |

Die IPA ist vom 12.09.2026 21:58, der QA-Fixes-Commit vom 13.09.2026 16:24. Die
Browser-Version wurde nachgezogen, die IPA nicht.

*Wirkung:* Wer die App auf dem iPhone installiert, testet ohne die QA-Fixes -
ohne Countdown in Schweizer Zeit, ohne groessere Tipp-Flaechen, ohne
Offline-Hinweis im Player. Wer sie im Browser oeffnet, testet mit.

*Behebung:* Ein neuer Ad-Hoc-Build von `242f5e4`. Braucht einen macOS-Executor -
oder einmal Codemagic `ios-adhoc`, wie bisher.

*Kuenftig verhindert durch:* Das Build-Manifest haelt den Commit fest, und die
neue Installationsseite zeigt Commit und SHA-256 an.

---

## BB-I-005 - Beide Apps haengen an einem Zertifikat mit demselben Ablaufdatum

**Beobachtung, kein Fehler.**

`Apple Distribution: Sebastian Brgy (38A4N26LD5)` wird von Thy Gnosis und Days of
Ruin geteilt und laeuft am **14.08.2027** ab. Beide Ad-Hoc-Profile laufen am
selben Tag ab.

*Wirkung:* Wenn es soweit ist, sind beide Apps gleichzeitig betroffen.

*Abgefedert durch:* Der Preflight warnt ab 30 Tagen Restlaufzeit und scheitert
nach Ablauf. Ablauf ist erst in rund 11 Monaten.

---

## BB-I-006 - Auf dem HP noch nicht gelaufen

**Abgeloest durch BB-I-007**, das dasselbe Problem praeziser fasst und ein
Messwerkzeug mitbringt.
