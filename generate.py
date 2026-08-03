from datetime import datetime, timedelta

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter

EPOCH = datetime(1899, 12, 30)

# --- támogatott bemeneti formátumok ---
#
# A bemeneti fájl kétféle lehet:
#   * 'legacy'  – a régi 'e-bev' munkalap
#   * 'nav2026' – az új NAV-export ('Bejelentés adatok' munkalap,
#                 pl. Egyszerusitett_<adószám>_<riportazonosító>.xlsx)
#
# Az oszlopfelismerés továbbra is pozíció alapú, de a formátumot a munkalap
# neve és a fejléc tartalma alapján automatikusan felismerjük.


class InputFormat:
    """Egy bemeneti formátum pozíció alapú oszlopkiosztása.

    A 'torles' és 'hiba' oszlopok kétféleképp működhetnek:
      * marker módban a cellában szereplő szó jelzi az állapotot (régi fájl),
      * expected módban a cella normál esetben egy fix értéket tartalmaz, és
        minden ettől eltérő érték jelenti a törlést / hibát (új NAV-export,
        ahol nem ismert előre a törölt vagy hibás sorok pontos szövege).
    """

    def __init__(self, key, label, sheet_names, header_keywords, columns,
                 torles=None, hiba=None, output_sheet=None):
        self.key = key
        self.label = label
        self.sheet_names = sheet_names
        self.output_sheet = output_sheet or sheet_names[0]
        self.header_keywords = header_keywords
        self.columns = columns
        self.torles = torles
        self.hiba = hiba

        used = list(columns.values())
        for rule in (torles, hiba):
            if rule:
                used.append(rule['col'])
        self.used_columns = tuple(sorted(set(used)))
        self.min_columns = max(self.used_columns) + 1

    def col(self, name):
        return self.columns[name]


LEGACY_FORMAT = InputFormat(
    key='legacy',
    label="régi 'e-bev' formátum",
    sheet_names=('e-bev',),
    header_keywords=(),
    columns={'nev': 0, 'adoazonosito': 1, 'bejelentes': 2,
             'kezdes': 5, 'munkanapok': 7, 'taj': 8},
    torles={'col': 3, 'mode': 'marker', 'markers': ('törlés',)},
    hiba={'col': 9, 'mode': 'marker', 'markers': ('hibás', 'hiba')},
)

NAV2026_FORMAT = InputFormat(
    key='nav2026',
    label="új NAV-export ('Bejelentés adatok')",
    sheet_names=('bejelentés adatok',),
    header_keywords=('munkavállaló neve', 'adóazonosító jele', 'taj száma',
                     'munkanapok száma', 'bejelentés jellege'),
    # A oszlop = sorszám (nem használjuk), az adatok B-től kezdődnek.
    columns={'nev': 1, 'adoazonosito': 2, 'taj': 3,
             'kezdes': 5, 'munkanapok': 7, 'bejelentes': 13},
    # I oszlop: 'Bejelentés jellege' – normál esetben 'Új'; minden más
    # (törlés, visszavonás, módosítás) törölt rekordnak számít.
    torles={'col': 8, 'mode': 'expected', 'expected': ('új',)},
    # K oszlop: 'Adatlap feldolgozottsági státusza' – normál esetben
    # 'FELDOLGOZOTT'; minden más érték hibás rekordot jelöl.
    hiba={'col': 10, 'mode': 'expected', 'expected': ('feldolgozott',)},
    output_sheet='Bejelentés adatok',
)

FORMATS = (NAV2026_FORMAT, LEGACY_FORMAT)
DEFAULT_FORMAT = LEGACY_FORMAT


def date_str_to_serial(date_str):
    cleaned = str(date_str).rstrip('.').strip()
    parts = cleaned.split('.')
    if len(parts) < 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return (datetime(y, m, d) - EPOCH).days
    except Exception:
        return None


def serial_to_date(serial):
    return EPOCH + timedelta(days=serial)


def serial_to_month_serial(serial):
    dt = serial_to_date(serial)
    return (datetime(dt.year, dt.month, 1) - EPOCH).days


def serial_to_ym(serial):
    dt = serial_to_date(serial)
    return f"{dt.year:04d}-{dt.month:02d}"


def serial_to_iso(serial):
    return serial_to_date(serial).strftime('%Y-%m-%d')


def iso_to_serial(iso):
    return (datetime.fromisoformat(iso) - EPOCH).days


def entry_key(entry):
    return f"{entry['adoazonosito']}|{serial_to_iso(entry['start_serial'])}|{entry['munkanapok']}"


def autofit(ws):
    DATE_FMT = 'YYYY.MM.DD.'
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value is None:
                continue
            if isinstance(cell.value, datetime):
                cell.number_format = DATE_FMT
                length = 12
            else:
                length = len(str(cell.value))
            if length > max_len:
                max_len = length
        ws.column_dimensions[col_letter].width = max(max_len + 2, 8)


def cell_text(row, idx):
    if idx is None or len(row) <= idx or row[idx] is None:
        return ''
    return str(row[idx]).strip()


def _flag_value(row, rule):
    """A törlés/hiba szabály által jelzett érték, vagy '' ha a sor rendben van."""
    if not rule:
        return ''
    value = cell_text(row, rule['col'])
    if rule['mode'] == 'marker':
        return value if value.lower() in rule['markers'] else ''
    # expected mód: üres cellát nem tekintünk eltérésnek (hiányzó adat, nem hiba)
    if not value:
        return ''
    return '' if value.lower() in rule['expected'] else value


def torles_value(row, fmt=DEFAULT_FORMAT):
    return _flag_value(row, fmt.torles)


def hiba_value(row, fmt=DEFAULT_FORMAT):
    return _flag_value(row, fmt.hiba)


def is_torles(row, fmt=DEFAULT_FORMAT):
    return bool(torles_value(row, fmt))


def is_hibas(row, fmt=DEFAULT_FORMAT):
    return bool(hiba_value(row, fmt))


def detect_format(sheet_title, header):
    """A munkalap neve és a fejléc alapján felismert bemeneti formátum."""
    title = (sheet_title or '').strip().lower()
    for fmt in FORMATS:
        if title in fmt.sheet_names:
            return fmt

    header_text = ' | '.join(str(h).strip().lower() for h in (header or []) if h)
    for fmt in FORMATS:
        if fmt.header_keywords and all(kw in header_text for kw in fmt.header_keywords):
            return fmt
    return DEFAULT_FORMAT


def _pick_sheet(wb_in):
    by_title = {ws.title.strip().lower(): ws for ws in wb_in.worksheets}
    for fmt in FORMATS:
        for name in fmt.sheet_names:
            if name in by_title:
                return by_title[name]
    return wb_in.active


def read_input(input_path):
    wb_in = load_workbook(input_path)
    ws_in = _pick_sheet(wb_in)
    all_rows = list(ws_in.values)
    if not all_rows:
        return None, [], DEFAULT_FORMAT
    header = all_rows[0]
    fmt = detect_format(ws_in.title, header)
    key_col = fmt.col('nev')
    data_rows = [r for r in all_rows[1:]
                 if len(r) > key_col and r[key_col] and str(r[key_col]).strip()]
    return header, data_rows, fmt


def check_header(header, fmt=DEFAULT_FORMAT):
    if header is None:
        return ['A fejléc sor hiányzik (üres fájl).']
    problems = []
    if len(header) < fmt.min_columns:
        problems.append(
            f'A fejléc csak {len(header)} oszlopot tartalmaz, legalább {fmt.min_columns} szükséges.')
    for idx in fmt.used_columns:
        if idx < len(header):
            val = header[idx]
            if val is None or not str(val).strip():
                problems.append(f'A fejléc {idx + 1}. oszlopa üres.')
    return problems


def extract_entries(data_rows, fmt=DEFAULT_FORMAT):
    active_rows = [r for r in data_rows
                   if not is_torles(r, fmt) and not is_hibas(r, fmt)]

    c_bejelentes = fmt.col('bejelentes')
    c_kezdes = fmt.col('kezdes')
    c_munkanapok = fmt.col('munkanapok')

    bejelentes_months = {}
    for r in active_rows:
        raw = cell_text(r, c_bejelentes)
        s = date_str_to_serial(raw.split(' ')[0]) if raw else None
        if s:
            ms = serial_to_month_serial(s)
            bejelentes_months[ms] = bejelentes_months.get(ms, 0) + 1
    current_month_serial = max(bejelentes_months, key=bejelentes_months.get) if bejelentes_months else None

    current_entries = []
    future_entries = []
    for r in active_rows:
        try:
            munkanapok = int(r[c_munkanapok])
        except Exception:
            munkanapok = 1
        start_serial = date_str_to_serial(cell_text(r, c_kezdes))
        if start_serial is None:
            continue
        entry = {
            'nev': cell_text(r, fmt.col('nev')),
            'adoazonosito': cell_text(r, fmt.col('adoazonosito')),
            'taj': cell_text(r, fmt.col('taj')),
            'start_serial': start_serial,
            'munkanapok': munkanapok,
        }
        if current_month_serial and serial_to_month_serial(start_serial) > current_month_serial:
            future_entries.append(entry)
        else:
            current_entries.append(entry)

    return current_month_serial, current_entries, future_entries


def merge_entries(current_entries, carried_entries):
    merged = list(current_entries)
    seen = {entry_key(e) for e in current_entries}
    for e in carried_entries:
        if entry_key(e) not in seen:
            seen.add(entry_key(e))
            merged.append(e)
    return merged


def generate_output(input_path, header, data_rows, entries, output_path=None,
                    fmt=DEFAULT_FORMAT, persons=None):
    persons = persons or {}
    by_date = {}
    by_name = {}

    for entry in entries:
        nev = entry['nev']
        if nev not in by_name:
            by_name[nev] = {'adoazonosito': entry['adoazonosito'],
                            'taj': entry['taj'], 'dates': set()}
        for i in range(entry['munkanapok']):
            serial = entry['start_serial'] + i
            by_date.setdefault(serial, []).append({'nev': nev})
            by_name[nev]['dates'].add(serial)

    sorted_dates = sorted(by_date.keys())
    sorted_names = sorted(by_name.keys(), key=lambda x: x.lower())
    month_serials = sorted(set(serial_to_month_serial(s) for s in sorted_dates))

    wb_out = Workbook()
    wb_out.remove(wb_out.active)

    RED_FILL = PatternFill("solid", fgColor="FF0000")
    BLUE_FILL = PatternFill("solid", fgColor="4472C4")
    WHITE_FONT = Font(color="FFFFFF", bold=True)

    # forrásadat lap (aktuális fájl) – a bemeneti munkalap nevével
    ws_ebev = wb_out.create_sheet(fmt.output_sheet)
    ws_ebev.append(list(header))
    for r in data_rows:
        ws_ebev.append(list(r))
        row_idx = ws_ebev.max_row
        if is_hibas(r, fmt):
            fill, font = RED_FILL, WHITE_FONT
        elif is_torles(r, fmt):
            fill, font = BLUE_FILL, WHITE_FONT
        else:
            continue
        for col in range(1, len(r) + 1):
            cell = ws_ebev.cell(row=row_idx, column=col)
            cell.fill = fill
            cell.font = font

    # Dátum Szerint
    ws_datum = wb_out.create_sheet('Dátum Szerint')
    for serial in sorted_dates:
        workers = by_date[serial]
        ws_datum.append([serial_to_date(serial), workers[0]['nev'], '', '', '', ''])
        for w in workers[1:]:
            ws_datum.append(['', w['nev'], '', '', '', ''])
        ws_datum.append([''] * 6)

    # Név Szerint
    ws_nev = wb_out.create_sheet('Név Szerint')
    for nev in sorted_names:
        info = by_name[nev]
        p = persons.get(info['taj'], {})
        ws_nev.append(['név:', nev, '', '', ''])
        ws_nev.append(['szül.név', p.get('szul_nev', ''), '', '', ''])
        ws_nev.append(['anyja neve:', p.get('anya_neve', ''), '', '', ''])
        ws_nev.append(['szül.hely, idő:', p.get('szul_hely_ido', ''), '', '', ''])
        ws_nev.append(['adóazonosító:', info['adoazonosito'], '', '', ''])
        ws_nev.append(['TAJ-szám:', info['taj'], '', '', ''])
        ws_nev.append(['lakcím:', p.get('lakcim', ''), '', '', ''])
        ws_nev.append([''] * 5)
        unique_dates = sorted(info['dates'])
        for serial in unique_dates:
            ws_nev.append([serial_to_date(serial), 1, '', '', ''])
        ws_nev.append(['', len(unique_dates), '', '', ''])
        ws_nev.append([''] * 5)

    # Ki hány napot dolgozott
    ws_hany = wb_out.create_sheet('ki hány napot dolgozott')
    header1 = ['név', '']
    for ms in month_serials:
        header1 += [serial_to_date(ms), '']
    header1 += ['bérkifizetés', 'munkanapok', '']
    ws_hany.append(header1)

    header2 = ['', 'Nap']
    for _ in month_serials:
        header2 += ['Összeg', '']
    header2 += ['összesen', 'összesen', '']
    ws_hany.append(header2)

    for nev in sorted_names:
        info = by_name[nev]
        by_month = {}
        for serial in info['dates']:
            ms = serial_to_month_serial(serial)
            by_month[ms] = by_month.get(ms, 0) + 1

        nap_row = [nev]
        total_nap = 0
        for ms in month_serials:
            nap = by_month.get(ms, '')
            nap_row += [nap, '']
            if nap:
                total_nap += nap
        nap_row += ['', total_nap, '']
        ws_hany.append(nap_row)

        ossze_row = [''] + ['', ''] * len(month_serials) + ['', '', '']
        ws_hany.append(ossze_row)

    for ws in wb_out.worksheets:
        autofit(ws)

    if output_path is None:
        import os
        output_path = os.path.splitext(input_path)[0] + '_statisztika.xlsx'
    wb_out.save(output_path)
    return output_path
