# Firebase beállítás — egyszeri, kézi lépések

Ez az útmutató a projekt gazdájának szól: ezeket a lépéseket **egyszer**,
a build előtt kell elvégezni a [Firebase console](https://console.firebase.google.com/)-on.

## 1. Firebase projekt létrehozása

1. Nyisd meg a Firebase console-t, jelentkezz be Google-fiókkal.
2. **Add project** → adj nevet (pl. `ebevtool`) → a Google Analytics nem szükséges,
   kikapcsolható → **Create project**.

## 2. Firestore adatbázis létrehozása

1. Bal oldali menü: **Build → Firestore Database** → **Create database**.
2. Mód: **Native mode**.
3. Régió: válassz EU-s régiót (pl. `europe-west3` / Frankfurt).
4. Induló szabályok: mindegy, mert a következő lépésben felülírjuk.

## 3. Anonim bejelentkezés engedélyezése

1. **Build → Authentication** → **Get started**.
2. **Sign-in method** fül → **Anonymous** → engedélyezés (**Enable**) → mentés.

## 4. Firestore Security Rules beállítása

**Firestore Database → Rules** fül, illeszd be az alábbit, majd **Publish**:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /companies/{company}/{document=**} {
      allow read, write: if request.auth != null;
    }
    match /company_aliases/{token} {
      allow read, write: if request.auth != null;
    }
  }
}
```

Ez azt jelenti: csak bejelentkezett (akár anonim) kliens fér hozzá, és csak
az app által használt útvonalakhoz — minden más útvonal zárva marad.

## 5. Web API key kimásolása és az app konfigurálása

1. Fogaskerék ikon → **Project settings** → **General** fül.
2. Másold ki a **Web API Key** és a **Project ID** értékét.
3. A repóban másold le a `config.example.py`-t `config.py` néven, és írd be a
   két értéket.
4. Generálj egy Fernet titkosítási kulcsot, és azt is írd be a `config.py`-ba:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   **Fontos:** ezt a kulcsot őrizd meg biztonságos helyen — ha elveszik, a
   Firestore-ban tárolt (titkosított) rekordok visszafejthetetlenné válnak.

A Web API key a Firebase dokumentáció szerint nem titok (a security rules és a
kliensoldali titkosítás védi az adatokat), de a `config.py` így sem kerül
verziókezelésbe.

## Terjesztési modell

- A fenti beállítás és a `config.py` kitöltése után az alkalmazás önálló
  `.exe`-vé fordítható (PyInstaller, lásd README.md) — a konfiguráció
  belefordul a binárisba.
- Aki megkapja és futtatja az `.exe`-t: **nem kell semmilyen Firebase-fiókot
  regisztrálnia vagy beállítania**, nem kell adatbázissal bajlódnia. A program
  a háttérben, automatikusan (anonim bejelentkezéssel) kommunikál a
  Firestore-ral. A munkafolyamat a megszokott: futtatja az `.exe`-t, behúzza
  vagy betallózza az Excel fájlt, igény esetén megnézi az Előzmények /
  Várakozási sor nézeteket.
- Mivel mindenki ugyanazt a Firestore-adatbázist éri el, több gépen vagy
  felhasználónál futtatva is közösen látható és konzisztens az Előzmények és a
  Várakozási sor.
- Minden az ingyenes **Spark csomagon** belül marad (Firestore + Anonymous
  Auth ingyenes kvótával; a havi néhány feldolgozás messze belefér).
