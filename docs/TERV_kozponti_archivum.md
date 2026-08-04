# Terv — Kész dokumentumok központi elérhetősége (snapshot-alapú)

**Állapot:** elfogadott terv, implementáció folyamatban
**Cél:** a legenerált statisztika bárki számára visszakereshető és letölthető
legyen, aki hozzáfér az adatbázishoz — **anélkül, hogy a fájlt magát tárolnánk**.
Mellékhatásként figyelmeztetés arra, ha egy cég+hónapot már feldolgoztak.

## 1. Miért kell

Ma az archiválás kizárólag lokális (`gui.py` `_process_file_async`): a kimenet
a `default_archive_dir()` alá másolódik. Minden gépen külön archívum él, senki
nem látja a másikét. A Firestore `history` kollekciójában csak a `filename`
string van — a kimenet tartalma sehol nincs központilag.

Következmények: ha a feldolgozó kolléga nincs bent, a múlt havi kimenet nem
érhető el; két gépen két, egymásról nem tudó archívum keletkezik; nincs jelzés
arról, ha ugyanazt a cég+hónapot ketten feldolgozták.

## 2. A megközelítés: tartalom, nem dokumentum

**Nem a kész XLSX-et töltjük fel, hanem a bemeneteit, és letöltéskor
újragenerálunk.**

Ez azért működik, mert a `generate.generate_output` **determinisztikus**: tiszta
függvény, ugyanabból a `header` / `data_rows` / `entries` / `persons` négyesből
mindig ugyanazt a munkafüzetet állítja elő. Nincs benne véletlen és nincs
időbélyeg a tartalomban.

Ez nem új feltevés: a README ma is kimondja, hogy a `consumed` rekordok fél évig
megmaradnak, "így egy hónap újrafeldolgozása ugyanazt a kimenetet adja".

### Mért méretek (Fernet-titkosítás után)

| Bejegyzés | Nyers | Titkosítva |
|---|---|---|
| 50 | 6,2 KB | 8,3 KB |
| 200 | 24,6 KB | 32,9 KB |
| 1000 | 123 KB | 164 KB |
| 5000 | 615 KB | 820 KB |

Egy bejegyzés ~248 bájt titkosítva. Egy tipikus havi adag (50–200 fő) **8–33 KB**
— a Firestore 1 MiB-os dokumentumlimitjének közelébe se ér.

A kész XLSX ehhez képest több száz KB–pár MB, mert az openpyxl beleteszi a teljes
zip-elt XML-szerkezetet, a `PatternFill`/`Font` stílusokat és az `autofit`
oszlopszélességeket. **A méret nagy része formázás, nem adat.**

### Ebből következően

**Nem kell Firebase Storage**, és nem kell más adatbázis. A meglévő Firestore
elég. Nincs külön konzolos aktiválás, nincs Blaze-csomag kérdés, nincs
bucket-név találgatás, nincs új REST-réteg.

További előnyök a fájltárolással szemben:

- **az adat böngészhető marad** (a Storage-ban egy blob átlátszatlan);
- **verziófüggetlen**: ha javítasz a `generate_output`-on, a régi hónapok is az
  új, javított formában jönnek le.

## 3. Adatmodell

### 3.1 Snapshot dokumentum

Új alkollekció a meglévő szerkezetben:

```
companies/{company}/snapshots/{snapshot_id}
```

`snapshot_id` = a hozzá tartozó `history` dokumentum azonosítója. A
`sync_processing` ma is `uuid.uuid4().hex[:24]`-et generál minden feldolgozáshoz,
így **két párhuzamos feltöltés két külön snapshotot hoz létre** — egyik sem írja
felül a másikat, a verziózás ingyen jön.

Mezők:

| mező | típus | tartalom |
|---|---|---|
| `payload` | string | Fernettel titkosított JSON (lásd 3.2), 1 chunk esetén |
| `chunk_count` | int | hány darabban van a payload (1 = nincs darabolva) |
| `year_month` | string | `2026-08` |
| `filename` | string | az eredeti bemeneti fájl neve |
| `app_version` | string | `version.__version__` a generálás idején |
| `sha256` | string | a **generált XLSX** hash-e (lásd 6.2) |
| `entry_count` | int | bejegyzések száma — listázáshoz, visszafejtés nélkül |
| `row_count` | int | forrássorok száma |
| `created_at` | string | ISO időbélyeg |
| `created_by` | string | felhasználó/gép (lásd 3.4) |

### 3.2 A payload tartalma

```json
{
  "v": 1,
  "header": [...],
  "data_rows": [[...], ...],
  "entries": [{"nev":..., "adoazonosito":..., "taj":...,
               "start_date":"2026-08-03", "munkanapok":5}, ...],
  "fmt": "nav2026"
}
```

- `v`: séma-verzió, hogy később bővíthető legyen visszafelé kompatibilisen.
- `fmt`: az `InputFormat.key` — a rekonstrukciónál a `FORMATS`-ból keressük
  vissza, mert a `generate_output` a `fmt`-ből veszi az `output_sheet` nevet és
  a törlés/hiba színezés szabályait.
- `entries`: a `serial` helyett ISO dátum, ahogy a `_encrypt_entry` is teszi —
  így a payload önleíró és nem függ az EPOCH-tól.
- **`persons` nincs benne**: a `persons` kollekcióban már tárolva van TAJ
  szerint, felesleges duplikálni. A rekonstrukciónál onnan töltjük.

`data_rows` tárolása szándékos: enélkül a `Dátum Szerint` / `Név Szerint` /
`ki hány napot dolgozott` lapok tökéletesek lennének, de a **forrásadat lap**
(a színezett törölt/hibás sorokkal) hiányozna. Ez ~3-4-szeres méret az
`entries`-hez képest, még mindig bőven a limit alatt.

**Nem szerializálható cellák:** a `data_rows` tartalmazhat `datetime` értéket
(az openpyxl dátumcellát ad vissza). A JSON ezt nem tudja, ezért a mentésnél
`datetime` → `{"__dt__": "ISO"}` alakra alakítjuk, visszatöltéskor vissza.
Minden más nem-primitív típus stringgé alakul.

### 3.3 Chunkolás

Bár a tipikus méret 8–33 KB, egy szélsőséges hónap (több ezer sor) átlépheti az
1 MiB-os dokumentumlimitet. Ezért a titkosított payload **szeletelve** tárolódik:

```
companies/{company}/snapshots/{snapshot_id}            -> chunk_count, metaadat
companies/{company}/snapshots/{snapshot_id}/parts/{i}  -> payload szelet
```

Egy szelet mérete `CHUNK_SIZE = 700_000` karakter, ami biztonságos tartalék az
1 MiB-hoz képest (a többi mező és a Firestore overhead miatt). 1 chunknál a
payload közvetlenül a fődokumentumban marad, alkollekció nélkül — a tipikus eset
tehát **egyetlen dokumentum, egyetlen olvasás**.

### 3.4 History dokumentum bővítése

A `sync_processing` által írt history dokumentum két új mezőt kap:

| mező | típus | tartalom |
|---|---|---|
| `snapshot_id` | string / null | a snapshot azonosítója, vagy `null` ha nem sikerült |
| `created_by` | string | a feldolgozó gép azonosítója |

Mindkettő opcionális olvasáskor: a **régi history rekordokban nincsenek**, ezért
a megjelenítés `.get()`-tel dolgozik, és a hiányzó `snapshot_id` azt jelenti,
hogy ehhez a bejegyzéshez nincs letölthető tartalom.

A `created_by` a Windows-felhasználónév + gépnév (`getpass.getuser()` /
`platform.node()`, hibatűrően). **Nem hitelesített adat** — a bejelentkezés
anonim —, csak arra jó, hogy a figyelmeztetés emberi nevet mutasson.

## 4. Titkosítás

A payload a meglévő Fernet kulccsal titkosítva megy fel, a `_encrypt_entry`
mintájára. Ez nem opcionális: a snapshot tartalmazza a teljes forrásadatot, a
`Név Szerint` lap pedig anyja nevét, lakcímet, TAJ-t és születési adatokat
állít elő belőle.

Ha a Fernet kulcs elvész, a snapshotok is visszafejthetetlenné válnak — ugyanaz
a kockázat, ami ma a memória-rekordokra igaz.

## 5. Kód-változások

### 5.1 `firebase_store.py`

Új konstans: `CHUNK_SIZE = 700_000`, `SNAPSHOT_SCHEMA = 1`.

Új metódusok:

| metódus | leírás |
|---|---|
| `save_snapshot(company, snapshot_id, payload_dict, meta)` | JSON → Fernet → chunkolás → `_commit` |
| `load_snapshot(company, snapshot_id)` | chunkok összefűzése → visszafejtés → dict |
| `list_snapshots(company)` | metaadatok payload nélkül (listázáshoz) |
| `delete_snapshot(company, snapshot_id)` | fődokumentum + parts törlése |

A `sync_processing` új, opcionális `history_extra=None` paramétert kap, amivel a
`snapshot_id` és `created_by` bekerül a history dokumentumba. Alapértelmezett
`None` esetén a mostani viselkedés változatlan.

A `delete_all_history` kiegészül a snapshotok törlésével, hogy ne maradjanak
árva dokumentumok.

### 5.2 `generate.py`

Két új tiszta függvény, a `generate_output` mellé:

- `entries_to_payload(entries)` / `entries_from_payload(list)` — serial ↔ ISO
  átalakítás (a `_encrypt_entry` mintájára, de listára).
- `rows_to_json(rows)` / `rows_from_json(rows)` — `datetime` kezelés (3.2).
- `format_by_key(key)` — az `InputFormat` visszakeresése a `FORMATS`-ból.

Ezek `generate.py`-ba valók, mert a szerializáció a formátum ismeretét igényli,
és így a `firebase_store` nem függ az openpyxl-től.

### 5.3 `gui.py` — mentés a feldolgozás végén

A `_process_file_async`-ben, a `sync_processing` **elé**, hogy a `snapshot_id`
egyetlen history íráshoz átadható legyen:

1. `generate_output` — a fájl elkészül (változatlan);
2. lokális archiválás (változatlan, **megmarad** offline tartaléknak);
3. **új:** snapshot mentése + a generált fájl SHA256-ja;
4. `sync_processing(..., history_extra=...)`.

**Hibakezelés:** a snapshot mentésének hibája nem bukhatja meg a feldolgozást.
A `try/except` a lokális archiválás mintáját követi: a hiba a naplóba kerül, a
`snapshot_id` `None` marad. A felhasználónak elkészült a fájlja — ez a fontos.

### 5.4 `gui.py` — letöltés az Előzményekből

A `show_history` / `_on_history_loaded` bővítése:

- a sorok `iid`-je a history `doc_id` (a `_fill_queue_tree` már ma is így
  használja), az oszlopok közé bekerül a **Készítette**;
- a lap aljára gombsor a `show_queue` mintájára: **⬇ Kijelölt letöltése** és
  **🔄 Frissítés**;
- letöltés: `filedialog.asksaveasfilename` → `run_async` → `load_snapshot` →
  `generate_output` a snapshot tartalmából + a **jelenlegi** `persons`-ból;
- siker esetén `log_link`-kel kattintható út a naplóba;
- ha a sorhoz nincs `snapshot_id` (régi rekord), a gomb ezt jelzi.

**Verzió-eltérés jelzése:** ha a snapshot `app_version` mezője eltér a mostani
`version.__version__`-tól, a letöltés után a napló jelzi. Ha a `sha256` is
eltér az újragenerált fájlétól, az azt jelenti, hogy a generálás azóta
megváltozott — ez figyelmeztetést érdemel, nem hibát (lásd 6.2).

### 5.5 `gui.py` — "már feldolgozták" figyelmeztetés

**Eldöntött viselkedés: figyelmeztet, de engedi.**

A `_process_file_async` háttérszálon fut, ott **nem szabad** dialógust nyitni
(tkinter nem szálbiztos). Ezért az ellenőrzés a meglévő aszinkron mintát követi,
ahogy a személyek betöltése (`_load_persons_work` →
`_on_persons_loaded_for_file` → `_process_file_check_persons`):

1. a személyek betöltésével **egy menetben** lekérjük a cég history rekordjait;
2. a főszálon futó callback: ha van az adott `ym`-re már feldolgozott rekord,
   popup:

```
⚠  Ezt a hónapot már feldolgozták

Cég:     Példa Kft.
Hónap:   2026-08
Készült: 2026-08-03 14:22  (kuti / IRODA-PC)

[ Mégis feldolgozom ]  [ Megszakítás ]
```

3. "Mégis feldolgozom" → folytatódik, **új verzióként** (külön `snapshot_id`,
   a régi érintetlen);
4. "Megszakítás" → leáll, naplóbejegyzéssel.

Ez **nem tranzakciós védelem** — ha ketten pontosan egyszerre indítanak,
mindkettő átcsúszhat. A gyakorlati esetet (valaki ma, valaki holnap ugyanazt a
hónapot) viszont lefedi.

## 6. Amit ez a terv tudatosan NEM old meg

### 6.1 Hozzáférés-szabályozás

A bejelentkezés továbbra is anonim (`accounts:signUp`), tehát aki megszerzi az
API kulcsot és a Fernet kulcsot, minden céghez hozzáfér. A snapshot a teljes
forrásadatot tartalmazza, tehát ez **nagyobb tét, mint a mostani rekordoknál**.
A valódi felhasználókezelés külön feladat.

A Firestore security rules nem szorul módosításra: a `companies/{company}/**`
szabály az új `snapshots` alkollekcióra automatikusan érvényes.

### 6.2 A rekonstrukció nem bitazonos garancia

Ha később megváltozik a `generate_output` szerkezete, a régi hónapok letöltése
*más* fájlt ad, mint amit annak idején beadtak. Ez a verziófüggetlenség
árnyoldala.

Kezelés: a snapshot tárolja az `app_version`-t és az eredeti fájl `sha256`-ját,
így a letöltésnél **kimutatható**, ha az újragenerált fájl eltér az eredetitől.
Ha bitazonos megőrzésre van szükség (pl. hatósági bizonyítás), az **továbbra is
a lokális archívum** feladata — az megmarad.

### 6.3 A várakozási sor ütközése

A `load_memory` → döntés → `sync_processing` ciklus továbbra is védtelen; az
5.5 pont figyelmeztetés, nem zárolás. Külön kör.

### 6.4 A személyek cache elavulása

Az a külön, egyszerűbb javítás — nem része ennek a tervnek.

## 7. Migráció

A régi, lokális archívum XLSX-ei **nem migrálhatók** snapshottá: a kész fájlból
nem nyerhető vissza megbízhatóan az eredeti `entries` szerkezet (a
`munkanapok` már napokra van bontva, a `data_rows` pedig a forrásformátumtól
függ). A korábban tervezett "régi archívum feltöltése" gomb ezért **kimarad**.

Helyette: a régi hónapok a lokális archívumban maradnak, az újak automatikusan
felkerülnek. Ha egy régi hónap kell központilag, azt **újra kell feldolgozni**
az eredeti bemeneti fájlból — amit a `consumed` rekordok fél éves megőrzése
támogat is.

## 8. Megvalósítási sorrend

1. `generate.py` szerializációs segédek (5.2)
2. `firebase_store.py` snapshot réteg (5.1)
3. Mentés a feldolgozás végén (5.3)
4. Letöltés az Előzményekből (5.4)
5. "Már feldolgozták" figyelmeztetés (5.5)
6. Dokumentáció (README)
