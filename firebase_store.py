import hashlib
import json
from datetime import datetime, timezone

import requests
from cryptography.fernet import Fernet

from generate import entry_key, iso_to_serial, serial_to_iso

IDENTITY_URL = 'https://identitytoolkit.googleapis.com/v1/accounts:signUp'
FIRESTORE_BASE = 'https://firestore.googleapis.com/v1'
TIMEOUT = 15

# Consumed rekordok megőrzési ideje hónapban (fél év)
RETENTION_MONTHS = 6


class FirebaseError(Exception):
    pass


def ym_today():
    now = datetime.now()
    return f"{now.year:04d}-{now.month:02d}"


def months_between(ym_from, ym_to):
    """Hónapok száma ym_from-tól ym_to-ig (pozitív, ha ym_to későbbi)."""
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
    return parsed


def entry_doc_id(entry):
    """Determinisztikus dokumentum-azonosító a dedup kulcsból (upsert-hez)."""
    return hashlib.sha256(entry_key(entry).encode('utf-8')).hexdigest()[:32]


class FirebaseStore:
    def __init__(self, api_key, project_id, fernet_key):
        self.api_key = api_key
        self.fernet = Fernet(fernet_key)
        self.doc_base = (f'{FIRESTORE_BASE}/projects/{project_id}'
                         f'/databases/(default)/documents')
        self.id_token = None

    # --- kapcsolat ---

    def sign_in(self):
        """Anonim bejelentkezés; FirebaseError-t dob, ha nem sikerül."""
        if self.id_token:
            return
        try:
            r = requests.post(f'{IDENTITY_URL}?key={self.api_key}',
                              json={'returnSecureToken': True}, timeout=TIMEOUT)
            r.raise_for_status()
            self.id_token = r.json()['idToken']
        except Exception as e:
            raise FirebaseError(f'Firebase bejelentkezés sikertelen: {e}') from e

    def _request(self, method, path, *, params=None, json_body=None):
        self.sign_in()
        try:
            r = requests.request(
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
        """Az összes tárolt rekord dekódolva:
        [{'id', 'status', 'consumed_in', 'entry': {...}}, ...]"""
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
                'entry': entry,
            })
        return records

    def upsert_pending(self, company, entry):
        """Upsert a dedup kulcs alapján; meglévő rekord státuszát nem írja felül."""
        doc_id = entry_doc_id(entry)
        path = f'companies/{company}/memory/{doc_id}'
        existing = self._request('GET', path)
        if existing is None:
            self._request('PATCH', path, json_body={'fields': _fields({
                'payload': self._encrypt_entry(entry),
                'status': 'pending',
                'consumed_in': None,
                'created_at': _now_iso(),
                'updated_at': _now_iso(),
            })})
        else:
            self._request('PATCH', path,
                          params={'updateMask.fieldPaths': ['payload', 'updated_at']},
                          json_body={'fields': _fields({
                              'payload': self._encrypt_entry(entry),
                              'updated_at': _now_iso(),
                          })})

    def mark_consumed(self, company, doc_id, ym):
        self._request(
            'PATCH', f'companies/{company}/memory/{doc_id}',
            params={'updateMask.fieldPaths': ['status', 'consumed_in', 'updated_at']},
            json_body={'fields': _fields({
                'status': 'consumed',
                'consumed_in': ym,
                'updated_at': _now_iso(),
            })})

    def delete_record(self, company, doc_id):
        self._request('DELETE', f'companies/{company}/memory/{doc_id}')

    def cleanup_expired(self, company):
        """A megőrzési időn túli (RETENTION_MONTHS-nál régebben consumed)
        rekordok végleges törlése. Visszaadja a törölt rekordok számát."""
        today = ym_today()
        deleted = 0
        for doc in self._list(f'companies/{company}/memory'):
            if doc.get('status') != 'consumed' or not doc.get('consumed_in'):
                continue
            if months_between(doc['consumed_in'], today) > RETENTION_MONTHS:
                self.delete_record(company, doc['_id'])
                deleted += 1
        return deleted

    # --- előzmények ---

    def add_history(self, company, filename, ym):
        self._request('POST', f'companies/{company}/history',
                      json_body={'fields': _fields({
                          'filename': filename,
                          'year_month': ym,
                          'processed_at': _now_iso(),
                      })})

    def load_history(self, company):
        return self._list(f'companies/{company}/history')

    # --- cég-aliasok ---

    def get_alias(self, token):
        doc = self._request('GET', f'company_aliases/{token}')
        return _parse_doc(doc).get('company') if doc else None

    def set_alias(self, token, company):
        self._request('PATCH', f'company_aliases/{token}',
                      json_body={'fields': _fields({'company': company})})

    def list_companies(self):
        """Az eddig megismert cégek egyedi, rendezett listája."""
        return sorted({doc['company'] for doc in self._list('company_aliases')
                       if doc.get('company')})
