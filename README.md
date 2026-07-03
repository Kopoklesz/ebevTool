# ebevTool

Excel-alapú statisztikagenerátor egyszerűsített foglalkoztatási (e-bev)
bejelentésekhez, GUI-val. A bemeneti Excel-fájlból (`e-bev` munkalap)
automatikusan előállít egy áttekinthető statisztikai munkafüzetet, cégenként
elkülönített, Firebase-alapú.

## Mit csinál

- **GUI**: a fájl behúzható (drag&drop) vagy
  betallózható; az állapotok, hibák az ablakban jelennek meg.
- A fájlnévből automatikusan felismeri a **céget és a hónapot**;
  ismeretlen fájlnévnél popup kérdez rá, és a választ megjegyzi.
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

| Munkalap                  | Tartalom                                                  |
|---------------------------|-----------------------------------------------------------|
| `e-bev`                   | Az eredeti sorok, a törölt/hibás rekordok kiemelve        |
| `Dátum Szerint`           | Naponként kik dolgoztak                                   |
| `Név Szerint`             | Személyenként a ledolgozott napok (kitölthető adatlappal) |
| `ki hány napot dolgozott` | Havi bontású összesítés személyenként                     |

A kimenet a bemeneti fájl mellé kerül `<fájlnév>_statisztika.xlsx` néven,
plusz egy másolat az archívum mappába.

## Használat

(Build nélkül) Indítsd el a GUI-t, és húzd be / tallózd be az Excel fájlt:

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

- Firebase konfiguráció: az alkalmazás oldalsávjában a **⚙ Beállítások**
  ablakban add meg (nem kell fájlt szerkeszteni). Az egyszeri Firebase
  console-beállítás lépéseit a **[FIREBASE_SETUP.md](FIREBASE_SETUP.md)**
  írja le, illetve ugyanez elérhető a Beállítások ablak
  **❓ Hogyan találom meg ezeket az adatokat?** gombja mögött is.

## Buildelés

Önálló futtatható állomány létrehozása [PyInstaller](https://pyinstaller.org/)-rel.
A build **nem tartalmaz semmilyen konkrét Firebase-adatot** — ugyanaz az
`.exe` bárkinek kiadható, a Firebase-adatokat mindenki a saját gépén, a
Beállítások ablakban adja meg (lásd lent):

```
pyinstaller --onefile --windowed --collect-all tkinterdnd2 --name Statisztika_generalas gui.py
```

## Megjegyzés

Firebase-beállítások (`config.dat`) a felhasználó gépén titkosítva
tárolódnak — az adott Windows-fiókhoz és géphez kötve, más gépre
vagy fiókba átmásolva olvashatatlanok, és csak a Beállítások ablakon
keresztül szerkeszthetők. A Firestore-ban csak az ideiglenes várakozási sor
adatai tárolódnak, titkosítva és korlátozott (max. fél éves) megőrzéssel.