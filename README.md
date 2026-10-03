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
  év-hónap szerint), ki készítette, és a korábbi statisztikák **letöltése**
  bármelyik gépről (lásd lent).
- **Ütközésvédelem** két szinten, ha többen használják ugyanazt az adatbázist:
  - *előre*: ha egy cég adott hónapja már szerepel az előzményekben, a
    feldolgozás rákérdez, mielőtt új verziót készítene;
  - *írás közben*: a várakozási sor rekordjait a program csak akkor jelöli
    felhasználtnak, ha azok a beolvasás óta nem változtak. Ha közben valaki
    más feldolgozta ugyanazt, a mentés megszakad, és **a másik gép munkája
    ép marad** — semmi nem íródik felül csendben.
- **Várakozási sor / Böngésző** nézet: a Firestore-ban tárolt rekordok
  dekódolt böngészése és manuális törlése.
- **Személyek** nézet: **adóazonosítóhoz** kötött, titkosítva tárolt személyi
  adatok (szül. név, anyja neve, szül. hely/idő, lakcím). **Egy ember = egy
  adatlap**: aki több cégnél dolgozik, annak is egyetlen adatlapja van, a
  cégfülek ugyanazt mutatják, így egy módosítás mindenhol egyszerre látszik
  (a széles táblázat vízszintesen görgethető). A régi, cégenkénti és közös
  listák az első indításkor automatikusan egybeolvadnak (előtte mentés
  készül). A személyt az adóazonosító azonosítja, mert azt ritkábban
  írják el, mint a TAJ-számot: ha a TAJ eltér az adatlapon tárolttól, a
  program figyelmeztet, de nem kérdez újra. A TAJ csak tartalék (adóazonosító
  nélküli sornál, illetve a régi, csak TAJ-jal rögzített adatlapoknál — ezek
  a következő feldolgozáskor automatikusan megkapják az adóazonosítót). Az
  adóazonosító és a TAJ a szerkesztő ablakban javítható.
  **Kereső**: név (ékezet nélkül is), adóazonosító vagy TAJ alapján egyszerre
  keres az összes cég listájában, és megmutatja, mely cégeknél szerepel a
  személy; dupla kattintás a cég sorára az adott cég fülére ugrik. A találatok
  innen közvetlenül szerkeszthetők és törölhetők.
  Ismeretlen személynél a feldolgozás rákérdez (sorszámmal, pl.
  `2 / 5`), és a `Név Szerint` lap adatlapjait a cég listájából tölti ki. Az
  **Összes kihagyása** gombbal a hátralévő kérdések egy kattintással
  átugorhatók: a kihagyottak bekerülnek a statisztikába, csak az adatlapjuk
  marad üres, és legközelebb újra rákérdez. Ha a személylista nem érhető el
  (nincs kapcsolat), a program nem kérdez, és meglévő adatlapot sem ír felül.
  > A korábbi verziók egyetlen, minden cégre közös listát használtak. Ez
  > „Régi közös lista” fülként látszik; feldolgozáskor az ott már szereplő
  > személyek kérdés nélkül **átkerülnek** az adott cég listájába (a régi
  > listából törlődnek, így nem duplikálódnak). Ha a lista kiürül, a fül
  > eltűnik.
- **Egy személy több cégnél**: mindegyik cég listájában szerepel, de az
  adatai mindenhol ugyanazok — ha az egyik cégnél módosítod, a többinél is
  módosul. Ha feldolgozáskor egy cégnél még ismeretlen személy egy másik
  cégnél (vagy a régi listában) már szerepel, a program rákérdezés nélkül
  átveszi az adatait. **Ütközésnél a programban felvitt adat nyer** az
  archívumból betöltöttel szemben, azon belül a frissebb; hogy egy mező az
  archívumból jött-e, azt az adatlap megjegyzi.
- **Munkanapló** (Személyek → 📅 Munkanapló, vagy dupla katt a keresőben a
  személy sorára): személyenként, cégenként a ledolgozott napok száma, első és
  utolsó napja és havi bontásban a dátumok — Excelbe is menthető. Forrása a
  havi statisztikák felhőben mentett tartalma, cég-hónaponként **csak a
  legutolsó feldolgozásé**: ha egy javított fájlt töltenek fel újra (pl.
  kihúztak belőle valakit), a korábbi verzió nem számít. A 2026.10.01 előtti
  hónapok a **📥 Régi hónapok az archívumból** gombbal tölthetők be a helyi
  archívum kimeneteiből (ugyanarra a hónapra több fájlnál a legújabb számít;
  a várakozási sorhoz és az előzményekhez nem nyúl). Ugyanez a betöltés a
  kimenetekben szereplő **személyeket** is felveszi: mindenki bekerül annak
  a cégnek a listájába, ahol a statisztikában szerepelt (üres adatlappal is,
  ha a régi kimenetben nem volt személyi adat). Ha a személy már szerepel
  egy másik cégnél vagy a régi listában, az ott (a programban) rögzített
  adatai kerülnek át; az archívum csak az **üres** mezőket tölti ki (szül.
  név, anyja neve, szül. hely/idő, lakcím), a programban felvitt adatot nem
  írja felül — az eltéréseket a megerősítő ablak megszámolja. Személyenként
  a legújabb hónap adata számít.
- **TAJ-szám formátuma**: egységesen kötőjeles, `123-456-789` alakban jelenik
  meg és mentődik (táblázat, munkanapló, a statisztika `Név Szerint` lapja,
  új és szerkesztett adatlapok). A meglévő adatlapokat az **Adatok
  ellenőrzése** alakítja át. A keresés és az azonosítás a számjegyekre épül,
  így kötőjellel és anélkül is talál. A `Bejelentés adatok` lap a forrásfájl
  változatlan másolata, ott a TAJ az eredeti alakjában marad.
- **Visszavonások**: egy (adóazonosító — híján TAJ —, kezdő nap) bejelentés
  érvénytelen, ha utána ugyanerre visszavonás/törlés jött — akár ugyanabban a
  fájlban, akár egy későbbi hónap fájljában. A visszavonás utáni újbóli „Új”
  bejelentés érvényes (a visszavonás előtti nem, más munkanapszámmal sem). A
  feldolgozás ezt naplózza, a sorban álló áthozott rekordot „visszavonva”
  állapotúra teszi (nem törli, így a hónap javított fájllal újra
  feldolgozva visszaállítható), a munkanapló pedig a korábbi hónapból is
  kiveszi. A régi `e-bev` formátumban a „törlés” jelölés csak magát a sort
  jelöli töröltnek, más bejelentést nem von vissza.
- **Javított hónap újrafeldolgozása**: ha a következő hónapot már
  feldolgozták, a megváltozott áthúzódó bejelentések régi változata akkor is
  törlődik, és a program szól, hogy a későbbi hónapot is futtasd újra.
- **🧹 Adatok ellenőrzése** (Személyek oldal): az **Összefésülés** fül
  listázza azokat a személyeket, akik több helyen eltérő adattal szerepelnek,
  vagy a régi listában is megvannak (pl. egy korábbi archívum-betöltés
  duplikátumai), és előnézettel mutatja, mi lesz az egységes adat és honnan
  jön — jóváhagyás után minden cégnél egységes lesz, a régi listából pedig
  átkerül. Az **Egységesítés** fül a már rögzített adatlapokra
  egységesítési javaslatokat tesz (pl. `KOVÁCS ÉVA` → `Kovács Éva`,
  `1234 BUDAPEST, FŐ UTCA 1.` → `1234 Budapest, Fő utca 1.`, dátum
  `1990.01.05.` alakra) — csak a kijelöltek, megerősítés után kerülnek
  mentésre. Külön listázza a problémákat: hibás ellenőrzőszámú adóazonosító
  vagy TAJ, hiányzó adatok, ugyanaz az adóazonosító más névvel, ugyanaz a
  TAJ más adóazonosítóval. A hibás ellenőrzőszámot a feldolgozás naplója és
  a szerkesztő ablak is jelzi.
- **Hibás sorok jelzése**: ha egy sor kezdő dátuma vagy munkanapszáma nem
  értelmezhető, a program a feldolgozás előtt felsorolja ezeket (a dátum
  lehet szöveg `ÉÉÉÉ.HH.NN.` / `ÉÉÉÉ-HH-NN` alakban vagy Excel-dátumcella).
- **Javított fájl újrafeldolgozása**: ha egy hónapot újra feldolgozol, és a
  javított fájlból kikerült egy jövő havi bejelentés, a program a korábbi
  futás által elmentett várakozó rekordot törli (ez csak az e verzió óta
  mentett rekordokra működik).
- **Helyi archívum**: a kimeneti fájl másolata automatikusan a
  `Dokumentumok/ebevTool archívum/<Cég>/<év-hónap>/` mappába kerül, így később
  is visszakereshető (a hely a Beállításokban átírható).
- **Központi visszakeresés**: a statisztika *tartalma* (a forrássorok és a
  bejegyzések, titkosítva) a Firestore-ba is felkerül, így az Előzmények
  nézetből **bárki letöltheti**, aki hozzáfér az adatbázishoz — nem csak az,
  aki annak idején feldolgozta.
- **Automatikus frissítés**: az alkalmazás induláskor csendben megnézi, van-e
  újabb kiadás a GitHubon, és a 🔄 **Frissítés** menüpontban egy kattintással
  letölthető és telepíthető (lásd lent).

### Generált munkalapok

| Munkalap                  | Tartalom                                                  |
|---------------------------|-----------------------------------------------------------|
| forrásadat lap            | Az eredeti sorok, a törölt/hibás rekordok kiemelve — a lap neve a bemenettel egyezik (`Bejelentés adatok` vagy `e-bev`) |
| `Dátum Szerint`           | Naponként kik dolgoztak                                   |
| `Név Szerint`             | Személyenként a ledolgozott napok, a Személyek nézetből kitöltött adatlappal |
| `ki hány napot dolgozott` | Éves tábla (január–december): havi napszámok személyenként, az év korábbi hónapjaival együtt |

Az éves tábla korábbi hónapjai a cég mentett havi statisztikáiból jönnek;
ahol ilyen nincs, ott az archívumból betöltött kézi munkafüzetek
`ki hány napot dolgozott` lapjából (hónaponként a legújabb fájl számít).

A kimenet a bemeneti fájl mellé kerül `<fájlnév>_statisztika.xlsx` néven,
plusz egy másolat az archívum mappába.

## Korábbi statisztikák letöltése

Az **Előzmények** nézetben minden feldolgozott fájl mellett látszik, hogy ki és
mikor készítette, és hogy letölthető-e (`✓`). A sort kijelölve a
**⬇ Kijelölt letöltése** gomb újraépíti a statisztikát, tetszőleges helyre.

Nem a kész munkafüzetet tároljuk, hanem a **tartalmát**: a forrássorokat és a
bejegyzéseket. A statisztika előállítása determinisztikus, ezért ugyanabból a
tartalomból ugyanaz a fájl épül újra. Ennek több előnye van:

- töredék helyet foglal (egy tipikus hónap néhány tíz KB a több száz KB-os
  munkafüzet helyett), így simán elfér a Firestore-ban — nem kell fájltároló;
- a tartalom titkosítva utazik és tárolódik, ugyanazzal a kulccsal, mint a
  várakozási sor;
- ha a program egy későbbi verziója javít a statisztikán, a **régi hónapok is
  a javított formában** jönnek le.

Ez utóbbinak van egy következménye: ha a generálás időközben megváltozott, a
letöltött fájl eltérhet attól, amit annak idején beadtak. A program ezt észreveszi
(a mentett verziószám és tartalom-ujjlenyomat alapján), és jelzi a naplóban.
**Ha bitazonos megőrzésre van szükség, arra továbbra is a helyi archívum való** —
az érintetlenül megmarad.

A funkció bevezetése előtt feldolgozott hónapoknál a `Letölthető` oszlopban `—`
áll: azokhoz nincs mentett tartalom. Ha egy ilyen hónap központilag is kell, az
eredeti bemeneti fájlt újra fel kell dolgozni.

## Használat

(Build nélkül) Indítsd el a GUI-t, és húzd be / tallózd be az Excel fájlt:

```
python gui.py
```

Vagy húzd rá a fájlt a `Statisztika_generálás.bat`-ra — ez a GUI-t az
előre kitöltött fájllal indítja, és rögtön feldolgozza.

## Hol tárolja az adatait

Az `.exe` mellé **semmit nem ír** — így a program mappája tiszta marad, és
akkor is működik, ha csak olvasható helyre (pl. `Program Files`) telepítik.

| Mi | Hol |
|---|---|
| Beállítások (`config.dat`) | `%APPDATA%\ebevTool\` |
| Cégnév-gyorsítótár (`aliases.json`) | `%APPDATA%\ebevTool\` |
| Archívum (kész statisztikák) | `Dokumentumok\ebevTool archívum\` |
| Frissítés ideiglenes fájljai | a rendszer `TEMP` mappája |

A pontos útvonalak a **⚙ Beállítások** ablak alján is látszanak, a mappákat
onnan egy kattintással meg lehet nyitni.

> **Frissítéskor a régi fájlok automatikusan átkerülnek.** A korábbi verziók az
> `.exe` mellé írtak; az első indításkor a `config.dat` és az `aliases.json`
> átköltözik az új helyre, beállítások elvesztése nélkül.
>
> Az **archívum mappát nem mozgatjuk** (nagy lehet): ha az `.exe` mellett már
> létezik `archívum` mappa, a program továbbra is azt használja, így a meglévő
> gyűjtemény nem szakad ketté. Ha át szeretnéd helyezni, mozgasd át kézzel, és
> add meg az új helyet a Beállításokban.

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

### Ha a frissítés nem sikerül

- **„Nincs írásjog"**: az `.exe` olyan mappában van (tipikusan
  `Program Files`), ahová a felhasználó nem írhat. A program ezt a letöltés
  *előtt* jelzi. Megoldás: indítsd rendszergazdaként, vagy tedd az `.exe`-t
  olyan mappába, ahová írhatsz.
- **„Nincs Python a gépen" vagy hasonló furcsa hiba indításkor**: ez nem a
  program hibája — a `Statisztika_generálás.bat` nem találja az `.exe`-t
  (pl. mert egy korábbi csere félbemaradt), és a Windows próbálja másként
  értelmezni a fájlt. A `.bat` ezt ma már felismeri és megnevezi a hiányzó
  fájlt. Megoldás: töltsd le újra a legfrissebb kiadást.
- **Ékezetes felhasználónév**: a csere rövid (8.3-as) útvonalakkal dolgozik,
  ezért ékezetes mappanévvel is működik. Ha egy gépen ki van kapcsolva a
  8.3-as névgenerálás *és* ékezetes az útvonal, a csere elbukhat — ilyenkor a
  kézi csere segít.
- **„Failed to load Python DLL” a `2026.08.03.2`-ről való frissítés után**:
  egyszeri, ártalmatlan hibaablak. A régi verzió frissítője a saját
  ideiglenes mappájára mutató PyInstaller-változókat adta tovább az
  újraindított programnak. A csere ilyenkor már megtörtént: OK, majd indítsd
  el újra a programot. A `2026.10.01.2` óta a frissítő tiszta környezettel
  indítja az új verziót, így ez többé nem fordul elő.
- **Ékezetes mappa a `2026.08.03.2`-es verzióval**: annak a frissítője ékezetes
  útvonalon nem tudja lecserélni magát (a program bezárul, a régi verzió
  marad). Ilyenkor egyszer kézzel kell kicserélni az `.exe`-t; onnantól az
  automatikus frissítés ékezetes mappában is működik.

A cserét egy ideiglenes batch végzi, ami megvárja, míg a futó példány kilép.
Ha a csere nem sikerül, **az eredeti `.exe` visszaáll** — a program nem marad
működésképtelen állapotban.

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

Telepítés előtt a program megnézi, fut-e még másik ablaka: ha igen, kéri a
bezárásukat (a csere ettől még működne, de azokban a régi verzió futna
tovább). A frissítés minden lépése — a cserét végző batch-é is — a
`%APPDATA%\ebevTool\update.log` naplóba kerül (a legutóbbi 500 sor), így ha
valakinél elakad, abból kiderül, mi történt.

## Megjegyzés

Firebase-beállítások (`config.dat`, a `%APPDATA%\ebevTool\` mappában) a
felhasználó gépén titkosítva tárolódnak — az adott Windows-fiókhoz és géphez
kötve, más gépre vagy fiókba átmásolva olvashatatlanok, és csak a Beállítások
ablakon keresztül szerkeszthetők.

A Firestore-ban a **várakozási sor** (titkosítva, max. fél éves megőrzéssel), a
**személyi adatlapok** (titkosítva, személyenként egy, adóazonosítóhoz kötve) és a feldolgozott hónapok
**statisztika-tartalma** (titkosítva) tárolódik. Mindhármat ugyanaz a Fernet
kulcs védi — ha ez elvész, az adatok visszafejthetetlenné válnak.

> **Figyelem:** a Firebase-bejelentkezés anonim, ezért aki hozzáfér a Web API
> kulcshoz *és* a Fernet kulcshoz, az minden cég adatát eléri. Ha több ügyfél
> adatait kezelitek, érdemes valódi felhasználókezelésre váltani.