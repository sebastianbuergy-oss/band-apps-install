# Kostenmodell

## Die Regel

```
PAID_SERVICES_ALLOWED=false
```

Das ist der Standard und der einzige Schalter, der Geld freigibt. Ohne ihn
verweigert Buergys Builds jede kostenpflichtige Ressource und meldet
`BLOCKED_BY_COST_GUARD` mit Begruendung. Es gibt **keinen automatischen
kostenpflichtigen Fallback**, auch nicht wenn ein Freikontingent erschoepft ist.

Eine Ressource, die der Cost Guard nicht kennt, gilt als kostenpflichtig. Fail
closed - ein neuer Cloud-Mac-Anbieter im Jahr 2027 wird blockiert, weil niemand
ihn eingetragen hat, nicht durchgewunken, weil niemand ihn verboten hat.

## Klassifikation

| Ressource | Kosten | Bemerkung |
|---|---|---|
| `windows_local` | FREE | Der HP. Strom, sonst nichts |
| `github_pages` | FREE | OTA-Hosting fuer oeffentliche Repos |
| `local_mac` | FREE | Ein eigener Mac mini. Noch nicht vorhanden |
| `github_actions_macos_public_repo` | FREE_TIER | **Der Weg, den wir vorschlagen** - siehe unten |
| `github_actions_macos_private_repo` | PAID | macOS-Minuten auf privaten Repos rechnen 10-fach |
| `codemagic` | PAID | Die Kosten, die wir loswerden wollen |
| `xcode_cloud` | PAID | Freikontingent existiert, ist aber an den Account gebunden |
| `macstadium`, `aws_mac`, `azure_mac` | PAID | Cloud-Macs. AWS mit 24-h-Mindestbelegung |
| `paid_artifact_storage` | PAID | Nicht noetig, lokal reicht |
| alles Unbekannte | PAID | Fail closed |

## Der entscheidende Befund

GitHub dokumentiert:

> "Use of the standard GitHub-hosted runners is free and unlimited on public
> repositories."
> "GitHub Actions usage is free for self-hosted runners and for public
> repositories that use standard GitHub-hosted runners."

Zu den *standard runners* gehoeren die macOS-Labels `macos-latest`, `macos-14`,
`macos-15`, `macos-26`, `xcode-27` sowie `macos-15-intel` / `macos-26-intel`.

Und: **`thy-gnosis-ios` und `days-of-ruin-ios` sind beide oeffentlich.**

Damit kostet ein Ad-Hoc-Build dieser beiden Apps auf GitHub Actions **nichts**.
Kein Codemagic-Abo, kein Cloud-Mac, kein Mac mini noetig, um den Pilot zu fahren.

Geprueft am 2026-09-20 gegen die GitHub-Dokumentation. Zwei Einschraenkungen, die
mitgehoeren:

1. **Larger runners sind auch auf oeffentlichen Repos kostenpflichtig.** Das
   Workflow-Template in `burgys-builds/templates/` nutzt `runs-on: macos-latest`.
   Wer das auf einen groesseren Runner aendert, faengt an zu zahlen. Der Cost
   Guard kennt nur die Standard-Variante als kostenlos.
2. **Ein privates Repo ist ein anderer Fall.** Sollte eines der App-Repos je auf
   privat gestellt werden, ist `visibility` in `executor_config` mitzuaendern -
   sonst blockiert der Cost Guard, was richtig ist. Bei unbekannter
   `visibility` nimmt er `private` an, also kostenpflichtig.

Preismodelle aendern sich. Der Cost Guard misst die verbrauchten Minuten deshalb
trotzdem mit (`cost_ledger.json`, Kappung bei 2000 Minuten/Monat), damit eine
Regelaenderung nicht unbemerkt Geld kostet.

## Was ein eigener Mac mini brauchen wuerde

Das Dashboard zeigt **macOS-Minuten pro Projekt**. Wenn der GitHub-Weg kostenlos
bleibt, ist die Zahl vor allem interessant fuer Wartezeit, nicht fuer Geld. Falls
er es nicht bleibt, ist es die Zahl, an der sich rechnen laesst, ob sich ein Mac
mini lohnt: ein M4 Mac mini kostet einmalig in der Groessenordnung eines
Codemagic-Jahres und faellt danach als laufende Kosten weg.

Diese Rechnung wird hier bewusst **nicht** vorweggenommen. Erst Daten sammeln.

## Was Geld kosten koennte und blockiert ist

- Codemagic weiterlaufen lassen: laeuft aktuell weiter, **und das ist so gewollt**
  (`CODEMAGIC_MIGRATION.md`). Buergys Builds loest dort nichts aus.
- GitHub Actions auf einem privaten Repo: blockiert.
- Jeder Cloud-Mac: blockiert.
- App-Store-Upload: keine Geldkosten, aber eine Aussenwirkung - eigener Modus,
  eigene Freigabe.
