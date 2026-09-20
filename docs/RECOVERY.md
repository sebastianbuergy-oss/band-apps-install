# Recovery

Ein Buildsystem muss Fehler ueberleben - Stromausfall, geschlossenes
Terminal, Bluescreen mitten im Build.

## Was auf der Platte liegt

```
data/
  queue.json              Wartende und laufende Jobs
  cost_ledger.json        Verbrauchte Minuten pro Monat
  projects/<id>/build_number.json
  builds/<build-id>/manifest.json
  artifacts/<build-id>/
  logs/<build-id>.log
  ota/<build-id>/
  audit/audit-YYYY-MM.jsonl
```

Jede Schreiboperation geht ueber `write_json`: temporaere Datei im selben
Verzeichnis, `fsync`, dann `os.replace`. Das ist auf NTFS und POSIX atomar - eine
halb geschriebene Statusdatei kann es nicht geben. Bei `ENOSPC` wird die
temporaere Datei aufgeraeumt und `DiskFull` gemeldet, nie eine halbe Datei
hinterlassen.

## Sperren

Ein Verzeichnis-Lock (`mkdir` ist atomar auf beiden Systemen) schuetzt Queue,
Buildnummern, Audit-Log und Manifeste. Dazu ein prozessinterner Thread-Lock, damit
Threads nicht erst auf dem Dateisystem kollidieren.

Ein Lock, dessen Besitzer laenger als `stale_after` (Standard 5 Minuten) nichts
mehr gemeldet hat, wird gebrochen - ein abgeschossener Controller blockiert die
Queue nicht dauerhaft. Die Frische wird notfalls an der mtime des
Lock-Verzeichnisses gemessen, nicht nur an der Besitzerdatei: sonst koennte ein
zweiter Wartender in dem Moment zuschlagen, in dem das Verzeichnis schon
existiert, die Besitzerdatei aber noch nicht geschrieben ist. Genau dieser Fall
ist beim Testen aufgefallen und behoben worden - es gibt jetzt einen Test mit
acht echten Prozessen dafuer.

## Nach einem Neustart

`burgys recover`, und automatisch bei jedem `burgys serve`:

| Vorgefundener Zustand | Was passiert |
|---|---|
| `MAC_BUILDING`, `SIGNING`, `EXPORTING`, `WAITING_MAC` | **`FAILED`, `failure_reason: INTERRUPTED_BY_RESTART`** - **nicht** neu gestartet |
| `PREFLIGHT`, `WINDOWS_TESTING`, `QUEUED`, `READY` | zurueck in die Queue - kostet nur HP-Zeit |
| bereits terminal | aus der Queue entfernt |
| Manifest fehlt | Eintrag entfernt |

Der Unterschied ist der ganze Punkt: ein unterbrochener macOS-Job koennte in
Wahrheit noch laufen. Ihn automatisch neu zu starten hiesse, Minuten doppelt zu
verbrauchen und eventuell zwei IPAs mit derselben Buildnummer zu erzeugen. Also
wird er markiert und Sebastian entscheidet.

Was in jedem Fall bleibt: Logs, fertige Artefakte, Manifeste, Audit-Log,
Buildnummern, Minutenzaehler.

## Abbrechen

```
burgys cancel BB-20260920-TG-001
```

Nimmt den Job aus der Queue, sagt dem Executor Bescheid (falls er schon laeuft)
und setzt `CANCELLED`. Ein bereits terminaler Build laesst sich nicht abbrechen.

## Zeitgrenze

`mac_job_timeout_minutes` (Standard 30) bricht einen haengenden macOS-Job ab -
das ist die Versicherung gegen einen Runner, der still vor sich hin laeuft.

## Speicher

Vor jedem Build: `require_disk`. Unter `min_free_bytes` (2 GiB) wird `BLOCKED`
gemeldet statt angefangen. Das Dashboard zeigt `OK` / `WARN` (unter 10 GiB) /
`CRITICAL`.

Konfigurierbare Aufbewahrung: `retention_days_builds`, `retention_days_logs`,
`retention_keep_artifacts_per_project`. Das automatische Aufraeumen ist noch
nicht implementiert - offener Punkt BB-I-002.

## Was zu tun ist, wenn etwas kaputt aussieht

```
burgys status            # Systemsicht
burgys recover           # Queue aufraeumen
burgys builds --limit 20 # was steht wo
burgys logs BB-...       # was zuletzt passiert ist
```

`data/` ist reines JSON und Text. Im Zweifel mit dem Editor ansehen. Geloescht
werden darf `data/` komplett - dann sind Historie und Artefakte weg, aber nichts
am System ist beschaedigt.
