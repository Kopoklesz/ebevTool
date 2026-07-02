# ebevTool

Excel-alapú statisztikagenerátor egyszerűsített foglalkoztatási (e-bev)
bejelentésekhez, GUI-val. A bemeneti Excel-fájlból (`e-bev` munkalap)
automatikusan előállít egy áttekinthető statisztikai munkafüzetet, cégenként
(Spring / Séd) elkülönített, Firebase-alapú várakozási sorral.

## Mit csinál

- **GUI** (Tkinter + tkinterdnd2): a fájl behúzható (drag&drop) vagy
  betallózható; az állapotok, hibák az ablakban jelennek meg.
- A fájlnévből (pl. `SPRING JÚNIUS.xlsx`, `SÉD JÚNIUS.xlsx`) automatikusan
  felismeri a **céget és a hónapot**; ismeretlen fájlnévnél popup kérdez rá,
  és a választ megjegyzi (alias) a jövőre.
- **Fejléc sanity-check**: az oszlopfelismerés pozíció alapú, de a fejléc
  szerkezetét ellenőrzi, és figyelmeztet, ha eltér a várttól.
- Kiszűri a **Törlés** és **hibás** rekordokat (színezve megtartja őket az
  `e-bev` lapon), a munkanapok alapján kibontja a foglalkoztatási napokat.
- A **jövőbeli hónapban** kezdődő bejelentések a Firebase Firestore-ba
  kerülnek (cégenként elkülönítve, a személyes adatok titkosítva), és a
  megfelelő hónap feldolgozásakor automatikusan beszámítanak. A felhasznált
  (`consumed`) rekordok fél évig megmaradnak, így egy hónap **újrafeldolgozása**
  ugyanazt a kimenetet adja; utána automatikusan törlődnek.
- **Előzmények** nézet: mely fájlok lettek már feldolgozva (cégenként,
  év-hónap szerint; csak fájlnév + időpont, tartalom nélkül).
- **Várakozási sor / Böngésző** nézet: a Firestore-ban tárolt rekordok
  dekódolt böngészése és manuális törlése.
- **Helyi archívum**: a kimeneti fájl másolata automatikusan a
  `archívum/<Cég>/<év-hónap>/` mappába kerül, így később is visszakereshető.

### Generált munkalapok

| Munkalap | Tartalom |
|---|---|
| `e-bev` | Az eredeti sorok, a törölt/hibás rekordok kiemelve |
| `Dátum Szerint` | Naponként kik dolgoztak |
| `Név Szerint` | Személyenként a ledolgozott napok (kitölthető adatlappal) |
| `ki hány napot dolgozott` | Havi bontású összesítés személyenként |

A kimenet a bemeneti fájl mellé kerül `<fájlnév>_statisztika.xlsx` néven,
plusz egy másolat az archívum mappába.

## Használat

Indítsd el a GUI-t, és húzd be / tallózd be az Excel fájlt:

```
python gui.py
```

Vagy húzd rá a fájlt a `Statisztika_generálás.bat`-ra — ez a GUI-t az
előre kitöltött fájllal indítja, és rögtön feldolgozza.

## Telepítés

- Python 3
- Függőségek:

```
pip install -r requirements.txt
```

- Firebase konfiguráció: másold le a `config.example.py`-t `config.py` néven
  és töltsd ki. Az egyszeri Firebase console-beállítás lépéseit a
  **[FIREBASE_SETUP.md](FIREBASE_SETUP.md)** írja le.

## Buildelés (opcionális)

Önálló futtatható állomány létrehozása [PyInstaller](https://pyinstaller.org/)-rel
(a kitöltött `config.py`-jal együtt fordul):

```
pyinstaller --onefile --windowed --collect-all tkinterdnd2 --name Statisztika_generalas gui.py
```

## Megjegyzés

A személyes adatokat tartalmazó fájlok (`*.xlsx`, `archívum/`), a
konfiguráció (`config.py`) és a lefordított `.exe` a `.gitignore` révén nem
kerülnek verziókövetésbe. A Firestore-ban csak az ideiglenes várakozási sor
adatai tárolódnak, titkosítva és korlátozott (max. fél éves) megőrzéssel.
