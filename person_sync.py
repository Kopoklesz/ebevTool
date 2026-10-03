"""Személyek azonosítása és a régi, többpéldányos tárolás átköltöztetése.

Egy embernek egyetlen adatlapja van (lásd FirebaseStore.load_people), benne
a cégek listájával. Ez a modul azt dönti el, hogy egy beérkező személy
(feldolgozott fájl, archívum, régi tárolási hely) melyik meglévő adatlappal
azonos, és hogyan olvad bele.

Óvatossági szabályok (valódi emberek adatairól van szó):
  * kitöltött mezőt soha nem írunk felül üressel, azonosítót nem veszítünk;
  * a programban felvitt adat erősebb az archívumból jöttnél ('archive_fields');
  * két eltérő, programban felvitt értéknél a meglévő marad (a másik a
    jelentésbe kerül), hiszen a beolvasás a frissebb adatlappal kezd;
  * csak TAJ alapján (adóazonosító nélkül) csak egyező névvel párosítunk —
    egy elírt TAJ így nem olvaszt össze két különböző embert.
"""
import hashlib
import unicodedata

import generate
from normalize import normalize_name, normalize_taj

DETAIL_FIELDS = ('szul_nev', 'anya_neve', 'szul_hely_ido', 'lakcim')
ID_FIELDS = ('adoazonosito', 'taj')
SYNC_FIELDS = ('nev',) + ID_FIELDS + DETAIL_FIELDS


# --- segédek ---

def _clean(value):
    return ' '.join(str(value or '').split())


def _ado(p):
    return generate.ado_key(p.get('adoazonosito'))


def _taj(p):
    """A TAJ számjegyei — a számjegy nélküli kitöltés ('-', 'n.a.') üresnek számít."""
    key = generate.taj_key(p.get('taj'))
    return key if key.isdigit() else ''


def name_key(name):
    """Összehasonlítható név: kisbetűs, ékezet és felesleges szóköz nélkül."""
    text = unicodedata.normalize('NFKD', normalize_name(name or '').lower())
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).split())


def same(field, a, b):
    """Azonos-e két érték; az azonosítóknál csak a számjegyek számítanak, a
    szövegeknél a kis- és nagybetű, illetve a szóközök sem."""
    if field == 'adoazonosito':
        return generate.ado_key(a) == generate.ado_key(b)
    if field == 'taj':
        return generate.taj_key(a) == generate.taj_key(b)
    return _clean(a).lower() == _clean(b).lower()


# --- azonosítás ---

def find_match(people, adoazonosito, taj, nev):
    """A meglévő adatlap azonosítója ehhez a személyhez, vagy None.

    Elsődleges az adóazonosító. Ha azzal nincs találat, a TAJ + név: csak
    olyan adatlapra, amelyiknek nincs (más) adóazonosítója — egy MÁS
    adóazonosítójú ember akkor sem ugyanaz, ha a TAJ-a egyezik.
    """
    ado = generate.ado_key(adoazonosito)
    if ado:
        for key, p in people.items():
            if _ado(p) == ado:
                return key
    t = generate.taj_key(taj)
    name = name_key(nev)
    if not t.isdigit() or not name:
        return None
    hits = [key for key, p in people.items()
            if _taj(p) == t and name_key(p.get('nev')) == name and not (ado and _ado(p))]
    return hits[0] if len(hits) == 1 else None


# --- átköltöztetés ---

def merge_into_people(people, company, person, doc_id_of):
    """Egy régi helyen tárolt adatlap beolvasztása a személyek közé.

    'people': {dok.azonosító: adatlap} — HELYBEN módosul.
    'company': a régi hely cége (None: a régi közös lista — tagság nélkül).
    'doc_id_of': a dokumentumazonosító képzése (FirebaseStore.person_doc_id).
    Visszatérés: (azonosító, ütközések [(név, mező, megtartott, eltérő)],
    régi azonosító ha az adatlap új azonosítót kapott, különben None).
    """
    incoming = {f: person.get(f, '') for f in SYNC_FIELDS}
    incoming_archive = set(person.get('archive_fields') or ())
    key = find_match(people, person.get('adoazonosito'), person.get('taj'), person.get('nev'))
    conflicts, old_key = [], None

    if key is None:
        key = doc_id_of(incoming)
        if key in people:
            # Azonos TAJ, de más név: két külön ember (valamelyik TAJ elírt).
            # Nem olvasztjuk össze, de el sem veszítjük: saját adatlapot kap
            # egy másik azonosítón; a TAJ javításáig szerkeszteni nem lehet.
            conflicts.append((incoming.get('nev', ''), 'személy', people[key].get('nev', ''),
                              'azonos TAJ, eltérő név — külön adatlapként megmaradt, '
                              'a TAJ-t javítani kell'))
            key = hashlib.sha256(f"dup:{key}:{name_key(incoming.get('nev'))}".encode('utf-8')).hexdigest()[:32]
        new = dict(incoming)
        new['taj'] = normalize_taj(new['taj']) if _taj(new) else new['taj']
        new['archive_fields'] = sorted(incoming_archive & set(DETAIL_FIELDS))
        new['companies'] = [company] if company else []
        for meta in ('_updated', '_created'):
            new[meta] = person.get(meta, '')
        people[key] = new
        return key, conflicts, None

    target = people[key]
    archive = set(target.get('archive_fields') or ())
    for field in SYNC_FIELDS:
        value = _clean(incoming.get(field))
        if not value:
            continue
        current = _clean(target.get(field))
        if not current:
            target[field] = incoming[field]
            if field in incoming_archive:
                archive.add(field)
        elif not same(field, current, value):
            if field in archive and field not in incoming_archive:
                target[field] = incoming[field]     # programos az archív helyett
                archive.discard(field)
            else:
                conflicts.append((target.get('nev', ''), field, target.get(field, ''), incoming[field]))
    target['archive_fields'] = sorted(archive & set(DETAIL_FIELDS))
    companies = set(target.get('companies') or ())
    if company:
        companies.add(company)
    target['companies'] = sorted(companies, key=str.lower)

    new_key = doc_id_of(target)
    if new_key != key:        # pl. a csak TAJ-os adatlap most kapott adóazonosítót
        people[new_key] = people.pop(key)
        old_key, key = key, new_key
    return key, conflicts, old_key
