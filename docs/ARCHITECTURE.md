# Architektur

## Der Grundgedanke

macOS-Rechenzeit ist das Einzige an einem iOS-Build, das Geld kostet. Also macht
Buergys Builds alles andere auf Sebastians HP - kostenlos, beliebig oft, ohne
Wartezeit - und uebergibt an einen Mac erst, wenn nichts mehr schiefgehen kann,
was man vorher haette sehen koennen.

```
                     Sebastians HP (Windows)                    |  macOS
  ------------------------------------------------------------- | -----------
  Buergys Agent ─┐                                               |
  CLI ───────────┼─> Agent API ─> BuildController                |
  Dashboard ─────┘                    │                          |
                                      ├─ Cost Guard  ──┐         |
                                      ├─ Build-Limit   ├─ STOP   |
                                      ├─ Preflight     │         |
                                      ├─ Duplikate ────┘         |
                                      ├─ Buildnummer             |
                                      ├─ Queue                   |
                                      │                          |
                                      └─> MacExecutor ───────────┼─> Archive
                                               ▲                 |   Signing
                                               │                 |   Export
                                      IPA <────┴─────────────────┘
                                      │
                                      ├─ verify.py   (Bundle ID, Buildnr, Profil)
                                      ├─ SHA-256
                                      ├─ OTA: Manifest, Seite, QR
                                      └─ Audit-Log, Build-Manifest
```

Alles links des Strichs ist kostenlos und laeuft ohne Netz. Rechts steht so wenig
wie moeglich.

## Module

| Modul | Aufgabe |
|---|---|
| `bb/config.py` | Konfiguration. Unbekannte Schluessel sind ein Startfehler, damit ein Tippfehler im Cost Guard nicht als "aus" durchgeht |
| `bb/store.py` | Atomare Schreibvorgaenge (`os.replace`), Verzeichnis-Lock, Speicherwaechter, Path-Traversal-Schutz |
| `bb/states.py` | Die 16 Zustaende aus Abschnitt 13, samt erlaubter Uebergaenge |
| `bb/ids.py` | `BB-YYYYMMDD-CODE-NNN`, Validierung aller Bezeichner |
| `bb/redact.py` | Schwaerzung nach Schluesselname und nach Muster |
| `bb/audit.py` | Append-only JSONL, monatsweise, geschwaerzt |
| `bb/costguard.py` | Klassifiziert Ressourcen, zaehlt Freikontingente, faellt geschlossen aus |
| `bb/limits.py` | 20 echte Builds pro Projekt / 24 h, Duplikaterkennung |
| `bb/projects.py` | Registry und zugleich Pfad-Allowlist |
| `bb/gitinfo.py` | Git, immer als Argumentliste, nie als Shell-String |
| `bb/preflight.py` | 13 Pruefungen auf Windows |
| `bb/manifest.py` | Build-Manifest, monotone Buildnummern |
| `bb/queue.py` | Queue mit Neustart-Recovery |
| `bb/executors/` | `MacExecutor` + `none`, `dryrun`, `github`, `local` |
| `bb/builds.py` | Der Ablauf, in der Reihenfolge der Prioritaeten |
| `bb/ipa.py` | IPA auf Windows lesen: Info.plist, Profil, SHA-256 |
| `bb/verify.py` | Die fertige IPA gegen das Bestellte pruefen |
| `bb/ota.py` | Manifest, Installationsseite, Pruefsumme |
| `bb/qr.py` | QR-Encoder (stdlib, Versionen 1-10, L/M/Q/H) |
| `bb/api.py` | Lokale HTTP-API + Dashboard-Auslieferung |
| `bb/dashboard.py` | Server-gerendertes HTML, kein JavaScript |
| `bb/cli.py` | `burgys` |

## Warum reine Standardbibliothek

Ein Build-System, das sich selbst erst per `pip install` bauen muss, ist ein
Build-System weniger. Auf dem HP soll ein blankes Python genuegen: kein
Paketindex, kein Compiler, kein Netz. Das kostet an genau zwei Stellen Arbeit -
der QR-Encoder und der PNG-Writer sind selbst geschrieben - und spart sie ueberall
sonst.

## Reihenfolge im Controller

`request_build` prueft in dieser Reihenfolge, und die Reihenfolge ist die der
Prioritaetenliste aus dem Auftrag:

1. Ist der Modus fuer dieses Projekt vorgesehen?
2. Ist genug Platz auf der Platte?
3. **Cost Guard** - bevor irgendetwas angelegt wird
4. **Build-Limit** - Dry Runs zaehlen nicht
5. **Preflight** auf Windows
6. **Duplikate** - identischer Commit schon gebaut?
7. Build-ID und Buildnummer vergeben
8. **Freigabe** - ein echter macOS-Job wartet auf Sebastian
9. In die Queue

Erst `run_next` fasst einen Executor an. Der Cost Guard laeuft dort ein zweites
Mal, unmittelbar bevor Minuten anfallen.

## Was bewusst *nicht* gebaut ist

- Keine Datenbank. Eine JSON-Datei pro Build, eine fuer die Queue. Nach einem
  Stromausfall ist das mit `type` lesbar und mit dem Auge zu pruefen.
- Kein Webhook-Empfaenger, kein oeffentlicher Endpunkt.
- Kein automatisches Deploy auf die Live-Installationsseite. `bb.ota` legt alles
  neben den Build; das Kopieren ist ein eigener, bewusster Schritt.
- Keine Secret-Verwaltung. Buergys Builds haelt keine privaten Schluessel; der
  Executor holt sie an seinem Ende (`SIGNING.md`).
