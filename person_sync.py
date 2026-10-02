"""Személyek összehangolása a cégek és a régi közös lista között.

Egy ember több cégnél is dolgozhat: mindegyik cég listájában szerepel, és az
adatai mindenhol ugyanazok — ha az egyiknél módosítják, a módosítás a
többinél is megjelenik. A régi, minden cégre közös listából egy személy
átkerül a cég listájába (onnan törlődik), így nem duplikálódik.

Óvatossági szabályok (valódi emberek adatairól van szó):
  * kitöltött mezőt automatikusan soha nem írunk felül üressel, és
    azonosítót (adóazonosító, TAJ) soha nem veszítünk el;
  * szerkesztéskor csak a ténylegesen módosított mezők mennek át a többi
    cégre;
  * automatikusan csak az egyértelmű esetet döntjük el: üres mező kitöltése,
    illetve a programban felvitt érték az ARCHÍVUMBÓL származó ellen;
  * ha két, programban felvitt érték tér el, azt a felhasználó dönti el (az
    Adatok ellenőrzése → Összefésülés fülön); addig mindenhol marad a saját.

Archív eredetű egy mező, ha az adatlap 'archive_fields' listája tartalmazza,
vagy — a jelölés előtti (2026.10.02.2-es) betöltésnél — ha az adatlapot
maga az archívum-betöltés HOZTA LÉTRE (a létrehozás ideje egy betöltés
idejére esik). Az akkor csak kiegészített adatlapok nem számítanak archívnak:
azokon a felhasználó saját adata is lehet.
"""
import unicodedata
from datetime import datetime, timedelta

import generate
from normalize import normalize_name, normalize_taj

DETAIL_FIELDS = ('szul_nev', 'anya_neve', 'szul_hely_ido', 'lakcim')
ID_FIELDS = ('adoazonosito', 'taj')
# az összehangolt mezők (minden cégnél ugyanaz)
SYNC_FIELDS = ('nev',) + ID_FIELDS + DETAIL_FIELDS

# a régi közös lista "cég"-kulcsa (így hívja a store is)
LEGACY = None

# A korábbi archívum-betöltés előbb a hónapokat írta, utána egyenként a
# személyeket — nagy archívumnál ez percekig tarthatott.
_IMPORT_BEFORE = timedelta(minutes=2)
_IMPORT_AFTER = timedelta(minutes=10)


# --- segédek ---

def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _clean(value):
    return ' '.join(str(value or '').split())


def _ado(p):
    return generate.ado_key(p.get('adoazonosito'))


def _taj(p):
    """A TAJ számjegyei — a számjegy nélküli kitöltés ('-', 'n.a.') üresnek számít."""
    key = generate.taj_key(p.get('taj'))
    return key if key.isdigit() else ''


def _name_key(name):
    text = unicodedata.normalize('NFKD', normalize_name(name or '').lower())
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).split())


def _same(field, a, b):
    """Azonos-e két érték; az azonosítóknál csak a számjegyek számítanak, a
    szövegeknél a kis- és nagybetű, illetve a szóközök sem (a formázás az
    Egységesítés dolga)."""
    if field == 'adoazonosito':
        return generate.ado_key(a) == generate.ado_key(b)
    if field == 'taj':
        return generate.taj_key(a) == generate.taj_key(b)
    return _clean(a).lower() == _clean(b).lower()


def public(person):
    """Az adatlap mentendő része (belső kulcsok nélkül)."""
    out = {k: person.get(k, '') for k in SYNC_FIELDS}
    if 'archive_fields' in person:
        out['archive_fields'] = sorted(set(person.get('archive_fields') or ()))
    return out


# --- archív eredet ---

def archive_windows(imports_by_company):
    """Az összes archívum-betöltés időpontja (a load_worklog_imports
    '_imported_at' mezőiből, minden cégre együtt — a betöltés minden cég
    hónapjait előbb írta, a személyeket utána)."""
    times = []
    for imports in imports_by_company.values():
        for item in (imports or {}).values():
            t = _parse_time(item.get('_imported_at'))
            if t:
                times.append(t)
    return times


def _created_by_import(company, person, windows):
    if company is LEGACY or 'archive_fields' in person:
        return False
    created = _parse_time(person.get('_created'))
    return bool(created) and any(t - _IMPORT_BEFORE <= created <= t + _IMPORT_AFTER
                                 for t in windows)


def is_archive_value(kind, company, person, field, windows):
    if kind == 'archive':
        return True
    if field not in DETAIL_FIELDS:
        return False
    if 'archive_fields' in person:
        return field in (person.get('archive_fields') or ())
    return _created_by_import(company, person, windows)


# --- csoportosítás ---

def build_groups(data, archive=None):
    """A személyek csoportjai: ugyanaz az ember minden helyről.

    'data': {cég vagy LEGACY: {dok.azonosító: adatlap}}
    'archive': {cég: [archív rekord {'nev','adoazonosito','taj','details'}]}
    Visszatérés: {csoportkulcs: [tag]}, tag = (fajta, cég, dok.azonosító,
    adatlap); fajta 'doc' (tárolt adatlap) vagy 'archive' (archív rekord).

    A kulcs az adóazonosító. Egy csak TAJ-os adatlap akkor kerül egy
    adóazonosítós személyhez, ha pontosan egy ilyen személynek van ez a
    TAJ-a ÉS a név is egyezik — egy elírt TAJ így nem olvaszt össze két
    különböző embert. Minden más csak TAJ-os adatlap a TAJ szerint csoportosul.
    """
    members = []
    for company, persons in data.items():
        for doc_id, p in persons.items():
            members.append(('doc', company, doc_id, p))
    for company, records in (archive or {}).items():
        for rec in records:
            p = {'nev': rec.get('nev', ''), 'adoazonosito': rec.get('adoazonosito', ''),
                 'taj': rec.get('taj', ''), **(rec.get('details') or {})}
            members.append(('archive', company, None, p))

    # TAJ -> {adóazonosító: nevek}
    by_taj = {}
    for _, _, _, p in members:
        if _ado(p) and _taj(p):
            by_taj.setdefault(_taj(p), {}).setdefault(_ado(p), set()).add(_name_key(p.get('nev')))

    groups = {}
    for m in members:
        p = m[3]
        if _ado(p):
            key = 'ado:' + _ado(p)
        elif _taj(p):
            holders = by_taj.get(_taj(p), {})
            name = _name_key(p.get('nev'))
            if len(holders) == 1 and name and name in next(iter(holders.values())):
                key = 'ado:' + next(iter(holders))
            else:
                key = 'taj:' + _taj(p)
        else:
            continue  # azonosító nélkül nem párosítható
        groups.setdefault(key, []).append(m)
    return groups


def find_group(groups, adoazonosito, taj, nev=''):
    """A személy csoportkulcsa adóazonosító, ennek híján TAJ + név alapján."""
    ado = generate.ado_key(adoazonosito)
    if ado and 'ado:' + ado in groups:
        return 'ado:' + ado
    t = generate.taj_key(taj)
    if not t.isdigit():
        return None
    name = _name_key(nev)
    if not ado and 'taj:' + t in groups:
        return 'taj:' + t
    # TAJ + név: csak adóazonosító nélküli (régi) adatlapokra — egy MÁS
    # adóazonosítójú ember akkor sem ugyanaz, ha a TAJ-a egyezik
    hits = [k for k, ms in groups.items()
            if any(_taj(m[3]) == t and _name_key(m[3].get('nev')) == name
                   and (not ado or not _ado(m[3])) for m in ms)]
    return hits[0] if len(hits) == 1 and name else None


def _group_containing(groups, company, doc_id):
    for key, ms in groups.items():
        if any(m[0] == 'doc' and m[1] == company and m[2] == doc_id for m in ms):
            return key
    return None


# --- egységes adat ---

def unify(members, windows):
    """Mezőnként az egységes érték.

    Visszatérés: (resolved, conflicts)
      resolved: {mező: (érték, forrás leírása, archív-e)} — az egyértelmű mezők
      conflicts: {mező: [(érték, forrás leírása, utolsó módosítás)]} — több,
                 egymástól eltérő, programban felvitt érték: a felhasználó dönt.
    """
    resolved, conflicts = {}, {}
    for field in SYNC_FIELDS:
        program, archive = [], []
        for kind, company, doc_id, p in members:
            value = _clean(p.get(field))
            if not value or (field == 'taj' and not _taj(p)):
                continue
            where = 'régi közös lista' if company is LEGACY else company
            item = (value, where, p.get('_updated') or '', kind)
            (archive if is_archive_value(kind, company, p, field, windows) else program).append(item)

        def distinct(items):
            out = []
            for item in sorted(items, key=lambda i: i[2], reverse=True):   # frissebb előre
                for d in out:
                    if _same(field, d[0], item[0]):
                        d[1].append(item[1])
                        break
                else:
                    out.append([item[0], [item[1]], item[2], item[3]])
            return out

        prog = distinct(program)
        if len(prog) == 1:
            value, wheres = prog[0][0], prog[0][1]
            resolved[field] = (value, 'program (' + ', '.join(sorted(set(wheres), key=str)) + ')', False)
        elif len(prog) > 1:
            conflicts[field] = [(v, 'program (' + ', '.join(sorted(set(w), key=str)) + ')', t)
                                for v, w, t, _ in prog]
        else:
            arch = distinct(archive)
            if arch:
                # tárolt (archív jelölésű) adatlap előbb, mint a friss archív rekord
                arch.sort(key=lambda a: a[3] == 'archive')
                value, wheres = arch[0][0], arch[0][1]
                resolved[field] = (value, 'archívum (' + ', '.join(sorted(set(wheres), key=str)) + ')', True)
        if field == 'taj' and field in resolved:
            v, d, a = resolved[field]
            resolved[field] = (normalize_taj(v), d, a)
    return resolved, conflicts


# --- tervek ---

def plan_group(members, windows, extra_companies=(), choices=None):
    """Egy csoport összehangolása.

    A személynek minden olyan cégnél adatlapja lesz, ahol már van, valamint
    az 'extra_companies' (pl. ahol az archívumban szerepel) cégeknél. A régi
    közös lista példánya törlődik, ha legalább egy cégnél megvan.

    'choices': {mező: érték} — a felhasználó döntése ütköző mezőkre.
    Ütköző, eldöntetlen mezőnél mindenhol marad a saját érték; új adatlapra a
    legfrissebb programos érték kerül (onnan nincs mit elveszíteni).

    Visszatérés: {'name', 'resolved', 'conflicts', 'writes': [(cég, adatlap,
    régi dok.azonosító vagy None)], 'deletes': [(LEGACY, dok.azonosító)],
    'changes': [(cég, mező, régi, új, forrás)]}.
    """
    choices = choices or {}
    resolved, conflicts = unify(members, windows)
    final = {f: v[0] for f, v in resolved.items()}
    final_archive = {f for f, v in resolved.items() if v[2] and f in DETAIL_FIELDS}
    sources = {f: v[1] for f, v in resolved.items()}
    for field, value in choices.items():
        if field in conflicts:
            final[field] = value
            sources[field] = 'a te döntésed'

    docs = [m for m in members if m[0] == 'doc']
    companies = {m[1] for m in docs if m[1] is not LEGACY}
    companies |= {m[1] for m in members if m[0] == 'archive'}
    companies |= set(extra_companies)

    writes, changes = [], []
    for company in sorted(companies, key=str.lower):
        own = [m for m in docs if m[1] == company]
        if not own:
            person = {f: final.get(f, '') for f in SYNC_FIELDS}
            for field, options in conflicts.items():
                if field not in final:
                    person[field] = options[0][0]   # a legfrissebb programos
            person['archive_fields'] = sorted(final_archive)
            writes.append((company, person, None))
            changes.append((company, '*', '', 'új adatlap', ''))
            continue
        for kind, _, doc_id, p in own:
            person = public(p)
            archive_fields = {f for f in DETAIL_FIELDS
                              if is_archive_value(kind, company, p, f, windows)}
            changed = False
            for field in SYNC_FIELDS:
                value = final.get(field)
                if not value or _same(field, p.get(field), value):
                    continue          # üres értékkel nem írunk felül semmit
                person[field] = value
                changed = True
                changes.append((company, field, p.get(field, ''), value, sources.get(field, '')))
                if field in DETAIL_FIELDS:
                    if field in final_archive and field not in choices:
                        archive_fields.add(field)
                    else:
                        archive_fields.discard(field)
            person['archive_fields'] = sorted(archive_fields)
            if changed:
                writes.append((company, person, doc_id))
    deletes = []
    if companies:
        for _, company, doc_id, p in docs:
            if company is LEGACY:
                deletes.append((LEGACY, doc_id))
                changes.append((LEGACY, '*', 'régi közös lista', 'átkerül a cég(ek) listájába', ''))
    name = final.get('nev') or (conflicts.get('nev') or [('',)])[0][0]
    return {'name': name, 'resolved': resolved, 'conflicts': conflicts, 'writes': writes,
            'deletes': deletes, 'changes': changes, 'members': members}


def plan_all(data, windows):
    """Összefésülési terv (az 'Adatok ellenőrzése' ablakhoz): azok a
    személyek, akiknél van mit tenni, vagy döntés kell."""
    plans = []
    for key, members in build_groups(data).items():
        plan = plan_group(members, windows)
        conflicting = {f: o for f, o in plan['conflicts'].items()
                       if len({m[1] for m in members if m[0] == 'doc'}) > 1 or len(o) > 1}
        if plan['writes'] or plan['deletes'] or conflicting:
            plan['key'] = key
            plans.append(plan)
    return sorted(plans, key=lambda p: _name_key(p['name']))


def plan_archive(data, archive, windows):
    """Archívum-betöltés: csak azok a személyek, akik az archívumban szerepelnek.

    A cégnél adatlapja lesz (ha még nincs), a programban felvitt adat az
    erősebb, a régi listából átkerül; az archívum csak az üres mezőket tölti.
    Visszatérés: (tervek, eltérések száma) — eltérés: az archív érték más,
    mint a megtartott (programban felvitt) érték.
    """
    plans, conflicts = [], 0
    for key, members in build_groups(data, archive).items():
        if not any(m[0] == 'archive' for m in members):
            continue
        plan = plan_group(members, windows)
        for kind, company, _, p in members:
            if kind != 'archive':
                continue
            for f in DETAIL_FIELDS:
                kept = plan['resolved'].get(f, ('',))[0]
                if _clean(p.get(f)) and kept and not _same(f, p.get(f), kept):
                    conflicts += 1
        if plan['writes'] or plan['deletes']:
            plan['key'] = key
            plans.append(plan)
    return plans, conflicts


def plan_edit(data, company, old_doc_id, updated):
    """Egy adatlap szerkesztése (vagy feldolgozáskori kiegészítése).

    Csak a ténylegesen MÓDOSÍTOTT mezők mennek át a személy többi cégnél lévő
    adatlapjára; üressé tett azonosítót nem viszünk át. Ha a régi közös lista
    adatlapját szerkesztik, és a személy már szerepel valamelyik cégnél, a
    módosítás a cég(ek)hez kerül, a régi listás példány törlődik.

    Visszatérés: {'writes', 'deletes', 'collision'} — 'collision': (cég, név),
    ha az új adóazonosító egy MÁSIK személyé (ilyenkor nem mentünk).
    """
    old = data.get(company, {}).get(old_doc_id, {})
    changed = {f: updated.get(f, '') for f in SYNC_FIELDS
               if not _same(f, old.get(f), updated.get(f))}
    for f in ID_FIELDS:
        if f in changed and not _clean(changed[f]):
            del changed[f]           # azonosítót nem ürítünk más cégnél

    groups = build_groups(data)
    key = _group_containing(groups, company, old_doc_id)
    members = [m for m in groups.get(key, []) if not (m[1] == company and m[2] == old_doc_id)]

    if 'adoazonosito' in changed:
        new_key = 'ado:' + generate.ado_key(changed['adoazonosito'])
        if new_key in groups and new_key != key:
            other = groups[new_key][0]
            return {'writes': [], 'deletes': [],
                    'collision': ('régi közös lista' if other[1] is LEGACY else other[1],
                                  other[3].get('nev', ''))}

    target = public(updated)
    target['archive_fields'] = sorted(set(updated.get('archive_fields') or ()) - set(changed))
    writes, deletes = [], []
    company_members = [m for m in members if m[1] is not LEGACY]
    if company is LEGACY and company_members:
        deletes.append((LEGACY, old_doc_id))       # a cég(ek)hez kerül
    else:
        writes.append((company, target, old_doc_id))
    for _, c, doc_id, p in members:
        if c is LEGACY:
            if company is not LEGACY or company_members:
                deletes.append((LEGACY, doc_id))
            continue
        person = public(p)
        person.update(changed)
        person['archive_fields'] = sorted(set(p.get('archive_fields') or ()) - set(changed))
        if changed:
            writes.append((c, person, doc_id))
    return {'writes': writes, 'deletes': deletes, 'collision': None}


def adopt(data, company, adoazonosito, taj, nev, windows):
    """Feldolgozáskor egy, a cégnél még ismeretlen személy: ha más cégnél
    vagy a régi listában megvan, az adatait vesszük át kérdés nélkül
    (ütköző mezőnél a legfrissebb programos értéket — az ütközés az
    Összefésülésben látszik). Visszatérés: (adatlap vagy None,
    [(LEGACY, dok.azonosító)])."""
    others = {c: ps for c, ps in data.items() if c != company}
    groups = build_groups(others)
    key = find_group(groups, adoazonosito, taj, nev)
    if key is None:
        return None, []
    members = groups[key]
    resolved, conflicts = unify(members, windows)
    person = {f: resolved.get(f, ('',))[0] for f in SYNC_FIELDS}
    for field, options in conflicts.items():
        person[field] = options[0][0]
    person['archive_fields'] = sorted(f for f, v in resolved.items() if v[2] and f in DETAIL_FIELDS)
    if not generate.ado_key(person.get('adoazonosito')):
        person['adoazonosito'] = adoazonosito
    legacy = [(LEGACY, m[2]) for m in members if m[1] is LEGACY]
    return person, legacy
