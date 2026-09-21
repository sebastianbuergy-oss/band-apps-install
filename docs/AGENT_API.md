# Agent API

Lokale HTTP-API fuer Buergys Agent, die CLI und das Dashboard. Gebunden an
`127.0.0.1`. Ein anderer Host wird abgelehnt - fuer Fernzugriff ein SSH-Tunnel,
nicht ein offener Port.

```
burgys serve                 # API + Dashboard
burgys dashboard             # dasselbe, oeffnet den Browser mit Token
```

## Authentifizierung

Zwei Tokens, beim ersten Start erzeugt, in `~/.burgys/agent_token` (unter POSIX
`0600`; `burgys init` warnt, wenn die Rechte zu weit sind).

| Token | Scopes | Darf |
|---|---|---|
| `agent` | `read`, `preflight`, `prepare` | Status lesen, Preflight starten, Build vorbereiten, Dry Run, Logs lesen, abbrechen |
| `release` | zusaetzlich `build`, `release` | echten macOS-Build starten, freigeben, App-Store-Upload ausloesen |

Das ist Abschnitt 19 des Auftrags: der Agent darf im Alltag alles Kostenlose,
und alles, was Geld kostet oder nach aussen wirkt, braucht das zweite Token.

```
Authorization: Bearer <token>
```

## Routen

| Methode | Pfad | Scope | |
|---|---|---|---|
| GET | `/health` | - | Lebenszeichen |
| GET | `/capabilities` | read | **Zuerst fragen:** was kann das System, was darf dieses Token |
| GET | `/status` | read | System, Cost Guard, Queue, Speicher, Builds heute |
| GET | `/projects` | read | Projektliste |
| GET | `/projects/{id}` | read | Projekt, Limit, letzte Builds |
| POST | `/preflight` | preflight | `{"project", "mode", "commit"}` |
| POST | `/builds` | prepare | `{"project", "mode", "commit", "dry_run"}` |
| GET | `/builds/{build-id}` | read | Manifest |
| POST | `/builds/{build-id}/cancel` | prepare | abbrechen |
| POST | `/builds/{build-id}/approve` | **release** | freigeben |
| GET | `/builds/{build-id}/logs?tail=n` | read | Log |
| GET | `/builds/{build-id}/artifacts` | read | Dateinamen, SHA-256, OTA-Daten |
| GET | `/queue` | read | Queue |
| GET | `/audit?limit=n&project=id` | read | Audit-Log |
| GET | `/published` | read | was aktuell auf der Installationsseite liegt |
| POST | `/builds/{build-id}/publish` | **release** | OTA-Release veroeffentlichen (`dry_run` ist Standard) |

`POST /builds` mit `dry_run: false` verlangt Scope `build`. Mit dem
Agent-Token kommt eine 400 mit dem Hinweis, dass `dry_run: true` kostenlos
durchlaeuft.

## Beispiel

```bash
TOKEN=$(python -c "import json,pathlib;print([t for t in json.loads(pathlib.Path.home().joinpath('.burgys/agent_token').read_text())['tokens'] if t['name']=='agent'][0]['token'])")

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/status
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"project":"thy-gnosis","mode":"AD_HOC"}' \
     http://127.0.0.1:8787/preflight
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"project":"thy-gnosis","mode":"AD_HOC","dry_run":true}' \
     http://127.0.0.1:8787/builds
```

## Sicherheit

- **Nur lokal.** Socket auf `127.0.0.1`, zusaetzlich prueft der Handler die
  Peer-Adresse.
- **Rate Limiting** pro Client, Schiebefenster, Standard 120/Minute, `Retry-After`.
- **Eingabevalidierung.** Projekt-IDs, Build-IDs, Commits und Branches muessen
  ihrem Muster entsprechen. Eine Build-ID, die keine ist, trifft gar keine Route.
- **Kein Pfad von aussen.** Keine Route nimmt einen Dateipfad entgegen.
  `/artifacts` liefert Namen und Groessen, nie Inhalte.
- **Keine Shell.** Git laeuft als Argumentliste, nie ueber `shell=True`.
- **Schwaerzung.** Jede Antwort laeuft durch `redact()`.
- **Body-Grenze** 64 KB, JSON-Objekt erzwungen.
- **Keine Tracebacks nach draussen** - nur der Ausnahmetyp, das Detail steht im
  Audit-Log.
- **Header**: `X-Content-Type-Options: nosniff`, restriktive CSP,
  `frame-ancestors 'none'`, `no-store`, `Referrer-Policy: no-referrer`.
- **Abgelehnte Aufrufe** landen als `api.denied` im Audit-Log.

## Dashboard

`/` verlangt dasselbe Token. `?token=<agent-token>` tauscht es einmalig gegen ein
`HttpOnly`-Cookie (8 Stunden). Das Token selbst steht nie im HTML.

## Client statt Handarbeit

Es gibt einen fertigen Client - `bb/agent_client.py`, reine Standardbibliothek.
Details und Fehlerbehandlung in `AGENT_INTEGRATION.md`.

```python
from bb.agent_client import BurgysClient
bb = BurgysClient()
bb.capabilities()["policy"]
```

## Fuer Buergys Agent

Der Agent fuehrt keine Shell-Befehle aus. Er spricht diese API. Empfohlene
Schleife:

1. `GET /status` - Cost Guard aktiv? Executor da? Platte ok?
2. `POST /preflight` - kostenlos, beliebig oft
3. Bei `ok: true`: `POST /builds` mit `dry_run: true` zum Ueben, oder mit dem
   Release-Token fuer echt
4. `GET /builds/{id}` pollen, `GET /builds/{id}/logs` bei Fehlern
5. `GET /builds/{id}/artifacts` fuer SHA-256 und OTA-Link

Ein Build, der `WAITING_APPROVAL` meldet, wartet auf einen Menschen. Der Agent
soll das melden, nicht umgehen.

**Ohne Worker passiert nichts.** `burgys serve` nimmt Builds an und legt sie in
die Queue; ausgefuehrt werden sie erst durch `burgys run` oder durch
`burgys serve --worker`. Fuer den Betrieb mit Buergys Agent ist `--worker`
richtig - er faehrt nur ab, was ohnehin laufen darf.
