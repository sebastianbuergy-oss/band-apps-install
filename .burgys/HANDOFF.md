# Handoff

Der jeweils letzte Eintrag steht oben.

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
