import hashlib
import json
import uuid
from datetime import datetime, timezone

import requests
from cryptography.fernet import Fernet

from generate import ado_key, entry_key, iso_to_serial, serial_to_iso, taj_key

IDENTITY_URL = 'https://identitytoolkit.googleapis.com/v1/accounts:signUp'
FIRESTORE_BASE = 'https://firestore.googleapis.com/v1'
TIMEOUT = 15

# Consumed rekordok megőrzési ideje hónapban
RETENTION_MONTHS = 6

# Firestore commit végpontonkénti írás-limit
BATCH_LIMIT = 500

# Egy Firestore dokumentum legfeljebb 1 MiB. A titkosított snapshot-payloadot
# ennél kisebb szeletekre vágjuk, hogy a többi mező és a Firestore overhead is
# biztosan elférjen mellette. A tipikus havi adag (50-200 fő) néhány tíz KB,
# tehát egyetlen szelet — a darabolás csak a szélsőséges eseteket fogja meg.
CHUNK_SIZE = 700_000


class FirebaseError(Exception):
    pass


class ConflictError(FirebaseError):
    """Egy másik gép közben módosította ugyanazt az adatot.

    A várakozási sor feldolgozása olvas -> dönt -> ír menetben zajlik. Ha a
    kettő között valaki más felhasználta ugyanazokat a rekordokat, a feltételes
    írás elbukik, és inkább hibát jelzünk, mint hogy csendben felülírjuk.
    """


def ym_today():
    now = datetime.now()
    return f"{now.year:04d}-{now.month:02d}"


def months_between(ym_from, ym_to):
    y1, m1 = int(ym_from[:4]), int(ym_from[5:7])
    y2, m2 = int(ym_to[:4]), int(ym_to[5:7])
    return (y2 * 12 + m2) - (y1 * 12 + m1)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _to_value(v):
    if isinstance(v, bool):
        return {'booleanValue': v}
    if isinstance(v, str):
        return {'stringValue': v}
    if isinstance(v, int):
        return {'integerValue': str(v)}
    if v is None:
        return {'nullValue': None}
    raise TypeError(f'Nem támogatott Firestore érték: {type(v)}')


def _from_value(val):
    if 'stringValue' in val:
        return val['stringValue']
    if 'integerValue' in val:
        return int(val['integerValue'])
    if 'booleanValue' in val:
        return val['booleanValue']
    return None


def _fields(d):
    return {k: _to_value(v) for k, v in d.items()}


def _parse_doc(doc):
    parsed = {k: _from_value(v) for k, v in doc.get('fields', {}).items()}
    parsed['_id'] = doc['name'].rsplit('/', 1)[1]
    # A dokumentum verziója: ezzel tudjuk feltételessé tenni a későbbi írást,
    # hogy egy közben történt módosítást ne írjunk felül észrevétlenül.
    parsed['_update_time'] = doc.get('updateTime')
    return parsed


def entry_doc_id(entry):
    return hashlib.sha256(entry_key(entry).encode('utf-8')).hexdigest()[:32]


def _is_precondition_failure(response):
    """Igaz, ha a válasz feltételes írás megsértését jelzi.

    A Firestore ilyenkor 400-at ad FAILED_PRECONDITION státusszal. A JSON
    szerkezetére nem támaszkodunk vakon: ha nem értelmezhető, a szövegre
    esünk vissza.
    """
    if response.status_code not in (400, 409):
        return False
    try:
        error = response.json().get('error', {})
        if error.get('status') == 'FAILED_PRECONDITION':
            return True
    except Exception:
        pass
    return 'FAILED_PRECONDITION' in (response.text or '')


class FirebaseStore:
    def __init__(self, api_key, project_id, fernet_key):
        self.api_key = api_key
        self.fernet = Fernet(fernet_key)
        self.doc_root = f'projects/{project_id}/databases/(default)/documents'
        self.doc_base = f'{FIRESTORE_BASE}/{self.doc_root}'
        self.id_token = None
        self.session = requests.Session()

    # --- kapcsolat ---

    def sign_in(self):
        if self.id_token:
            return
        try:
            r = self.session.post(f'{IDENTITY_URL}?key={self.api_key}',
                                  json={'returnSecureToken': True}, timeout=TIMEOUT)
            r.raise_for_status()
            self.id_token = r.json()['idToken']
        except Exception as e:
            raise FirebaseError(f'Firebase bejelentkezés sikertelen: {e}') from e

    def _request(self, method, path, *, params=None, json_body=None):
        self.sign_in()
        try:
            r = self.session.request(
                method, f'{self.doc_base}/{path}',
                headers={'Authorization': f'Bearer {self.id_token}'},
                params=params, json=json_body, timeout=TIMEOUT)
        except Exception as e:
            raise FirebaseError(f'Firestore hívás sikertelen: {e}') from e
        if r.status_code == 404:
            return None
        if not r.ok:
            raise FirebaseError(f'Firestore hiba ({r.status_code}): {r.text[:300]}')
        return r.json()

    def _list(self, collection_path):
        docs = []
        page_token = None
        while True:
            params = {'pageSize': 300}
            if page_token:
                params['pageToken'] = page_token
            resp = self._request('GET', collection_path, params=params)
            if not resp:
                break
            docs.extend(_parse_doc(d) for d in resp.get('documents', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        return docs

    def _batch_get(self, paths):
        if not paths:
            return {}
        self.sign_in()
        names = [f'{self.doc_root}/{p}' for p in paths]
        try:
            r = self.session.post(
                f'{self.doc_base}:batchGet',
                headers={'Authorization': f'Bearer {self.id_token}'},
                json={'documents': names}, timeout=TIMEOUT)
        except Exception as e:
            raise FirebaseError(f'Firestore batchGet hívás sikertelen: {e}') from e
        if not r.ok:
            raise FirebaseError(f'Firestore batchGet hiba ({r.status_code}): {r.text[:300]}')
        found = {}
        for item in r.json():
            doc = item.get('found')
            if doc:
                path = doc['name'].split('/documents/', 1)[1]
                found[path] = doc
        return found

    def _commit(self, writes):
        if not writes:
            return
        self.sign_in()
        for i in range(0, len(writes), BATCH_LIMIT):
            chunk = writes[i:i + BATCH_LIMIT]
            try:
                r = self.session.post(
                    f'{self.doc_base}:commit',
                    headers={'Authorization': f'Bearer {self.id_token}'},
                    json={'writes': chunk}, timeout=TIMEOUT)
            except Exception as e:
                raise FirebaseError(f'Firestore commit hívás sikertelen: {e}') from e
            if not r.ok:
                # A feltételes írás megsértését külön kezeljük: ilyenkor nem
                # hiba történt, hanem valaki más módosította közben az adatot.
                if _is_precondition_failure(r):
                    raise ConflictError(
                        'Egy másik gép közben módosította ugyanezeket a rekordokat.')
                raise FirebaseError(f'Firestore commit hiba ({r.status_code}): {r.text[:300]}')

    def _delete_write(self, path, if_unchanged_since=None):
        write = {'delete': f'{self.doc_root}/{path}'}
        if if_unchanged_since:
            write['currentDocument'] = {'updateTime': if_unchanged_since}
        return write

    def _update_write(self, path, fields, mask=None, if_unchanged_since=None):
        """Írás-művelet. Az 'if_unchanged_since' a dokumentum ismert verziója:
        ha megadjuk, a Firestore csak akkor írja felül, ha azóta nem változott."""
        write = {'update': {'name': f'{self.doc_root}/{path}', 'fields': _fields(fields)}}
        if mask is not None:
            write['updateMask'] = {'fieldPaths': mask}
        if if_unchanged_since:
            write['currentDocument'] = {'updateTime': if_unchanged_since}
        return write

    # --- titkosítás ---

    def _encrypt_entry(self, entry):
        payload = {
            'nev': entry['nev'],
            'adoazonosito': entry['adoazonosito'],
            'taj': entry['taj'],
            'start_date': serial_to_iso(entry['start_serial']),
            'munkanapok': entry['munkanapok'],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return self.fernet.encrypt(raw).decode('ascii')

    def _decrypt_entry(self, token):
        payload = json.loads(self.fernet.decrypt(token.encode('ascii')))
        return {
            'nev': payload['nev'],
            'adoazonosito': payload['adoazonosito'],
            'taj': payload['taj'],
            'start_serial': iso_to_serial(payload['start_date']),
            'munkanapok': payload['munkanapok'],
        }

    # --- memória (várakozási sor) ---

    def load_memory(self, company):
        records = []
        for doc in self._list(f'companies/{company}/memory'):
            try:
                entry = self._decrypt_entry(doc['payload'])
            except Exception:
                continue
            records.append({
                'id': doc['_id'],
                'status': doc.get('status', 'pending'),
                'consumed_in': doc.get('consumed_in'),
                # Melyik hónap feldolgozása tette a sorba (a régebbi
                # rekordoknál hiányzik) — ez kell az újrafeldolgozáskori
                # takarításhoz.
                'source_ym': doc.get('source_ym'),
                'entry': entry,
                # A beolvasáskori verzió: a feldolgozás végén ezzel tesszük
                # feltételessé az írást (lásd sync_processing).
                'version': doc.get('_update_time'),
            })
        return records

    def sync_processing(self, company, upsert_entries, consume_ids, ym, filename,
                        history_extra=None, history_id=None, stale_ids=(),
                        withdraw_ids=(), restore_ids=()):
        """A várakozási sor frissítése és egy előzmény-rekord létrehozása.

        A 'consume_ids' elemei lehetnek sima azonosítók, vagy (id, verzió)
        párok. Verzióval megadva az írás feltételes lesz: ha a rekordot a
        beolvasásunk óta más módosította (pl. már felhasználta), a commit
        ConflictError-ral elbukik ahelyett, hogy csendben felülírná.

        A 'history_extra' opcionális mezőkkel (pl. snapshot_id, created_by)
        egészíti ki az előzmény-dokumentumot. A 'history_id' megadható kívülről,
        hogy a hozzá tartozó snapshot ugyanazt az azonosítót kapja; enélkül
        újat generálunk. Visszaadja a használt azonosítót.

        A 'stale_ids' (id, verzió) párjai azok a várakozó rekordok, amiket egy
        korábbi feldolgozás tett a sorba ugyanebből a hónapból, de az új fájlban
        már nem szerepelnek — ezeket (szintén feltételesen) töröljük, különben
        a következő hónapban egy már nem létező bejelentés számítana be.
        """
        upsert_paths = [f'companies/{company}/memory/{entry_doc_id(e)}' for e in upsert_entries]
        existing = self._batch_get(upsert_paths)

        writes = []
        for entry, path in zip(upsert_entries, upsert_paths):
            if path in existing:
                writes.append(self._update_write(
                    path, {'payload': self._encrypt_entry(entry), 'source_ym': ym,
                           'updated_at': _now_iso()},
                    mask=['payload', 'source_ym', 'updated_at']))
            else:
                writes.append(self._update_write(path, {
                    'payload': self._encrypt_entry(entry), 'status': 'pending',
                    'consumed_in': None, 'source_ym': ym,
                    'created_at': _now_iso(), 'updated_at': _now_iso(),
                }))

        for doc_id, version in stale_ids:
            writes.append(self._delete_write(
                f'companies/{company}/memory/{doc_id}', if_unchanged_since=version))

        for item in consume_ids:
            doc_id, version = item if isinstance(item, (tuple, list)) else (item, None)
            writes.append(self._update_write(
                f'companies/{company}/memory/{doc_id}',
                {'status': 'consumed', 'consumed_in': ym, 'updated_at': _now_iso()},
                mask=['status', 'consumed_in', 'updated_at'],
                if_unchanged_since=version))

        # Visszavont (áthozott) rekordok: megjelölve, nem törölve — a hónap
        # újrafeldolgozásakor újra elbírálhatók. A visszaállítottak (a javított
        # fájl már nem vonja vissza) újra függőbe kerülnek.
        for doc_id, version in withdraw_ids:
            writes.append(self._update_write(
                f'companies/{company}/memory/{doc_id}',
                {'status': 'withdrawn', 'consumed_in': ym, 'updated_at': _now_iso()},
                mask=['status', 'consumed_in', 'updated_at'],
                if_unchanged_since=version))
        for doc_id, version in restore_ids:
            writes.append(self._update_write(
                f'companies/{company}/memory/{doc_id}',
                {'status': 'pending', 'consumed_in': None, 'updated_at': _now_iso()},
                mask=['status', 'consumed_in', 'updated_at'],
                if_unchanged_since=version))

        history_id = history_id or uuid.uuid4().hex[:24]
        history_fields = {'filename': filename, 'year_month': ym, 'processed_at': _now_iso()}
        history_fields.update(history_extra or {})
        writes.append(self._update_write(
            f'companies/{company}/history/{history_id}', history_fields))

        self._commit(writes)
        return history_id

    def delete_record(self, company, doc_id):
        self._request('DELETE', f'companies/{company}/memory/{doc_id}')

    def delete_all_memory(self, company):
        docs = self._list(f'companies/{company}/memory')
        self._commit([self._delete_write(f'companies/{company}/memory/{d["_id"]}') for d in docs])

    def delete_all_history(self, company):
        docs = self._list(f'companies/{company}/history')
        self._commit([self._delete_write(f'companies/{company}/history/{d["_id"]}') for d in docs])
        # A snapshotok az előzményekhez tartoznak — nélkülük árván maradnának.
        self.delete_all_snapshots(company)

    def delete_all_aliases(self, company):
        docs = self._list('company_aliases')
        matching = [d['_id'] for d in docs if d.get('company') == company]
        self._commit([self._delete_write(f'company_aliases/{doc_id}') for doc_id in matching])

    def cleanup_expired(self, company):
        today = ym_today()
        expired = [doc['_id'] for doc in self._list(f'companies/{company}/memory')
                  if doc.get('status') in ('consumed', 'withdrawn') and doc.get('consumed_in')
                  and months_between(doc['consumed_in'], today) > RETENTION_MONTHS]
        self._commit([self._delete_write(f'companies/{company}/memory/{doc_id}') for doc_id in expired])
        return len(expired)

    # --- előzmények ---

    def load_history(self, company):
        return self._list(f'companies/{company}/history')

    # --- snapshotok (a kimenet újragenerálásához szükséges tartalom) ---
    #
    # Nem a kész munkafüzetet tároljuk, hanem a bemeneteit: a 'generate_output'
    # determinisztikus, így letöltéskor ugyanaz a fájl állítható elő belőle.
    # A payload titkosítva megy fel, mert a teljes forrásadatot tartalmazza.

    def save_snapshot(self, company, snapshot_id, payload, meta):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        token = self.fernet.encrypt(raw).decode('ascii')
        chunks = [token[i:i + CHUNK_SIZE] for i in range(0, len(token), CHUNK_SIZE)] or ['']

        base = f'companies/{company}/snapshots/{snapshot_id}'
        fields = dict(meta)
        fields['chunk_count'] = len(chunks)
        fields['created_at'] = _now_iso()
        # Egy szeletnél a payload a fődokumentumban marad: a tipikus eset így
        # egyetlen dokumentum, egyetlen olvasás.
        fields['payload'] = chunks[0] if len(chunks) == 1 else None

        writes = [self._update_write(base, fields)]
        if len(chunks) > 1:
            for i, chunk in enumerate(chunks):
                writes.append(self._update_write(f'{base}/parts/{i}', {'payload': chunk}))
        self._commit(writes)

    def load_snapshot(self, company, snapshot_id):
        base = f'companies/{company}/snapshots/{snapshot_id}'
        doc = self._request('GET', base)
        if not doc:
            return None
        parsed = _parse_doc(doc)

        if (parsed.get('chunk_count') or 1) > 1:
            parts = self._list(f'{base}/parts')
            # A dokumentumnevek stringként rendeződnek, ezért számként rendezzük.
            parts.sort(key=lambda d: int(d['_id']))
            token = ''.join(p.get('payload') or '' for p in parts)
        else:
            token = parsed.get('payload') or ''
        if not token:
            return None

        payload = json.loads(self.fernet.decrypt(token.encode('ascii')))
        return {'payload': payload, 'meta': parsed}

    def delete_snapshot(self, company, snapshot_id):
        base = f'companies/{company}/snapshots/{snapshot_id}'
        writes = [self._delete_write(f'{base}/parts/{d["_id"]}')
                  for d in self._list(f'{base}/parts')]
        writes.append(self._delete_write(base))
        self._commit(writes)

    def delete_all_snapshots(self, company):
        for doc in self._list(f'companies/{company}/snapshots'):
            self.delete_snapshot(company, doc['_id'])

    # --- archívumból betöltött hónapok (munkanaplóhoz) ---
    #
    # A 2026.10.01 előtti feldolgozásoknak nincs snapshotja; a helyi
    # archívum kimeneteiből kinyert napokat hónaponként egy dokumentumban
    # tároljuk (titkosítva). Újbóli betöltés felülírja ugyanazt a hónapot.

    def save_worklog_import(self, company, ym, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        token = self.fernet.encrypt(raw).decode('ascii')
        if len(token) > CHUNK_SIZE:
            raise FirebaseError(f'A(z) {company} {ym} archív adata túl nagy a mentéshez.')
        self._commit([self._update_write(f'companies/{company}/worklog_imports/{ym}', {
            'payload': token, 'year_month': ym, 'imported_at': _now_iso(),
        })])

    def load_worklog_imports(self, company):
        imports = {}
        for doc in self._list(f'companies/{company}/worklog_imports'):
            try:
                imports[doc['_id']] = json.loads(self.fernet.decrypt(doc['payload'].encode('ascii')))
            except Exception:
                continue
        return imports

    def delete_all_worklog_imports(self, company):
        path = f'companies/{company}/worklog_imports'
        self._commit([self._delete_write(f'{path}/{d["_id"]}') for d in self._list(path)])

    # --- cég-aliasok ---

    def get_alias(self, token):
        doc = self._request('GET', f'company_aliases/{token}')
        return _parse_doc(doc).get('company') if doc else None

    def set_alias(self, token, company):
        self._request('PATCH', f'company_aliases/{token}',
                      json_body={'fields': _fields({'company': company})})

    def list_companies(self):
        return sorted({doc['company'] for doc in self._list('company_aliases')
                       if doc.get('company')})

    # --- személyek (adóazonosítóhoz kötött profil, titkosítva) ---

    PERSON_FIELDS = ('adoazonosito', 'taj', 'nev', 'szul_nev', 'anya_neve',
                     'szul_hely_ido', 'lakcim')

    def _encrypt_person(self, person):
        payload = {k: person.get(k, '') for k in self.PERSON_FIELDS}
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return self.fernet.encrypt(raw).decode('ascii')

    def _decrypt_person(self, token):
        payload = json.loads(self.fernet.decrypt(token.encode('ascii')))
        # a régi adatlapokon nincs 'adoazonosito' — ott üres marad
        return {k: payload.get(k, '') for k in self.PERSON_FIELDS}

    @staticmethod
    def person_doc_id(person):
        """A személy dokumentumazonosítója.

        Adóazonosítóval az abból képzett hash; enélkül (régi adatlap, vagy
        hiányzó adóazonosító) a korábbi, TAJ-ból képzett hash — így a régi
        dokumentumok azonosítója nem változik, amíg nem kapnak adóazonosítót.
        """
        ado = ado_key(person.get('adoazonosito'))
        source = f'ado:{ado}' if ado else taj_key(person.get('taj'))
        return hashlib.sha256(source.encode('utf-8')).hexdigest()[:32]

    @staticmethod
    def _persons_path(company):
        """A személyek gyűjteménye cégenként külön.

        A company=None a régi, minden cégre közös 'persons' gyűjtemény: ebből
        már nem írunk újat, csak olvassuk (átvételhez) és törölhető.
        """
        return f'companies/{company}/persons' if company else 'persons'

    def load_persons(self, company):
        """A cég személyei a dokumentumazonosítójuk szerint kulcsolva.

        Kereséshez a generate.find_person való (adóazonosító, tartalékként TAJ).
        """
        persons = {}
        for doc in self._list(self._persons_path(company)):
            try:
                persons[doc['_id']] = self._decrypt_person(doc['payload'])
            except Exception:
                continue
        return persons

    def save_person(self, company, person, old_doc_id=None):
        """Mentés; az 'old_doc_id' a személy korábbi dokumentuma.

        Ha az azonosító megváltozott (a régi, TAJ-alapú adatlap adóazonosítót
        kapott, vagy az adóazonosítót javították), a régi dokumentumot
        ugyanabban a commitban töröljük, hogy ne maradjon kettőzött adatlap.
        """
        path = self._persons_path(company)
        doc_id = self.person_doc_id(person)
        writes = [self._update_write(f'{path}/{doc_id}', {
            'payload': self._encrypt_person(person),
            'updated_at': _now_iso(),
        })]
        if old_doc_id and old_doc_id != doc_id:
            writes.append(self._delete_write(f'{path}/{old_doc_id}'))
        self._commit(writes)
        return doc_id

    def delete_person(self, company, doc_id):
        self._request('DELETE', f'{self._persons_path(company)}/{doc_id}')

    def delete_all_persons(self, company):
        path = self._persons_path(company)
        docs = self._list(path)
        self._commit([self._delete_write(f'{path}/{d["_id"]}') for d in docs])
