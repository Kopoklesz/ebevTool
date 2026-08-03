# ebevTool

Excel-alapú statisztikagenerátor egyszerűsített foglalkoztatási (e-bev)
bejelentésekhez, GUI-val. A bemeneti Excel-fájlból automatikusan előállít egy
áttekinthető statisztikai munkafüzetet, cégenként elkülönített, Firebase-alapú.

## Támogatott bemeneti formátumok

A program a munkalap neve és a fejléc alapján **automatikusan felismeri**,
melyik formátumról van szó — nincs teendő a fájllal:

| Formátum | Munkalap | Fájlnév-minta |
|---|---|---|
| Új NAV-export | `Bejelentés adatok` | `Egyszerusitett_<adószám>_<riportazonosító>.xlsx` |
| Régi (archív) | `e-bev` | pl. `<Cégnév> JÚLIUS.xlsx` |

Az új NAV-exportban a **törölt** rekordokat a `Bejelentés jellege` (I) oszlop
`Új`-tól eltérő értéke, a **hibás** rekordokat pedig az
`Adatlap feldolgozottsági státusza` (K) oszlop `FELDOLGOZOTT`-tól eltérő értéke
jelzi. Mivel a NAV által használt pontos szöveg előre nem ismert, a program
minden eltérő értéket kiszűr, és a naplóba kiírja a ténylegesen talált
szöveget (pl. `Kiszűrve 1 törölt sor — "Visszavonás" (1 db)`).

Az új fájlnév nem tartalmaz cégnevet, ezért a cég felismerése a fájlnévben
szereplő **foglalkoztatói adószám** alapján történik.

## Mit csinál

- **GUI**: a fájl behúzható (drag&drop) vagy
  betallózható; az állapotok, hibák az ablakban jelennek meg.
- A fájlnévből automatikusan felismeri a **céget és a hónapot**;
  ismeretlen fájlnévnél popup kérdez rá, és a választ megjegyzi.
- **Fejléc sanity-check**: az oszlopfelismerés pozíció alapú, de a fejléc
  szerkezetét ellenőrzi, és figyelmeztet, ha eltér a várttól.
- Kiszűri a **törölt** és **hibás** rekordokat (színezve megtartja őket a
  forrásadat lapon), a munkanapok alapján kibontja a foglalkoztatási napokat.
- A **jövőbeli hónapban** kezdődő bejelentések a Firebase Firestore-ba
  kerülnek (cégenként elkülönítve, a személyes adatok titkosítva), és a
  megfelelő hónap feldolgozásakor automatikusan beszámítanak. A felhasznált
  (`consumed`) rekordok fél évig megmaradnak, így egy hónap **újrafeldolgozása**
  ugyanazt a kimenetet adja; utána automatikusan törlődnek.
- **Előzmények** nézet: mely fájlok lettek már feldolgozva (cégenként,
  év-hónap szerint; csak fájlnév + időpont, tartalom nélkül).
- **Várakozási sor / Böngésző** nézet: a Firestore-ban tárolt rekordok
  dekódolt böngészése és manuális törlése.
- **Személyek** nézet: TAJ-hoz kötött, titkosítva tárolt személyi adatok
  (szül. név, anyja neve, szül. hely/idő, lakcím). Ismeretlen TAJ-nál a
  feldolgozás rákérdez, és a `Név Szerint` lap adatlapjait ezekből tölti ki.
- **Helyi archívum**: a kimeneti fájl másolata automatikusan a
  `archívum/<Cég>/<év-hónap>/` mappába kerül, így később is visszakereshető.
- **Automatikus frissítés**: az alkalmazás induláskor csendben megnézi, van-e
  újabb kiadás a GitHubon, és a 🔄 **Frissítés** menüpontban egy kattintással
  letölthető és telepíthető (lásd lent).

### Generált munkalapok

| Munkalap                  | Tartalom                                                  |
|---------------------------|-----------------------------------------------------------|
| forrásadat lap            | Az eredeti sorok, a törölt/hibás rekordok kiemelve — a lap neve a bemenettel egyezik (`Bejelentés adatok` vagy `e-bev`) |
| `Dátum Szerint`           | Naponként kik dolgoztak                                   |
| `Név Szerint`             | Személyenként a ledolgozott napok, a Személyek nézetből kitöltött adatlappal |
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

## Frissítés / új verzió kiadása

Az alkalmazás a **GitHub Releases**-ből frissül. Induláskor csendben
ellenőrzi, van-e újabb kiadás (ha nincs net, nem szól semmit), és ha talál,
az oldalsávi 🔄 **Frissítés** gombra egy pötty (●) kerül. Az ablakban a
letöltés és a telepítés egy-egy kattintás — a program bezárul, lecseréli
magát, és újraindul az új verzióval.

> A repó publikus, így a frissítés token nélkül működik. Ha egyszer privátra
> váltana, a GitHub API 404-et adna, és az app „Nincs közzétett kiadás"
> hibát írna ki.

> **Az első átállás kézi.** A `2026.07.03` kiadásban még nincs benne a
> frissítés-funkció, ezért az a példány nem tudja magát lecserélni — azt az
> `.exe`-t egyszer kézzel kell kicserélni. Az onnantól kiadott verziók már
> automatikusan frissülnek.

Új verzió kiadásának lépései:

1. Írd át a verziószámot a [`version.py`](version.py) fájlban:
   ```python
   __version__ = '2026.09.01'
   ```
2. Commitold, majd tag-eld **ugyanazzal** a számmal, és told fel:
   ```
   git commit -am "2026.09.01"
   git tag 2026.09.01
   git push origin main --tags
   ```
3. Buildeld az `.exe`-t a fenti PyInstaller-paranccsal.
4. A GitHubon hozz létre egy release-t erre a tag-re, és **csatold hozzá a
   `dist/Statisztika_generalas.exe` fájlt**. A leírásba írt szöveg megjelenik
   a felhasználónál a frissítés ablakban.

A verziószám formátuma `ÉÉÉÉ.HH.NN`, egy napon belüli több kiadásnál
`ÉÉÉÉ.HH.NN.2`. A tag-en a `v` előtag és a záró pont is megengedett.

Ha egy kiadáshoz nincs `.exe` csatolva, az app ezt jelzi, és felkínálja a
kiadási oldal megnyitását — kézzel akkor is frissíthető. Forrásból futtatva
(`python gui.py`) az automatikus csere nem működik, ilyenkor `git pull` kell.

## Megjegyzés

Firebase-beállítások (`config.dat`) a felhasználó gépén titkosítva
tárolódnak — az adott Windows-fiókhoz és géphez kötve, más gépre
vagy fiókba átmásolva olvashatatlanok, és csak a Beállítások ablakon
keresztül szerkeszthetők. A Firestore-ban csak az ideiglenes várakozási sor
adatai tárolódnak, titkosítva és korlátozott (max. fél éves) megőrzéssel.