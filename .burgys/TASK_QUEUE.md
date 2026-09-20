# Aufgaben

Status: `TODO`, `CLAIMED_CLAUDE`, `CLAIMED_CODEX`, `REVIEW`, `DONE`, `BLOCKED`.
Ein Agent aendert nur, was er selbst geclaimt hat.

| ID | Aufgabe | Status | Wer |
|---|---|---|---|
| BB-001 | Bestandsaufnahme Repos, IPAs, Signing, Codemagic -> `docs/INVENTORY.md` | DONE | Claude |
| BB-002 | Buergys Builds v0.1: Cost Guard, Limit, Zustaende, Queue, Preflight, Executor-Schicht, OTA, QR, API, Dashboard, CLI | DONE | Claude |
| BB-003 | Testsuite nach Auftrag Abschnitt 26 | DONE | Claude | 
| BB-004 | Rechner-Bestandsaufnahme auf dem HP (`burgys doctor`), `local_path` eintragen | TODO | Sebastian |
| BB-005 | GitHub-Actions-Workflow in `thy-gnosis-ios` einrichten, Secrets setzen, ersten Lauf von Hand beobachten | BLOCKED | wartet auf Freigabe |
| BB-006 | Erster echter Ad-Hoc-Build ueber Buergys Builds, IPA auf iPhone installieren | BLOCKED | wartet auf BB-005 |
| BB-007 | `build_number_floor` fuer beide Apps aus App Store Connect ermitteln | TODO | Sebastian |
| BB-008 | Retention/Aufraeumen implementieren (BB-I-002) | TODO | frei |
| BB-009 | `ota_publish_dir` + `burgys publish`, damit das Kopieren auf die Live-Seite ein Befehl wird | TODO | frei |
| BB-010 | Days of Ruin nachziehen, sobald der Pilot durch ist | TODO | frei |
| BB-011 | Artefakt-Download im GitHub-Executor (`fetch_artifact`) ueber die Actions-API | TODO | frei |
| BB-012 | Code-Review von v0.1 durch Codex | DONE | Codex |
| BB-013 | Windows-Abnahme auf dem HP (`tests/windows_check.py`) | TODO | Sebastian |
| BB-014 | Geschuetzte Umgebung `ios-signing` im App-Repo anlegen (Required Reviewers) | BLOCKED | wartet auf Freigabe |
| BB-015 | Export-Methode beim ersten Lauf pruefen (`ad-hoc` vs `release-testing`) | TODO | offen bis erster Lauf |

## Hinweise zu einzelnen Aufgaben

**BB-011** ist die letzte Luecke im GitHub-Executor: `submit` und `poll` sind da,
`fetch_artifact` gibt noch `None` zurueck. Solange das so ist, endet ein
GitHub-Build mit "Executor meldet Erfolg, liefert aber keine IPA" - was korrekt
ist, aber nicht das Ziel. Vor BB-006 zu erledigen.

**BB-012** ist erledigt - Ergebnis in `HANDOFF.md`. 14 Befunde, alle behoben,
Suite von 137 auf 186 Tests. Die Mutationspruefung (35 Sicherungen einzeln
kaputtmachen) steht als Werkzeug bereit und sollte vor jedem groesseren Merge
wiederholt werden.

**BB-013** ist der wichtigste offene Punkt: bis das Skript auf dem HP gelaufen
ist, ist die Windows-Tauglichkeit eine Behauptung, keine Messung.

**BB-015**: Xcode 15.3 hat `ad-hoc`/`app-store` zugunsten von
`release-testing`/`app-store-connect` als veraltet markiert. Das Template ist
ueber `BURGYS_EXPORT_METHOD_ADHOC`/`_STORE` umschaltbar. Beim ersten echten Lauf
darauf achten.
