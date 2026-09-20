# Claude und Codex

Claude ist Lead und Koordinator, Codex ist Implementation und Review. Beide
arbeiten auf demselben Git-Stand. Nichts wird durch Annahmen geregelt - der
Zustand steht in `.burgys/`.

## Die Dateien

| Datei | Inhalt |
|---|---|
| `.burgys/state.json` | Maschinenlesbarer Zustand. **Vor jeder Arbeit lesen.** |
| `.burgys/PROJECT_STATE.md` | Nur der bestaetigte Zustand: Commit, aktive Aufgabe, getesteter Stand, Blocker, naechster Schritt |
| `.burgys/TASK_QUEUE.md` | Aufgaben mit ID und Status |
| `.burgys/HANDOFF.md` | Was bei der letzten Uebergabe passiert ist |
| `.burgys/DECISIONS.md` | Architekturentscheidungen. Werden nicht stillschweigend geaendert |
| `.burgys/KNOWN_ISSUES.md` | Bekannte Fehler und Blocker |

## Ablauf

**Vor der Arbeit:**

1. `git fetch`
2. Aktuellen Branch und Commit pruefen. Ist Remote neuer: **erst synchronisieren.**
   Keine Arbeit auf einem Stand, von dem man weiss, dass er veraltet ist.
3. `.burgys/state.json` und `TASK_QUEUE.md` lesen
4. Eine Aufgabe mit `TODO` claimen: Status auf `CLAIMED_CLAUDE` oder
   `CLAIMED_CODEX`, committen, pushen. **Erst dann anfangen.**

**Waehrend der Arbeit:**

- Nur an der geclaimten Aufgabe arbeiten.
- Claude und Codex bearbeiten nie gleichzeitig dieselben Dateien. Wer merkt, dass
  er in fremde Dateien muss: Aufgabe auf `BLOCKED`, Grund in
  `KNOWN_ISSUES.md`, abgeben.
- Bei paralleler Arbeit eigene Branches: `claude/<task-id>`, `codex/<task-id>`.
  Merge erst nach Tests und Review.

**Nach der Arbeit:**

1. Tests laufen lassen: `python -m unittest discover -s tests -t tests`
2. `HANDOFF.md` schreiben: Agent, Datum, Task-ID, Start-Commit, End-Commit,
   geaenderte Dateien, ausgefuehrte Tests, Testergebnis, offene Probleme,
   empfohlener naechster Schritt
3. `PROJECT_STATE.md` und `state.json` aktualisieren - atomar, in einem Commit
4. Aufgabe auf `REVIEW` oder `DONE`
5. Pushen

## Task-IDs

`BB-001`, `BB-002`, ... Status: `TODO`, `CLAIMED_CLAUDE`, `CLAIMED_CODEX`,
`REVIEW`, `DONE`, `BLOCKED`.

**Ein Agent aendert nur eine Aufgabe, die er selbst geclaimt hat.**

## Verboten

- Force Push auf `main`
- History Rewrites
- Fremde Aenderungen verwerfen
- Eine Aufgabe anfassen, die ein anderer geclaimt hat
- `DECISIONS.md` stillschweigend aendern - eine Entscheidung wird ersetzt, indem
  eine neue mit Begruendung dazukommt und die alte als abgeloest markiert wird

## `state.json`

```json
{
  "schema_version": 1,
  "project": "burgys-builds",
  "current_commit": "",
  "active_tasks": [],
  "last_agent": "",
  "last_handoff": "",
  "system_status": {
    "windows_controller": "",
    "mac_executor": "",
    "cost_guard": true
  }
}
```

`cost_guard: true` heisst: der Guard ist aktiv, kostenpflichtige Dienste sind
gesperrt.

## Sprachregelung - das Wichtigste

Diese vier Begriffe werden streng verwendet. Jeder andere Gebrauch ist ein
Fehlerbericht wert:

| Begriff | Bedeutung |
|---|---|
| **IMPLEMENTED** | Code vorhanden |
| **TESTED** | Automatischer oder lokaler Test bestanden |
| **DEVICE VERIFIED** | Auf einem echten iPhone geprueft |
| **PRODUCTION VERIFIED** | Der vollstaendige echte Produktionsweg ist erfolgreich gelaufen |

Ein Mock-Build ist **nie** ein erfolgreicher iOS-Build. Der Dry-Run-Executor
markiert jedes Ergebnis als `simulated`, jedes Manifest als `dry_run`, und jede
Anzeige schreibt `SUCCESS (DRY RUN - kein echter iOS-Build)`. Wer diese
Markierung entfernt, entfernt die Ehrlichkeit des Systems.

## Secrets

Kommen in keinem Handoff vor, in keiner `.burgys`-Datei, in keinem Commit.
`bb/redact.py` schwaerzt maschinell - aber ein Agent, der ein Token in eine
Markdown-Datei schreibt, umgeht das. Also: nicht tun.
