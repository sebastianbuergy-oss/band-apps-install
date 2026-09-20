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
| BB-012 | Code-Review von v0.1 durch Codex | TODO | Codex |

## Hinweise zu einzelnen Aufgaben

**BB-011** ist die letzte Luecke im GitHub-Executor: `submit` und `poll` sind da,
`fetch_artifact` gibt noch `None` zurueck. Solange das so ist, endet ein
GitHub-Build mit "Executor meldet Erfolg, liefert aber keine IPA" - was korrekt
ist, aber nicht das Ziel. Vor BB-006 zu erledigen.

**BB-012**: besonders anzusehen waeren `bb/store.py` (Sperren), `bb/builds.py`
(Reihenfolge der Pruefungen) und `bb/qr.py` (die Blocktabelle, auch wenn sie sich
gegen die Geometrie selbst prueft).
