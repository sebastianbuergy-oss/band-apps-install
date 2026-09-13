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
https://sebastianbuergy-oss.github.io/band-apps-install/thy-gnosis/

Auf Android in Chrome über das Menü «Zum Startbildschirm hinzufügen» wie eine App
ablegen. Aktualisieren: `python sync_web.py thy-gnosis`, dann committen und pushen.
Die Seite ist mit `noindex` markiert, weil sie eine Testversion für die Band ist.
