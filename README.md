# Band-Apps installieren

Installationsseite für die beiden iPhone-Fan-Apps, ad hoc signiert für Sebastians
und Lynns iPhone. Läuft über GitHub Pages, damit die itms-services-Installation
über HTTPS funktioniert.

https://sebastianbuergy-oss.github.io/band-apps-install/

Neue Version veröffentlichen: in Codemagic den Workflow `ios-adhoc` des jeweiligen
Repos starten, die `.ipa` aus den Artefakten hier ersetzen, `bundle-version` in der
passenden `.plist` hochzählen, committen und pushen.
