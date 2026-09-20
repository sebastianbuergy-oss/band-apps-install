# macOS-Executor

## Das Interface

Alles, was einen Mac braucht, laeuft ueber `bb/executors/__init__.py`:

```python
class MacExecutor:
    name: str                  # steht im Manifest und im Audit-Log
    cost_resource: str         # was der Cost Guard pruefen soll
    produces_real_ipa: bool    # False heisst: das Ergebnis ist kein iOS-Build

    def availability(self) -> str:        # AVAILABLE | BUSY | OFFLINE
    def submit(self, job: MacJob) -> str
    def poll(self, handle: str) -> MacJobResult
    def cancel(self, handle: str) -> bool
    def fetch_artifact(self, handle, dest_dir) -> str | None
```

`MacJob` enthaelt Repository, Commit, Modus, Scheme, Bundle ID, Buildnummer,
Version und den **Namen** des Provisioning-Profils. Es enthaelt **keine
Secrets**: der Executor loest seine Zugangsdaten an seinem eigenen Ende auf.

## Die vier Implementierungen

### `none` - der Standard heute

Meldet immer `OFFLINE` und verweigert jeden Job mit einer Begruendung, die sagt,
was fehlt und welche Optionen es gibt. Das ist kein Platzhalter, sondern die
ehrliche Antwort: Sebastian hat keinen Mac und keinen freigegebenen Executor.

### `dryrun` - die Pipeline ohne Mac

Laeuft den kompletten Zustandsablauf durch, ohne Xcode. Jedes Ergebnis ist mit
`simulated` markiert, jedes Manifest mit `dry_run`, und jede Anzeige schreibt
`SUCCESS (DRY RUN - kein echter iOS-Build)`. Zaehlt nicht gegen das Build-Limit,
erzeugt keine IPA, wird nie fuer OTA freigegeben.

### `github` - der Vorschlag fuer den Pilot

Startet den Workflow `burgys-ios-build.yml` im App-Repo per
`workflow_dispatch`, verfolgt den Run und holt die IPA. Kostenlos fuer
oeffentliche Repos (`COST_MODEL.md`).

Konfiguration in `config/projects.json`:

```json
"executor": "github",
"executor_config": {
  "repo": "sebastianbuergy-oss/thy-gnosis-ios",
  "workflow": "burgys-ios-build.yml",
  "visibility": "public",
  "token_file": "C:\\Users\\<user>\\.burgys\\github_token"
}
```

`visibility` ist Pflicht. Fehlt sie, nimmt der Cost Guard `private` an und
blockiert - lieber ein Build zu wenig als eine Rechnung zu viel.

Das Token gehoert in eine Datei ausserhalb des Repositories und braucht nur
`actions: write` und `contents: read` auf genau diesem Repo.

**Einrichtung (Sebastians Entscheidung, nicht automatisch):**

1. `burgys-builds/templates/burgys-ios-build.yml` nach
   `.github/workflows/burgys-ios-build.yml` im App-Repo kopieren.
2. Repository-Secrets setzen: `BURGYS_CERT_P12_BASE64`,
   `BURGYS_CERT_PASSWORD`, `BURGYS_PROFILE_BASE64`.
3. Repository-Variablen: `BURGYS_TEAM_ID`, `BURGYS_BUNDLE_ID`.
4. Ersten Lauf von Hand in der Actions-Oberflaeche starten und zusehen.
5. Erst danach `executor: "github"` eintragen.

Zu Punkt 2: ein Distribution-Zertifikat in ein oeffentliches Repo als *Secret*
zu legen ist ueblich und von GitHub dafuer vorgesehen - Secrets sind in
Workflow-Runs aus Forks nicht sichtbar und werden in Logs maskiert. Es bleibt
trotzdem eine Entscheidung, die Sebastian treffen muss, nicht Buergys Builds.

### `local` - der spaetere Burgys-iOS-Runner

Fuer den eigenen Mac mini. SSH mit Schluessel, ein Shell-Script auf dem Mac,
Statusdateien als Rueckkanal. Jeder Wert geht als eigenes `argv`-Element, nichts
wird in einen Shell-String interpoliert.

Wenn der Mac mini kommt, aendert sich **nur diese Datei plus die Konfiguration**.
Queue, Cost Guard, Manifeste, Preflight, OTA und Dashboard bleiben, wie sie sind.
Das war der Zweck der Abstraktion.

## Zeitgrenze

`mac_job_timeout_minutes` (Standard 30) bricht einen haengenden Job ab, damit
keine Minuten weiterlaufen. Der abgebrochene Build wird `BLOCKED`, nicht
wiederholt.

## Einen eigenen Executor schreiben

`MacExecutor` ableiten, `@register` daraufsetzen, in
`bb/executors/__init__.py::_load_backends` importieren. `cost_resource` muss in
`bb/costguard.py::RESOURCES` stehen - sonst gilt er als kostenpflichtig und wird
blockiert.
