# ebevTool

Excel-alapú statisztikagenerátor egyszerűsített foglalkoztatási (e-bev) bejelentésekhez.
A bemeneti Excel-fájlból (`e-bev` munkalap) automatikusan előállít egy áttekinthető
statisztikai munkafüzetet.

## Mit csinál

A bemeneti fájl feldolgozása során:

- kiszűri a **Törlés** és **hibás** rekordokat (színezve megtartja őket az `e-bev` lapon),
- a munkanapok alapján kibontja a foglalkoztatási napokat,
- a **jövőbeli hónapban** kezdődő bejelentéseket elmenti a következő hónapra
  (`memory.json`), és a korábban elmentetteket a megfelelő hónapban behúzza.

### Generált munkalapok

| Munkalap | Tartalom |
|---|---|
| `e-bev` | Az eredeti sorok, a törölt/hibás rekordok kiemelve |
| `Dátum Szerint` | Naponként kik dolgoztak |
| `Név Szerint` | Személyenként a ledolgozott napok (kitölthető adatlappal) |
| `ki hány napot dolgozott` | Havi bontású összesítés személyenként |

A kimenet a bemeneti fájl mellé kerül `<fájlnév>_statisztika.xlsx` néven.

## Használat

Húzd rá a bemeneti Excel-fájlt a `Statisztika_generálás.bat`-ra (vagy a lefordított
`.exe`-re).

Parancssorból:

```
python generate.py <bemeneti_fajl.xlsx>
```

## Követelmények

- Python 3
- [openpyxl](https://pypi.org/project/openpyxl/)

```
pip install openpyxl
```

## Buildelés (opcionális)

Önálló futtatható állomány létrehozása [PyInstaller](https://pyinstaller.org/)-rel:

```
pyinstaller --onefile --name Statisztika_generalas generate.py
```

## Megjegyzés

A személyes adatokat tartalmazó fájlok (`memory.json`, `*.xlsx`) és a lefordított
`.exe` a `.gitignore` révén nem kerülnek verziókövetésbe.
