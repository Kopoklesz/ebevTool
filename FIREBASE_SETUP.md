# Firebase beállítás — egyszeri, kézi lépések

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
    // a régi, minden cégre közös személylista (csak átvételhez és törléshez)
    match /persons/{taj} {
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
3. Generálj egy Fernet titkosítási kulcsot:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   **Fontos:** ezt a kulcsot őrizd meg biztonságos helyen — ha elveszik, a
   Firestore-ban tárolt (titkosított) rekordok visszafejthetetlenné válnak.
4. A három értéket (Web API Key, Project ID, Fernet kulcs) az alkalmazás
   futtatásakor az oldalsáv **⚙ Beállítások** ablakában add meg (az ablakban
   egy **❓ Hogyan találom meg ezeket az adatokat?** gomb is elérhető, ami
   ugyanezt a lépéssort mutatja, laikusabban megfogalmazva).

A Web API key a Firebase dokumentáció szerint nem titok (a security rules és a
kliensoldali titkosítás védi az adatokat), a Fernet kulcs viszont igen — ezt
soha ne oszd meg, és ne is kelljen: a Beállítások ablak sosem tárolja
olvasható formában (lásd lent).
