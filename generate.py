from datetime import datetime, timedelta

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter

EPOCH = datetime(1899, 12, 30)

# Pozíció alapú oszlopkiosztás a bemeneti 'e-bev' lapon
COL_NEV = 0
COL_ADOAZON = 1
COL_BEJELENTES = 2
COL_TORLES = 3
COL_KEZDES = 5
COL_MUNKANAPOK = 7
COL_TAJ = 8
COL_HIBA = 9
USED_COLUMNS = (COL_NEV, COL_ADOAZON, COL_BEJELENTES, COL_TORLES,
                COL_KEZDES, COL_MUNKANAPOK, COL_TAJ, COL_HIBA)
MIN_COLUMNS = max(USED_COLUMNS) + 1


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


def is_torles(row):
    return len(row) > COL_TORLES and str(row[COL_TORLES]).strip() == 'Törlés'


def is_hibas(row):
    if len(row) <= COL_HIBA:
        return False
    s = str(row[COL_HIBA]).strip().lower()
    return s in ('hibás', 'hiba')


def read_input(input_path):
    wb_in = load_workbook(input_path)
    if 'e-bev' in wb_in.sheetnames:
        ws_in = wb_in['e-bev']
    else:
        ws_in = wb_in.active
    all_rows = list(ws_in.values)
    if not all_rows:
        return None, []
    header = all_rows[0]
    data_rows = [r for r in all_rows[1:] if r[0] and str(r[0]).strip()]
    return header, data_rows


def check_header(header):
    if header is None:
        return ['A fejléc sor hiányzik (üres fájl).']
    problems = []
    if len(header) < MIN_COLUMNS:
        problems.append(
            f'A fejléc csak {len(header)} oszlopot tartalmaz, legalább {MIN_COLUMNS} szükséges.')
    for idx in USED_COLUMNS:
        if idx < len(header):
            val = header[idx]
            if val is None or not str(val).strip():
                problems.append(f'A fejléc {idx + 1}. oszlopa üres.')
    return problems


def extract_entries(data_rows):
    active_rows = [r for r in data_rows if not is_torles(r) and not is_hibas(r)]

    bejelentes_months = {}
    for r in active_rows:
        s = date_str_to_serial(str(r[COL_BEJELENTES]).split(' ')[0]) if r[COL_BEJELENTES] else None
        if s:
            ms = serial_to_month_serial(s)
            bejelentes_months[ms] = bejelentes_months.get(ms, 0) + 1
    current_month_serial = max(bejelentes_months, key=bejelentes_months.get) if bejelentes_months else None

    current_entries = []
    future_entries = []
    for r in active_rows:
        try:
            munkanapok = int(r[COL_MUNKANAPOK])
        except Exception:
            munkanapok = 1
        start_serial = date_str_to_serial(r[COL_KEZDES])
        if start_serial is None:
            continue
        entry = {
            'nev': str(r[COL_NEV]).strip(),
            'adoazonosito': str(r[COL_ADOAZON]).strip(),
            'taj': str(r[COL_TAJ]).strip(),
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


def generate_output(input_path, header, data_rows, entries, output_path=None):
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

    # e-bev lap (aktuális fájl)
    ws_ebev = wb_out.create_sheet('e-bev')
    ws_ebev.append(list(header))
    for r in data_rows:
        ws_ebev.append(list(r))
        row_idx = ws_ebev.max_row
        if is_hibas(r):
            fill, font = RED_FILL, WHITE_FONT
        elif is_torles(r):
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
        ws_nev.append(['név:', nev, '', '', ''])
        ws_nev.append(['szül.név', '', '', '', ''])
        ws_nev.append(['anyja neve:', '', '', '', ''])
        ws_nev.append(['szül.hely, idő:', '', '', '', ''])
        ws_nev.append(['adóazonosító:', info['adoazonosito'], '', '', ''])
        ws_nev.append(['TAJ-szám:', info['taj'], '', '', ''])
        ws_nev.append(['lakcím:', '', '', '', ''])
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
