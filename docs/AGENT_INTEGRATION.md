# Buergys Agent anbinden

Was Buergys Builds bereitstellt, damit der Agent nicht raten muss - und was
er ausdruecklich **nicht** darf.

## In einem Satz

Der Agent startet keine Shell. Er redet mit einer lokalen HTTP-API, bekommt
typisierte Antworten und kann kein Geld ausgeben, weil der Cost Guard auf der
Serverseite sitzt und sein Token gar keinen echten Build starten darf.

## Controller starten

Auf dem HP, einmal:

```bat
cd burgys-builds
python -m bb.cli init
python -m bb.cli serve --worker
```

`--worker` ist der Unterschied zwischen "der Agent kann Builds anfordern" und
"die Builds laufen auch". Ohne den Worker landen angeforderte Builds in der
Queue und warten darauf, dass jemand `burgys run` tippt - richtig fuer einen
Menschen am Rechner, nutzlos fuer einen Agenten.

Der Worker faehrt **nur ab, was ohnehin laufen darf**: ein Build, der auf
Freigabe wartet, kommt gar nicht erst in die Queue.

## Zwei Tokens, zwei Reichweiten

Stehen in `~/.burgys/agent_token`, erzeugt beim ersten `init`.

| Token | darf |
|---|---|
| `agent` | lesen, Preflight, Build **vorbereiten**, Dry Runs, Logs, abbrechen |
| `release` | zusaetzlich echten Build starten, freigeben, veroeffentlichen |

**Der Agent bekommt das `agent`-Token.** Alles, was Geld kostet oder nach
aussen wirkt, braucht bewusst das zweite - das ist Abschnitt 29 des Auftrags,
in der Tokenvergabe durchgesetzt statt in einer Regel, an die man sich
erinnern muss.

## Der Client

```python
from bb.agent_client import BurgysClient, BurgysRefused, BurgysDenied

bb = BurgysClient()          # liest das agent-Token, spricht 127.0.0.1:8787
```

Erst fragen, was ueberhaupt geht:

```python
caps = bb.capabilities()
caps["identity"]["scopes"]                     # ['read', 'preflight', 'prepare']
caps["policy"]["executor_produces_real_ipa"]   # False, solange kein Mac da ist
caps["policy"]["paid_services_allowed"]        # False

ready, reasons = bb.ready_for_real_builds()
# (False, ['Executor "none" erzeugt keine echte IPA',
#          'Dieses Token darf keinen echten Build starten', ...])
```

Dann arbeiten:

```python
report = bb.preflight("thy-gnosis")
if not report["ok"]:
    for r in report["results"]:
        if r["status"] == "FAIL":
            print(r["check"], r["message"])
else:
    build = bb.request_build("thy-gnosis", dry_run=True)
    final = bb.wait_for(build["build_id"])
    print(final["display_status"])
```

`wait_for` haelt auch bei `WAITING_APPROVAL` an - dort wartet ein Mensch, und
ein Agent, der darauf pollt, wartet ewig.

## Fehler auseinanderhalten

Der wichtigste Teil des Vertrags. Der Agent muss "ich darf nicht" von "das
System sagt nein" von "es ist kaputt" unterscheiden koennen:

| Ausnahme | Bedeutung | Was der Agent tun soll |
|---|---|---|
| `BurgysUnreachable` | Controller laeuft nicht | Spaeter nochmal, oder melden |
| `BurgysDenied` | Token fehlt der Scope | **Nicht** wiederholen. Menschen fragen |
| `BurgysRefused` | Cost Guard, Build-Limit, unzulaessiger Zustand | **Nicht** umgehen. `.state` sagt, was daraus wird |
| `BurgysInvalid` | Eingabe war falsch | Eingabe korrigieren |
| `BurgysRateLimited` | zu viele Anfragen | `.retry_after` abwarten |

`BLOCKED_BY_COST_GUARD` ist endgueltig. Es gibt keinen kostenpflichtigen
Ausweichweg, und es gibt auch keinen Parameter, der einen freischaltet -
das ist Absicht.

## Der gemeinsame Zustand

`.burgys/state.json` wird jetzt **vom Controller geschrieben**, nicht mehr von
Hand. Agent, Claude und Codex lesen sie vor der Arbeit (Abschnitt 18):

```json
{
  "system_status": {
    "windows_controller": "ONLINE",
    "mac_executor": "OFFLINE",
    "mac_executor_produces_real_ipa": false,
    "cost_guard": true,
    "disk": "OK"
  },
  "builds": {
    "queue_length": 0,
    "running": [],
    "waiting_approval": [],
    "last_success": { "build_id": "...", "artifact_sha256": "..." }
  }
}
```

Handgeschriebene Felder daneben (`active_tasks`, `notes`, Entscheidungen)
bleiben erhalten - die Maschine ueberschreibt nur, was sie selbst beobachtet.

`cost_guard: true` heisst: der Guard ist **aktiv**, kostenpflichtige Dienste
sind gesperrt.

## Was der Agent nie tun soll

- Einen Build starten, den `capabilities()` als nicht erlaubt meldet
- Auf `WAITING_APPROVAL` warten oder es umgehen
- `BLOCKED_BY_COST_GUARD` als voruebergehend behandeln
- Ein Dry-Run-Ergebnis als echten Build melden - das Feld `display_status`
  sagt ausdruecklich `SUCCESS (DRY RUN - kein echter iOS-Build)`
- Dateien im Pages-Repo anfassen. Dafuer gibt es `publish`, und das braucht
  das Release-Token

## Ein vollstaendiger Ablauf

```python
bb = BurgysClient()

# 1. Lage pruefen
if bb.status()["disk"]["level"] == "CRITICAL":
    raise SystemExit("Platte voll - kein Build")

# 2. Kostenlos so weit wie moeglich
report = bb.preflight("thy-gnosis")
if not report["ok"]:
    raise SystemExit(f"{report['summary']['fail']} Preflight-Fehler")

# 3. Pipeline ueben, ohne Mac und ohne Kosten
dry = bb.wait_for(bb.request_build("thy-gnosis", dry_run=True)["build_id"])
assert "DRY RUN" in dry["display_status"]

# 4. Echter Build: geht nur mit dem Release-Token und Freigabe
ready, reasons = bb.ready_for_real_builds()
if not ready:
    print("Echter Build derzeit nicht moeglich:", *reasons, sep="\n  ")
```

## Betrieb

Der Controller kann als Autostart laufen (`INSTALL_WINDOWS.md`). Nach einem
Neustart raeumt er die Queue selbst auf und schreibt den Zustand neu - ein
Build, der auf einem Mac unterbrochen wurde, wird als unterbrochen markiert
und **nicht** automatisch wiederholt.

## Was noch fehlt

Buergys Agent selbst gibt es noch nicht - in keinem erreichbaren Repository
ist davon etwas zu finden. Diese Seite beschreibt die Seite, die bereitsteht.
Wenn der Agent kommt, ist das Anbinden Verdrahtung, kein Umbau.
