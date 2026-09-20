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

**Offen. Aufgabe BB-004.**

Die gesamte Entwicklung und alle 137 Tests liefen unter Linux/Python 3.11. Die
plattformkritischen Stellen sind bewusst portabel gebaut (`os.replace`,
`mkdir`-Locks, `pathlib`, keine POSIX-Aufrufe ausser einem `chmod`, das unter
Windows still uebersprungen wird), aber **geprueft ist das unter Windows nicht**.

*Zuerst zu pruefen:* `burgys init`, `burgys doctor`, `burgys preflight`,
Verhalten der Sperren auf NTFS, Pfade mit Leerzeichen und Umlauten.
