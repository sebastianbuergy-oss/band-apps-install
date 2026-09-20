# Band-Apps installieren

Installationsseite für die beiden iPhone-Fan-Apps, ad hoc signiert für Sebastians
und Lynns iPhone. Läuft über GitHub Pages, damit die itms-services-Installation
über HTTPS funktioniert.

https://sebastianbuergy-oss.github.io/band-apps-install/

Neue Version veröffentlichen: in Codemagic den Workflow `ios-adhoc` des jeweiligen
Repos starten, die `.ipa` aus den Artefakten hier ersetzen, `bundle-version` in der
passenden `.plist` hochzählen, committen und pushen.

## Browser-Version (Android)

Wer kein iPhone hat, öffnet die gleiche App im Browser:
- Thy Gnosis: https://sebastianbuergy-oss.github.io/band-apps-install/thy-gnosis/
- Days of Ruin: https://sebastianbuergy-oss.github.io/band-apps-install/days-of-ruin/

Auf Android in Chrome über das Menü «Zum Startbildschirm hinzufügen» wie eine App
ablegen. Aktualisieren: `python sync_web.py thy-gnosis days-of-ruin`, dann committen und pushen.
Die Seite ist mit `noindex` markiert, weil sie eine Testversion für die Band ist.

## Bürgys Builds

In `burgys-builds/` liegt der Build-Controller, der Codemagic für diese Apps
ablösen soll: Preflight, Tests, Queue, Buildnummern, Signing-Prüfung,
IPA-Verifikation, OTA-Manifest, QR-Code, Dashboard und eine lokale API für
Bürgys Agent — alles auf Windows, kostenlos, mit reiner Standardbibliothek.
Der macOS-Schritt (Archive, Signing, Export) steckt hinter einer
Executor-Schnittstelle und ist heute bewusst nicht freigegeben.

```
cd burgys-builds
python -m bb.cli init
python -m bb.cli preflight thy-gnosis
python -m bb.cli dashboard
```

Einstieg: [`docs/INVENTORY.md`](docs/INVENTORY.md) — was da ist und was fehlt —
und [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Die Installationsseite und
die Browser-Versionen oben sind davon unberührt und funktionieren wie bisher.
