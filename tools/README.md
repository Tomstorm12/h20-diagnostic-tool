# tools/

Deze map is gereserveerd voor optionele externe hulpmiddelen die de diagnostiek
kunnen uitbreiden. De hoofdtool heeft deze bestanden **niet** nodig om te werken.

## Voorgestelde inhoud

| Bestand                          | Doel                                                                 |
|----------------------------------|----------------------------------------------------------------------|
| `OpenHardwareMonitorLib.dll`     | Uitgebreide CPU/GPU/moederbord-temperaturen via Open Hardware Monitor |
| `smartctl.exe` (smartmontools)   | Diepere SMART-diagnose dan wat WMI oplevert                          |
| `crystaldiskinfo-portable/`      | Portable CrystalDiskInfo voor handmatige SSD/HDD-inspectie           |

## Licenties

Voeg elke tool toe met respect voor de originele licentie. Plaats een kopie van
de licentie bij het binary (bijv. `OpenHardwareMonitorLib.LICENSE.txt`).

## Integratie

`src/h20_diagnostic.py` detecteert automatisch of deze bestanden aanwezig zijn
en gebruikt ze indien beschikbaar. Ontbreken ze, dan valt de tool terug op
pure WMI/psutil-metingen.
