# Installation auf dem HP

## Voraussetzungen

- **Python 3.9 oder neuer.** Mehr nicht. Buergys Builds nutzt ausschliesslich die
  Standardbibliothek - kein `pip install`, kein Compiler, kein Netz noetig.
- **Git** im `PATH` (fuer Preflight und Commit-Aufloesung).
- **Node** nur, wenn das jeweilige Projekt ein eigenes Preflight-Script hat.
  Fehlt es, meldet Buergys Builds eine Warnung und macht weiter - es faellt
  nicht aus.

```
python --version
git --version
node --version
```

## Einrichten

```bat
cd C:\Users\<user>\Projekte
git clone https://github.com/sebastianbuergy-oss/band-apps-install
cd band-apps-install\burgys-builds

python -m bb.cli init
```

`init` legt `data/` an, erzeugt die Agent-Tokens in `%USERPROFILE%\.burgys\agent_token`
und zeigt, was konfiguriert ist. Die Tokens selbst werden bewusst nicht in die
Konsole geschrieben.

`bin\burgys.cmd` ist ein Wrapper - wer `burgys ...` statt
`python -m bb.cli ...` tippen will, legt `burgys-builds\bin` in den `PATH`.

## Bestandsaufnahme des Rechners

```bat
python -m bb.cli doctor --out ..\docs\INVENTORY_HP.md
```

Schreibt System, Werkzeuge, Apple-Werkzeuge und die *Namen* vorhandener
SSH-Schluessel. Schluesselinhalte niemals.

## Projekte eintragen

In `config/projects.json` braucht jedes Projekt ein `local_path` - den Klon auf
dem HP. Das ist zugleich die Allowlist: was nicht drinsteht, wird nicht gebaut.

```json
"local_path": "C:\\Users\\<user>\\Projekte\\thy-gnosis-ios"
```

Doppelte Backslashes, weil JSON. `%USERPROFILE%` und `~` werden aufgeloest.

Dann:

```bat
python -m bb.cli projects
python -m bb.cli preflight thy-gnosis
```

Der Preflight muss gruen sein, bevor irgendetwas anderes Sinn ergibt.

## Die Pipeline ohne Mac ausprobieren

```bat
python -m bb.cli --executor dryrun build thy-gnosis --dry-run --run
```

Laeuft alle Zustaende durch, erzeugt Manifest und Log, zaehlt nicht gegen das
Build-Limit und sagt bei jeder Gelegenheit, dass keine IPA entstanden ist.

## Dashboard

```bat
python -m bb.cli dashboard
```

Startet den Server auf `127.0.0.1:8787` und oeffnet den Browser mit Token. Nur
lokal erreichbar.

## Eine vorhandene IPA untersuchen

Geht ohne Mac:

```bat
python -m bb.cli ipa ..\thy-gnosis.ipa
```

Bundle ID, Version, Buildnummer, SHA-256, Profilname, Ablaufdatum, Anzahl
registrierter Geraete, Verteilungsart.

## Tests

```bat
cd burgys-builds
python -m unittest discover -s tests -t tests
```

137 Tests, rund 16 Sekunden, keine externen Abhaengigkeiten, kein Netz.

## Autostart (optional)

Eine Verknuepfung nach
`shell:startup` legen, die `pythonw -m bb.cli serve` im Ordner
`burgys-builds` startet. Recovery laeuft beim Start automatisch mit.

## Konfiguration

`config/burgys.json`. Ein unbekannter Schluessel ist ein Startfehler - besser ein
lautes Nein als ein stillschweigend ignorierter Cost Guard.

| Schluessel | Standard | |
|---|---|---|
| `paid_services_allowed` | `false` | **Der Kostenschalter** |
| `max_real_builds_per_project_per_day` | `20` | |
| `require_approval_for_mac_builds` | `true` | |
| `default_executor` | `"none"` | `none`, `dryrun`, `github`, `local` |
| `mac_job_timeout_minutes` | `30` | |
| `data_root` | `burgys-builds/data` | |
| `api_host` / `api_port` | `127.0.0.1` / `8787` | Ein anderer Host wird abgelehnt |
| `api_token_file` | `~/.burgys/agent_token` | Nie im Repository |
| `ota_base_url` | GitHub-Pages-URL | |
| `min_free_bytes` | 2 GiB | |

Umgebungsvariablen ueberschreiben: `PAID_SERVICES_ALLOWED`, `BURGYS_DATA`,
`BURGYS_API_PORT`, `BURGYS_MAX_BUILDS_PER_DAY`, `BURGYS_REQUIRE_APPROVAL`,
`BURGYS_OTA_BASE_URL`, `BURGYS_API_TOKEN_FILE`.

## Was nicht ins Repository gehoert

`burgys-builds/data/` ist in `.gitignore`. Die Tokendatei liegt ausserhalb des
Repos. Zertifikate und `.p12`-Dateien gehoeren weder ins eine noch ins andere.
