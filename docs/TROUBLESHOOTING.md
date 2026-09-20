# Troubleshooting

## "Kein macOS-Executor konfiguriert"

Kein Fehler, sondern die aktuelle Wahrheit: Buergys Builds hat alles erledigt,
was auf Windows geht, und es gibt keinen freigegebenen Mac.

- Pipeline ueben: `--executor dryrun ... --dry-run`
- Echte IPA: Codemagic wie bisher, oder den GitHub-Weg einrichten
  (`MAC_EXECUTOR.md`) - kostenlos, braucht aber Sebastians Freigabe.

## `BLOCKED_BY_COST_GUARD`

Eine kostenpflichtige Ressource wurde angefordert. Die Meldung nennt welche.

- Unbekannte Ressource? Der Cost Guard behandelt Unbekanntes als kostenpflichtig.
  Eintragen in `bb/costguard.py::RESOURCES`.
- GitHub-Executor blockiert obwohl das Repo oeffentlich ist? `visibility:
  "public"` in `executor_config` fehlt. Ohne Angabe wird `private` angenommen.
- Freikontingent erschoepft? Dann ist Schluss. Ein kostenpflichtiger Fallback ist
  ausgeschlossen - das ist der Sinn der Sache.

## "Limit erreicht - kein weiterer macOS-Job"

20 echte Builds in 24 Stunden. Dry Runs und Preflight bleiben erlaubt.
`burgys status` zeigt den Zaehler. Anheben ueber
`max_real_builds_per_project_per_day` - aber erst fragen, warum so viel gebaut
wird.

## Preflight: "nicht committete Aenderungen"

Ein Build muss einem Commit entsprechen, sonst weiss niemand, was in der IPA
steckt. Committen oder stashen.

## Preflight: "project.yml sagt X, Buergys Builds erwartet Y"

Ein Widerspruch bei der Bundle ID. **Kein Build.** Entweder `project.yml` oder
`config/projects.json` ist falsch - das muss ein Mensch entscheiden.

## Preflight: "N fehlende Datei(en)"

Die Seite referenziert Bilder oder Schriften, die nicht im Repo sind. Das Detail
listet sie. Auf einem iPhone waere das ein leerer Kasten.

## Preflight: "npm run check" fehlt

Node ist nicht installiert - nur eine Warnung, nicht fatal. Buergys Builds
prueft dieselben Dinge selbst; das Projekt-Script ist das zusaetzliche Netz.

## "build_number_floor fehlt"

Nur im App-Store-Modus. Codemagic hat schon Buildnummern an Apple geschickt, und
eine kleinere waere eine Ablehnung. Die hoechste bisher verwendete Nummer aus App
Store Connect eintragen - `SIGNING.md`.

## "Executor meldet Erfolg, liefert aber keine IPA"

Absichtlich hart: ein Build ohne Artefakt ist kein Erfolg. Im Workflow-Log
nachsehen, ob der Export-Schritt tatsaechlich eine `.ipa` erzeugt hat.

## "IPA-Pruefung: ..."

`bb/verify.py` hat einen Unterschied zwischen Bestelltem und Geliefertem
gefunden:

- *Buildnummer X statt Y* - der Schritt, der `CURRENT_PROJECT_VERSION` patcht,
  hat nicht gegriffen
- *Signierung ist APP_STORE, erwartet AD_HOC* - falsches Profil
- *Profil P statt Q* - `profile_name` und der Executor sind sich uneinig
- *web/index.html fehlt* - der `web/`-Ordner ist nicht als Ressource eingebunden

## OTA abgelehnt

Alle Gruende auf einmal. Haeufig:

- *Dry-Run-Build* - es gibt keine IPA
- *Die IPA ist als APP_STORE signiert* - die wuerde sich nicht installieren
- *Profil listet keine registrierten Geraete* - kein Ad-Hoc-Profil
- *OTA braucht HTTPS* - iOS installiert nicht ueber `http`

## Installation bricht auf dem iPhone ab

- Das Geraet ist nicht im Profil (`burgys ipa <datei>` zeigt die Anzahl)
- Die Seite wurde nicht in Safari geoeffnet
- Das Manifest ist nicht ueber HTTPS erreichbar
- Die IPA-URL im Manifest zeigt ins Leere (GitHub Pages braucht nach dem Push
  einen Moment)

## API: 401

- Kein oder falsches Token
- Falsches Token fuer die Aktion: ein echter Build braucht das `release`-Token
- Token-Datei neu erzeugt? Dann sind die alten Tokens ungueltig

## API: 429

Rate Limit. `Retry-After` beachten, oder `api_rate_limit_per_minute` anheben.

## "timed out waiting for lock"

Ein anderer Prozess arbeitet gerade. Nach 5 Minuten ohne Lebenszeichen wird das
Lock automatisch gebrochen. Haengt es laenger: `burgys recover`, notfalls die
`.lock`-Verzeichnisse unter `data/` loeschen, wenn sicher kein Controller laeuft.

## Nach einem Absturz steht ein Build auf FAILED / INTERRUPTED_BY_RESTART

So gewollt. Der Job war auf einem Mac, als der Controller starb - automatisch neu
zu starten koennte Minuten doppelt verbrauchen. Nachsehen, ob der Run beim
Executor durchgelaufen ist, dann neu anfordern.

## Kein Platz mehr

`burgys status` zeigt `disk`. Unter 2 GiB wird blockiert. `data/artifacts/` und
`data/logs/` sind die grossen Posten und duerfen aufgeraeumt werden.

## Ganz von vorn

`data/` loeschen. Historie und Artefakte sind weg, das System ist unbeschaedigt.
Die Tokens bleiben, sie liegen woanders.
