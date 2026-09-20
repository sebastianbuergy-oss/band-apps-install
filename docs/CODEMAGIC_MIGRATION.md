# Codemagic-Migration

## Regel

**Codemagic wird nicht geloescht.** Kein funktionierender Workflow wird
abgeschaltet, bevor Buergys Builds fuer genau diese App nachweislich
funktioniert. Buergys Builds loest bei Codemagic nichts aus und aendert dort
nichts - der Cost Guard blockiert `codemagic` ohnehin.

## Die vier Zustaende

```
CODEMAGIC_ACTIVE  ->  BURGYS_BUILDS_PARALLEL  ->  BURGYS_BUILDS_VERIFIED  ->  CODEMAGIC_DISABLED
```

Der Zustand steht pro Projekt in `config/projects.json` als `migration_state` und
im Dashboard.

### `CODEMAGIC_ACTIVE`

Wo beide Apps heute stehen. Codemagic baut, Buergys Builds macht Preflight, Dry
Runs, Inventar und OTA-Vorbereitung. Kein Risiko.

### `BURGYS_BUILDS_PARALLEL`

Beide bauen denselben Commit. Verglichen wird:

- Bundle ID, Version, Buildnummer
- Verteilungsart und Profilname
- Ist `web/index.html` im Bundle?
- Installiert die IPA auf einem registrierten iPhone und startet die App?

Die SHA-256-Summen werden **nicht** gleich sein - Xcode-Builds sind nicht
bit-reproduzierbar. Verglichen wird der Inhalt, nicht der Hash.

### `BURGYS_BUILDS_VERIFIED`

Erreicht, wenn die Pilot-Abnahme aus Abschnitt 24 vollstaendig durch ist - alle
17 Punkte, inklusive "IPA installiert auf registriertem iPhone" und "App
startet". Codemagic laeuft weiter, wird aber nicht mehr gebraucht.

### `CODEMAGIC_DISABLED`

Erst jetzt, und auch jetzt in dieser Reihenfolge:

1. Workflow in Codemagic **deaktivieren**, nicht loeschen.
2. Mindestens einen weiteren echten Release-Zyklus ueber Buergys Builds fahren.
3. `codemagic.yaml` im Repo **behalten** - sie ist die beste Dokumentation
   dessen, was ein Build braucht, und der schnellste Rueckweg.
4. Erst danach ueber das Abo reden.

## Reihenfolge der Apps

1. **`thy-gnosis`** - der Pilot. Begruendung in `.burgys/DECISIONS.md` (BB-D-004).
2. `days-of-ruin` - identische Struktur, uebernimmt die gelernten Lektionen.
3. Alles andere erst danach, App fuer App.

Der App-Store-Weg wird **nach** dem Ad-Hoc-Weg migriert. Ad Hoc ist reversibel -
eine kaputte IPA installiert man einfach nicht. Ein fehlerhafter
App-Store-Upload ist es nicht.

## Rueckweg

Jederzeit, an jedem Punkt: in Codemagic den Workflow `ios-adhoc` starten, IPA aus
den Artefakten laden, wie bisher veroeffentlichen. Dieser Weg bleibt bis
`CODEMAGIC_DISABLED` vollstaendig intakt. Dafuer wird die `codemagic.yaml` nicht
angefasst.
