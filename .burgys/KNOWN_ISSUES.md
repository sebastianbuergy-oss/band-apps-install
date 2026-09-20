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

## BB-I-002 - Aufbewahrung ist konfigurierbar, aber raeumt noch nicht auf

**Offen. Aufgabe BB-008.**

`retention_days_builds`, `retention_days_logs` und
`retention_keep_artifacts_per_project` stehen in der Konfiguration und werden
bisher von nichts ausgewertet. `data/` waechst also.

*Abgefedert durch:* Der Speicherwaechter blockiert unter 2 GiB frei, das
Dashboard warnt unter 10 GiB, Build-Logs werden bei 8 MB abgeschnitten.

*Risiko heute:* gering - ein Build erzeugt ein Manifest, ein Log und eine IPA von
rund 5 MB.

---

## BB-I-003 - `fetch_artifact` fehlt im GitHub-Executor

**Offen. Aufgabe BB-011. Blockiert BB-006.**

`GitHubMacExecutor` kann einen Workflow starten und seinen Zustand verfolgen,
aber die IPA noch nicht herunterladen - `fetch_artifact` gibt `None` zurueck.

*Wie es sich aeussert:* Der Build endet mit "Executor meldet Erfolg, liefert aber
keine IPA" und wird `FAILED`. Das ist korrekt (kein Artefakt ist kein Erfolg),
aber nicht das Ziel.

*Was fehlt:* `GET /repos/{repo}/actions/runs/{id}/artifacts`, dann das Zip laden
und entpacken. Die Actions-API liefert Artefakte immer als Zip.

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
