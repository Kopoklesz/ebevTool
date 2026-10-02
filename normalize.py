"""A tárolt személyadatok egyszeri egységesítése (nagybetűsítés, formátumok).

A felhasználók kézzel, következetlenül gépelték be az adatokat (CSUPA NAGY,
csupa kisbetű, vegyesen). Az itt lévő függvények egységes alakra hozzák őket:
szavanként nagy kezdőbetű, a többi kicsi.

Alapelvek:
  * tiszta függvények – nincs mellékhatás, a bemenetet nem módosítjuk,
  * determinisztikus és IDEMPOTENS – kétszer futtatva ugyanaz, mint egyszer,
  * óvatos – ha nem biztos a szabály, a szöveg változatlan marad
    (pl. a vegyes kis-nagybetűs szavak, mint a 'McDonald').

A None bemenetet üres szövegként kezeljük.
"""

import re
from datetime import date

# --- közös segédek ---

_WS_RE = re.compile(r'\s+')
# Római szám 1–39 között (kerület, emelet): pl. 'II', 'XI', 'XXIII'.
_ROMAN_RE = re.compile(r'^(?=[IVX])X{0,3}(IX|IV|V?I{0,3})$')
# Betűsorozat, opcionális záró ponttal (rövidítések: 'u.', 'krt.').
_RUN_RE = re.compile(r'[^\W\d_]+\.?')
# Szó eleji / végi írásjelek, amelyek nem részei a szónak.
_LEAD_RE = re.compile(r'^[(\["„\']*')
_TRAIL_RE = re.compile(r'[)\]"”\',;:]*$')


def _text(value):
    """None → '', minden más szöveggé alakítva."""
    if value is None:
        return ''
    return str(value)


def _collapse(text):
    """Szélek levágása, belső szóközök egyetlen szóközre."""
    return _WS_RE.sub(' ', _text(text)).strip()


def _fix_commas(text):
    """Vessző előtt nincs szóköz, utána pontosan egy (a záró vesszőnél nincs)."""
    def repl(m):
        start, end = m.span()
        before = text[start - 1] if start > 0 else ''
        after = text[end] if end < len(text) else ''
        # '12,5' jellegű tizedes vesszőt nem bántunk
        if before.isdigit() and after.isdigit() and m.group(0) == ',':
            return ','
        return ',' if end == len(text) else ', '
    return re.sub(r'\s*,\s*', repl, text).strip()


def _is_uniform(word):
    """Igaz, ha a szó betűi mind nagyok vagy mind kicsik (van legalább egy betű)."""
    letters = ''.join(c for c in word if c.isalpha())
    return bool(letters) and (letters.isupper() or letters.islower())


def _capitalize(part):
    """Első betű nagy, a többi kicsi – csak egységes (csupa nagy/kis) szóra.

    A vegyes szavakat ('McDonald') változatlanul hagyjuk.
    """
    if not _is_uniform(part):
        return part
    for i, c in enumerate(part):
        if c.isalpha():
            return part[:i] + c.upper() + part[i + 1:].lower()
    return part


def _capitalize_hyphenated(word):
    """Kötőjeles szónál minden tagot külön nagybetűsítünk (Nagy-Kovács)."""
    return '-'.join(_capitalize(p) for p in word.split('-'))


def _roman(core):
    """A római számot (pont nélkül) adja vissza nagybetűvel, vagy None-t.

    Ponttal ('xi.') kis- és nagybetűsen is felismerjük; pont nélkül csak a
    már eleve nagybetűs alakot ('XI') – a kisbetűs 'vi' lehet más is.
    """
    if core.endswith('.'):
        body = core[:-1]
        if body and _ROMAN_RE.match(body.upper()) and _is_uniform(body):
            return body.upper() + '.'
        return None
    if core and core.isupper() and _ROMAN_RE.match(core):
        return core
    return None


def _split_token(token):
    """Szó felbontása: (nyitó írásjelek, mag, záró írásjelek)."""
    lead = _LEAD_RE.match(token).group(0)
    rest = token[len(lead):]
    trail = _TRAIL_RE.search(rest).group(0)
    core = rest[:len(rest) - len(trail)] if trail else rest
    return lead, core, trail


# --- nevek ---

# Előtagok / címek: mindig kisbetűvel, ponttal.
_NAME_TITLES = {
    'dr': 'dr.', 'dr.': 'dr.',
    'ifj': 'ifj.', 'ifj.': 'ifj.',
    'id.': 'id.',
    'özv': 'özv.', 'özv.': 'özv.',
}
# Mindig kisbetűs névszavak: különálló 'né' ('Kovács János né') és a
# születési név jelölése ('(szül. Nagy)').
_NAME_LOWER = {'né', 'szül.', 'szül'}
# Idegen névelőtagok: nem az első szónál kisbetűsek ('Van der Berg');
# az első szónál csak az eleve kisbetűs alakot hagyjuk meg ('von Berg').
_NAME_PARTICLES = {'von', 'van', 'de', 'der', 'den', 'la', 'le', 'du',
                   'di', 'da', 'del'}
# Szóhoz ponttal tapadt cím: 'DR.NAGY' → 'dr.' + 'NAGY'.
_GLUED_TITLE_RE = re.compile(r'^(dr|ifj|id|özv)\.(?=[^\W\d_])', re.IGNORECASE)


def _capitalize_name_part(part):
    """Névtag nagybetűsítése; aposztróf után is nagy betű ('O'Brien').

    A '-né' tag mindig kisbetűs ('Szabó-né').
    """
    if part.lower() == 'né':
        return 'né'
    if not _is_uniform(part):
        return part
    return "'".join(_capitalize(p.lower()) for p in part.split("'"))


def normalize_name(text):
    """Személynév egységesítése: 'NAGY-KOVÁCS ZSÓFIA' → 'Nagy-Kovács Zsófia'.

    A magyar kettős betűk (Zs, Gy, Sz) és ékezetek maguktól jól működnek,
    mert csak az első betű lesz nagy. A 'né' végű alakok érintetlenek
    ('KOVÁCS JÁNOSNÉ' → 'Kovács Jánosné'); a 'dr.', 'ifj.', 'id.', 'özv.'
    kisbetűs, ponttal; a római sorszám ('II') nagybetűs marad.
    """
    words = []
    for word in _collapse(text).split(' ') if _collapse(text) else []:
        m = _GLUED_TITLE_RE.match(word)
        if m:
            words.extend((m.group(0), word[m.end():]))
        else:
            words.append(word)
    out = []
    for i, word in enumerate(words):
        lead, core, trail = _split_token(word)
        low = core.lower()
        if not core:
            new = core
        elif low in _NAME_TITLES:
            new = _NAME_TITLES[low]
        elif low in _NAME_LOWER and (_is_uniform(core) or low == 'né'):
            new = low
        elif low in _NAME_PARTICLES and (core.islower()
                                         or (i > 0 and _is_uniform(core))):
            new = low
        elif i > 0 and core.isupper() and _ROMAN_RE.match(core.rstrip('.')):
            new = core
        else:
            new = '-'.join(_capitalize_name_part(p) for p in core.split('-'))
        out.append(lead + new + trail)
    return ' '.join(out)


# --- címek és helynevek (közös szófeldolgozás) ---

# Közterület-jellegek: kisbetűsek, de CSAK ha egy név után állnak
# ('Kert utca' → az első szó 'Kert', a második 'utca').
_STREET_TYPES = {
    'utca', 'u.', 'u', 'út', 'útja', 'tér', 'tere', 'körút', 'körútja',
    'krt.', 'krt', 'köz', 'köze', 'sor', 'sora', 'sétány', 'fasor', 'dűlő',
    'liget', 'lakótelep', 'ltp.', 'ltp', 'rakpart', 'park', 'kert', 'telep',
    'tanya', 'major', 'puszta', 'árok', 'part', 'sugárút', 'lépcső', 'udvar',
    'zug',
}
# Mindig kisbetűs szavak a címben (emelet, ajtó, kerület, helyrajzi szám…).
_ADDRESS_LOWER = {
    'emelet', 'em.', 'ajtó', 'fszt.', 'fszt', 'földszint', 'lph.', 'lph',
    'lépcsőház', 'kerület', 'ker.', 'hrsz.', 'hrsz', 'sz.', 'szám',
}
# Mindig kisbetűs szavak a születési helyben.
_PLACE_LOWER = {'kerület', 'ker.', 'megye'}


def _fix_run(run, before, always_lower, types):
    """Egy számokkal / pontokkal tagolt szón belüli betűsorozat ('u.12', '12/a')."""
    low = run.lower()
    if low in always_lower or low in types:
        return low
    roman = _roman(run)
    if roman:
        return roman
    letters = run.rstrip('.')
    if len(letters) == 1:
        # házszám betűjele: '12/A', '5B'
        if before and (before.isdigit() or before in '/-'):
            return run.upper()
        return run
    return _capitalize(run)


def _fix_words(text, always_lower, types):
    """Szavankénti kis-nagybetű javítás a cím- és helynév-szabályokkal."""
    tokens = text.split(' ') if text else []
    out = []
    prev_is_word = False  # az előző szó tisztán betűs név volt-e (vessző nélkül)
    for idx, token in enumerate(tokens):
        lead, core, trail = _split_token(token)
        low = core.lower()
        is_word = bool(core) and not any(c.isdigit() for c in core)
        # Ha közvetlenül újabb közterület-jelleg követi ('KERT UTCA'), akkor
        # ez a szó az utcanév része, nem a jelleg.
        nxt = _split_token(tokens[idx + 1])[1].lower() if idx + 1 < len(tokens) else ''
        name_part = nxt in types and not trail
        if not core:
            new = core
        elif low in always_lower:
            new = low
        elif low in types and prev_is_word and not lead and not name_part:
            new = low
        elif _roman(core):
            new = _roman(core)
        elif any(c.isdigit() for c in core) or '.' in core.rstrip('.'):
            # vegyes szó (házszám, 'u.12', 'XI.ker.'): betűsorozatonként
            def repl(m, core=core):
                before = core[m.start() - 1] if m.start() > 0 else ''
                return _fix_run(m.group(0), before, always_lower, types)
            new = _RUN_RE.sub(repl, core)
        else:
            new = _capitalize_hyphenated(core)
        out.append(lead + new + trail)
        prev_is_word = (is_word and _roman(core) is None
                        and not any(c in trail for c in ',;:'))
    return ' '.join(out)


def normalize_address(text):
    """Lakcím egységesítése: '1234 BUDAPEST, FŐ UTCA 12. 3/4'
    → '1234 Budapest, Fő utca 12. 3/4'.

    A település és utcanév nagy kezdőbetűs, a közterület-jelleg, emelet,
    ajtó, kerület kisbetűs, a római számok és a házszám-betűjelek nagyok.
    """
    s = _fix_commas(_collapse(text))
    return _fix_words(s, _ADDRESS_LOWER, _STREET_TYPES)


# --- születési hely és idő ---

# Dátum: év, hónap, nap, azonos elválasztóval ('.', '-', '/'), opcionális
# szóközökkel és záró ponttal: 1990.1.5 / 1990. 01. 05. / 1990-01-05.
_DATE_RE = re.compile(
    r'(?<!\d)(\d{4})\s*([.\-/])\s*(\d{1,2})\s*\2\s*(\d{1,2})(?:\s*\.)?(?!\d)')
_YEAR_MIN, _YEAR_MAX = 1880, 2100


def _parse_date(m):
    """A találatból érvényes dátum, vagy None."""
    y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
    if not _YEAR_MIN <= y <= _YEAR_MAX:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def normalize_place_date(text):
    """Születési hely és idő: 'BUDAPEST 1990.1.5' → 'Budapest, 1990.01.05.'.

    Csak egyetlen, érvényes dátumot írunk át; ha a dátum a végén áll és
    előtte hely van, közéjük ', ' kerül. Ha bizonytalan, csak a szóközöket
    és a kis-nagybetűket javítjuk.
    """
    s = _fix_commas(_collapse(text))
    matches = list(_DATE_RE.finditer(s))
    if len(matches) != 1 or _parse_date(matches[0]) is None:
        return _fix_words(s, _PLACE_LOWER, ())
    m = matches[0]
    canon = _parse_date(m).strftime('%Y.%m.%d.')
    before, after = s[:m.start()], s[m.end():]
    if not after.strip():
        place = before.rstrip(' ,')
        if not place:
            return canon
        if place[-1].isalnum() or place[-1] in '.)':
            return _fix_words(place, _PLACE_LOWER, ()) + ', ' + canon
    # a dátum máshol áll: helyben cseréljük, a többit csak betűzzük
    return (_fix_words(before.rstrip(' '), _PLACE_LOWER, ())
            + (' ' if before.strip() else '') + canon
            + (' ' if after.strip() and not after.startswith(',') else '')
            + _fix_words(after.strip(), _PLACE_LOWER, ())).strip()


def _invalid_date_part(text):
    """A dátumszerű, de érvénytelen rész szövege (vagy None)."""
    for m in _DATE_RE.finditer(_collapse(text)):
        if _parse_date(m) is None:
            return m.group(0).strip()
    return None


# --- azonosítók ---

_ID_SEP_RE = re.compile(r'[\s.\-]')
_DIGITS_RE = re.compile(r'[0-9]+')


def normalize_id(text):
    """Adóazonosító / TAJ: ha a szóköz, kötőjel, pont elhagyásával csak
    számjegy marad, azt adjuk vissza; különben a levágott eredetit."""
    s = _text(text).strip()
    digits = _ID_SEP_RE.sub('', s)
    if _DIGITS_RE.fullmatch(digits):
        return digits
    return s


def valid_adoazonosito(text):
    """Magyar adóazonosító jel: 10 számjegy, 8-assal kezdődik; az első 9
    jegy helyiértékkel (1..9) szorzott összege mod 11 = 10. jegy (10 → hibás)."""
    s = normalize_id(text)
    if not re.fullmatch(r'8[0-9]{9}', s):
        return False
    check = sum(int(s[i]) * (i + 1) for i in range(9)) % 11
    return check != 10 and check == int(s[9])


def valid_taj(text):
    """TAJ-szám: 9 számjegy; az első 8 jegy páratlan helyen 3-mal, páros
    helyen 7-tel szorzott összege mod 10 = 9. jegy."""
    s = normalize_id(text)
    if not re.fullmatch(r'[0-9]{9}', s):
        return False
    total = sum(int(s[i]) * (3 if i % 2 == 0 else 7) for i in range(8))
    return total % 10 == int(s[8])


# --- személyrekord ---

_FIELD_FUNCS = {
    'nev': normalize_name,
    'szul_nev': normalize_name,
    'anya_neve': normalize_name,
    'szul_hely_ido': normalize_place_date,
    'lakcim': normalize_address,
    'adoazonosito': normalize_id,
    'taj': normalize_id,
}

# A hiányzó-adat figyelmeztetésben szereplő mezők, sorrendben.
_REQUIRED_LABELS = (
    ('szul_nev', 'születési név'),
    ('anya_neve', 'anyja neve'),
    ('szul_hely_ido', 'születési hely és idő'),
    ('lakcim', 'lakcím'),
)


def normalize_person(person):
    """ÚJ dict a normalizált mezőkkel; a többi kulcs változatlan.

    Hiányzó kulcsot nem adunk hozzá, a nem szöveges értéket (pl. None)
    nem bántjuk.
    """
    result = dict(person)
    for key, func in _FIELD_FUNCS.items():
        if key in result and isinstance(result[key], str):
            result[key] = func(result[key])
    return result


def person_changes(person):
    """[(mező, régi, új), ...] – csak a ténylegesen változó mezők."""
    new = normalize_person(person)
    return [(key, person[key], new[key]) for key in _FIELD_FUNCS
            if key in person and person[key] != new[key]]


def check_person(person):
    """Magyar nyelvű figyelmeztetések listája (üres, ha minden rendben)."""
    warnings = []

    ado = _text(person.get('adoazonosito')).strip()
    if not ado:
        warnings.append('Hiányzó adóazonosító.')
    elif not valid_adoazonosito(ado):
        if re.fullmatch(r'8[0-9]{9}', normalize_id(ado)):
            warnings.append(f'Az adóazonosító ({ado}) ellenőrzőszáma hibás '
                            '– valószínűleg elírás.')
        else:
            warnings.append(f'Az adóazonosító ({ado}) formátuma hibás '
                            '(10 számjegy, 8-assal kezdődik).')

    taj = _text(person.get('taj')).strip()
    if taj and not valid_taj(taj):
        if re.fullmatch(r'[0-9]{9}', normalize_id(taj)):
            warnings.append(f'A TAJ-szám ({taj}) ellenőrzőszáma hibás.')
        else:
            warnings.append(f'A TAJ-szám ({taj}) formátuma hibás '
                            '(9 számjegy kell).')

    bad_date = _invalid_date_part(person.get('szul_hely_ido'))
    if bad_date:
        warnings.append(f'A születési dátum ({bad_date}) nem érvényes dátum.')

    missing = [label for key, label in _REQUIRED_LABELS
               if not _text(person.get(key)).strip()]
    if missing:
        warnings.append('Hiányzó adatok: ' + ', '.join(missing))

    return warnings
