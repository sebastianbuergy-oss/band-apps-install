# OTA-Installation

## Warum das First Class ist

Sebastian installiert direkt auf seine registrierten iPhones, nicht ueber
TestFlight. Also ist OTA kein Nachgedanke, sondern der Normalfall nach einem
Ad-Hoc-Build. Eine automatische Umstellung auf TestFlight findet nicht statt.

## Der Ablauf

Nach einem erfolgreichen `AD_HOC`-Build erzeugt `bb/ota.py::prepare`:

1. **IPA erfassen** - Groesse und Inhalt gelesen
2. **SHA-256** ueber die ganze Datei
3. **Manifest** `<slug>.plist` im `itms-services`-Format
4. **HTTPS-Quelle** - eine `http`-URL wird abgelehnt, iOS installiert darueber
   ohnehin nichts
5. **QR-Code** als `qr.svg` und `qr.png`
6. **`release.json`** mit allen Metadaten
7. Die IPA daneben, unter dem Namen, den das Manifest erwartet

Alles landet in `data/ota/<build-id>/`. **Die Live-Seite wird nicht angefasst.**
Das Kopieren nach `band-apps-install/` ist ein eigener, bewusster Schritt.

## Was veroeffentlicht wird - und was nicht

`check_publishable` sammelt *alle* Gruende auf einmal und lehnt ab bei:

- Dry-Run-Build (es gibt keine IPA - ein Mock wird nie als installierbar ausgegeben)
- Modus ist nicht `AD_HOC`
- Bundle ID der IPA passt nicht zum Projekt
- keine Codesignatur
- die IPA ist nicht Ad Hoc signiert (App Store, Development, Enterprise)
- Profil abgelaufen
- Profil listet keine registrierten Geraete
- Profilname weicht vom konfigurierten ab

Jeder dieser Faelle hat einen Test.

## Das Manifest

Das erzeugte `.plist` ist **byte-identisch** mit dem, was heute live liegt
(Test: `test_ota.py::test_generated_plist_matches_the_live_one_byte_for_byte`).
Buergys Builds kann die Erzeugung uebernehmen, ohne dass sich fuer iOS
irgendetwas aendert.

```
itms-services://?action=download-manifest&url=https://<base>/<slug>.plist
```

## Die Installationsseite

`render_install_page` erzeugt die Seite aus Abschnitt 10 des Auftrags: pro App
Icon, Name, **Version**, **Buildnummer**, Installieren-Button, **Commit**,
**Erstellungsdatum**, **Groesse**, Mindest-iOS und **SHA-256**; dazu ein
QR-Code auf die Seite selbst.

Die Farbgebung folgt der bestehenden Seite (dunkel, pro Band ein Akzent). Der
Days-of-Ruin-Akzent ist hier `#a3ff12` - das Giftgruen aus Commit `218d93c`.
Auf der Live-Seite ist der Button noch pink, weil das Inline-`style` dort nie
mitgeaendert wurde (`.burgys/KNOWN_ISSUES.md`, BB-I-001).

`noindex, nofollow` ist gesetzt, wie bei den Browser-Versionen.

## QR-Code

`bb/qr.py` ist ein vollstaendiger QR-Encoder in der Standardbibliothek: Byte-Modus,
Versionen 1-10, Level L/M/Q/H, alle acht Masken mit Bewertung, SVG-, PNG- und
Terminal-Ausgabe.

Wie er geprueft wird:

- Die Codewort-Tabellen werden **aus der Modul-Geometrie abgeleitet**, nicht
  abgetippt, und die Blocktabelle wird beim Import dagegen geprueft
  (`self_check()`). Die abgeleiteten Summen (26, 44, 70, 100, 134, 172, 196,
  242, 292, 346) stimmen mit der Norm ueberein.
- Ein **unabhaengiger Decoder** in `tests/qrdecode.py` liest die fertige Matrix
  zurueck: Formatinformation, Demaskierung, Zickzack-Leseordnung,
  De-Interleaving, Modus und Laenge.
- Die **Reed-Solomon-Syndrome** jedes Blocks muessen null sein - eine Pruefung,
  die den Encoder nicht wiederholt, sondern das Codewort an den Nullstellen des
  Generatorpolynoms auswertet.

Alle 40 Kombinationen aus Version und Level laufen durch diesen Test, dazu die
echten Installations-URLs und UTF-8.

Trotzdem gilt: **TESTED, nicht DEVICE VERIFIED.** Ob ein iPhone den Code
tatsaechlich scannt, weiss man erst, wenn ein iPhone ihn gescannt hat.

```
burgys qr "https://sebastianbuergy-oss.github.io/band-apps-install/"
burgys qr "https://..." --out qr.png
```

## Veroeffentlichen

Heute von Hand, und das ist Absicht - die Live-Seite ist die, ueber die die Band
ihre Apps bekommt:

```
copy data\ota\BB-...\thy-gnosis.ipa    ..\band-apps-install\
copy data\ota\BB-...\thy-gnosis.plist  ..\band-apps-install\
git -C ..\band-apps-install add -A && git -C ..\band-apps-install commit -m "..." && git -C ..\band-apps-install push
```

Ein `ota_publish_dir` ist vorgesehen, aber leer voreingestellt. Automatisches
Deployen auf eine oeffentliche Seite kommt erst, wenn der Pilot durch ist.
