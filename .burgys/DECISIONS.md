# Entscheidungen

Werden nicht stillschweigend geaendert. Eine ueberholte Entscheidung wird als
abgeloest markiert und bekommt eine neue mit Begruendung daneben.

---

## BB-D-001 - Reine Standardbibliothek

**2026-09-20, Claude**

Buergys Builds nutzt ausschliesslich die Python-Standardbibliothek.

*Warum:* Auf dem HP soll ein blankes Python genuegen - kein `pip`, kein
Paketindex, kein Compiler, kein Netz. Ein Build-System, das sich selbst erst
bauen muss, ist ein Problem mehr. Die Kosten sind ein selbstgeschriebener
QR-Encoder und ein selbstgeschriebener PNG-Writer; beide sind getestet.

*Folge:* Auch die HTTP-API und das Dashboard laufen auf `http.server`. Kein
Flask, kein FastAPI.

---

## BB-D-002 - Cost Guard faellt geschlossen aus

**2026-09-20, Claude**

Eine Ressource, die der Cost Guard nicht kennt, gilt als kostenpflichtig und
wird blockiert.

*Warum:* Die Alternative waere, Unbekanntes durchzulassen. Dann kostet der
naechste Cloud-Mac-Anbieter, den niemand eingetragen hat, Geld. Fail closed ist
gelegentlich laestig und nie teuer.

*Folge:* Ein neuer Executor braucht einen Eintrag in `RESOURCES`, sonst
funktioniert er nicht. Das ist gewollt.

---

## BB-D-003 - GitHub Actions auf oeffentlichen Repos als erster Executor

**2026-09-20, Claude**

Der vorgeschlagene Weg zur ersten echten IPA ist ein GitHub-Actions-Workflow mit
`runs-on: macos-latest` im jeweiligen App-Repo.

*Warum:* GitHub dokumentiert, dass Standard-Runner auf oeffentlichen
Repositories kostenlos und unbegrenzt sind - macOS eingeschlossen. `thy-gnosis-ios`
und `days-of-ruin-ios` sind beide oeffentlich. Damit kostet der Pilot nichts,
und es braucht weder Codemagic noch einen Cloud-Mac noch sofort einen Mac mini.

*Geprueft am:* 2026-09-20 gegen die GitHub-Dokumentation.

*Grenzen:* Larger Runners sind auch auf oeffentlichen Repos kostenpflichtig -
`runs-on` nicht aendern. Wird ein Repo privat, muss `visibility` mitgeaendert
werden; bei unbekannter `visibility` nimmt der Cost Guard `private` an.

*Abgeloest wenn:* GitHub das Preismodell aendert, oder der Mac mini kommt.

---

## BB-D-004 - Thy Gnosis ist der Pilot

**2026-09-20, Claude**

*Warum, gegen die Kriterien aus Abschnitt 24:*

- **Geringe Gefahr:** Fan-App fuer eine Berner Band, keine zahlenden Nutzer,
  keine Daten, kein Backend. Ein fehlgeschlagener Build kostet niemanden etwas.
- **Signing bekannt:** Ad-Hoc-Profil und Zertifikat sind aus der ausgelieferten
  IPA ausgelesen und dokumentiert, gueltig bis 2027-08-14, zwei registrierte
  Geraete.
- **OTA bekannt:** Laeuft bereits ueber GitHub Pages; das erzeugte Manifest ist
  byte-identisch mit dem bestehenden.
- **Ueberschaubare Abhaengigkeiten:** Keine Pods, kein SPM, kein Flutter. Xcode
  wird aus `project.yml` generiert. Die App ist eine `WKWebView`-Huelle um einen
  `web/`-Ordner.
- **Repo oeffentlich:** also kostenlos baubar (BB-D-003).
- **Store nicht gefaehrdet:** Der Ad-Hoc-Weg ist vom App-Store-Weg getrennt;
  `APP_STORE_RELEASE` ist ohnehin blockiert, bis `build_number_floor` steht.

Days of Ruin ist technisch identisch und folgt, sobald der Pilot durch ist.

---

## BB-D-005 - Der Dry-Run-Executor darf nie wie ein echter Build aussehen

**2026-09-20, Claude**

Ein simuliertes Ergebnis traegt `simulated`, das Manifest `dry_run`, die Anzeige
schreibt `SUCCESS (DRY RUN - kein echter iOS-Build)`, es zaehlt nicht gegen das
Build-Limit, es erzeugt kein Artefakt, und OTA lehnt es ab.

*Warum:* Abschnitt 28 des Auftrags. Ein gruener Mock, den jemand fuer einen Build
haelt, ist schlimmer als gar kein Mock.

---

## BB-D-006 - Buergys Builds haelt keine privaten Schluessel

**2026-09-20, Claude**

Nur Profilnamen und Zertifikatsnamen - genug fuer Widerspruchspruefungen, zu
wenig um Schaden anzurichten. Die Schluessel liegen beim Executor.

*Folge:* Buergys Builds kann eine IPA pruefen, aber nicht signieren. Das ist die
richtige Arbeitsteilung.

---

## BB-D-007 - Die Live-Installationsseite wird nicht automatisch ueberschrieben

**2026-09-20, Claude**

`bb/ota.py` schreibt nach `data/ota/<build-id>/`. Das Kopieren in das
Pages-Verzeichnis ist ein eigener, bewusster Schritt.

*Warum:* Prioritaet 3 des Auftrags. Ueber diese Seite bekommt die Band ihre Apps.
Ein automatisches Deployment aus einem System, das noch keinen einzigen echten
Build gemacht hat, waere die falsche Reihenfolge.

*Abgeloest wenn:* Der Pilot ist `PRODUCTION VERIFIED`. Dann BB-009.

---

## BB-D-008 - Der Code liegt vorerst in `band-apps-install`

**2026-09-20, Claude**

*Warum:* Der Auftrag nennt diesen Branch in diesem Repository. Also hier.

*Was daran unschoen ist:* `band-apps-install` ist ein oeffentliches
GitHub-Pages-Repo. Der Quellcode wird damit mit ausgeliefert. Das ist kein
Sicherheitsproblem - es sind keine Secrets darin, und das soll auch so bleiben -
aber es vermischt eine Installationsseite mit einem Build-System.

*Vorschlag:* Ein eigenes, privates Repository `burgys-builds`, sobald der Pilot
durch ist. `data/` ist bereits per `.gitignore` ausgeschlossen.

*Entscheidung offen - Sebastians Sache.*
