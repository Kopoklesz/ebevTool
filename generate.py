import sys
import os
import json

# Windows: ékezetes argumentumok helyes kezelése Win32 API-val
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.kernel32.SetConsoleCP(65001)
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    try:
        GetCommandLineW = ctypes.windll.kernel32.GetCommandLineW
        GetCommandLineW.restype = ctypes.c_wchar_p
        CommandLineToArgvW = ctypes.windll.shell32.CommandLineToArgvW
        CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        nargs = ctypes.c_int()
        lp = CommandLineToArgvW(GetCommandLineW(), ctypes.byref(nargs))
        unicode_args = [lp[i] for i in range(nargs.value)]
        if getattr(sys, 'frozen', False):
            sys.argv = unicode_args
        elif len(unicode_args) >= 3:
            sys.argv = [unicode_args[1]] + unicode_args[2:]
    except Exception:
        pass

from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter
import openpyxl

EPOCH = datetime(1899, 12, 30)

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
    return str(row[3]).strip() == 'Törlés'

def is_hibas(row):
    s = str(row[9]).strip().lower()
    return s in ('hibás', 'hiba')

def get_memory_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'memory.json')

def load_memory():
    path = get_memory_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_memory(memory):
    path = get_memory_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def main():
    if len(sys.argv) < 2:
        input("Húzd rá az Excel fájlt erre a programra!\nNyomj Entert a kilépéshez...")
        return

    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        try:
            input_file = input_file.encode('latin-1').decode('utf-8')
        except Exception:
            pass
    if not os.path.exists(input_file):
        input(f"Nem található a fájl: {input_file}\nNyomj Entert a kilépéshez...")
        return

    print(f"Beolvasás: {input_file}")

    wb_in = openpyxl.load_workbook(input_file)
    if 'e-bev' in wb_in.sheetnames:
        ws_in = wb_in['e-bev']
    else:
        ws_in = wb_in.active
    all_rows = list(ws_in.values)

    if not all_rows:
        input("Üres fájl!\nNyomj Entert a kilépéshez...")
        return

    header = all_rows[0]
    data_rows = [r for r in all_rows[1:] if r[0] and str(r[0]).strip()]
    active_rows = [r for r in data_rows if not is_torles(r) and not is_hibas(r)]

    # Az aktuális fájl hónapját a bejelentés napjaiból határozzuk meg (a leggyakoribb hónap)
    bejelentes_months = {}
    for r in active_rows:
        s = date_str_to_serial(str(r[2]).split(' ')[0]) if r[2] else None
        if s:
            ms = serial_to_month_serial(s)
            bejelentes_months[ms] = bejelentes_months.get(ms, 0) + 1
    current_month_serial = max(bejelentes_months, key=bejelentes_months.get) if bejelentes_months else None

    # Memory betöltése (előző hónapból áthúzódó rekordok)
    memory = load_memory()

    # Az aktuális fájl rekordjait feldolgozzuk:
    # - ha Kezdés napja az aktuális hónapban (vagy korábban) van → ebbe a statisztikába kerül
    # - ha Kezdés napja egy JÖVŐBELI hónapban van → mentjük a memóriába a következő hónapnak
    current_entries = []   # az aktuális statisztikába kerülők
    new_memory = {}        # amit a memóriában tartunk a következő hónapnak

    for r in active_rows:
        nev = str(r[0]).strip()
        adoazon = str(r[1]).strip()
        taj = str(r[8]).strip()
        try:
            munkanapok = int(r[7])
        except Exception:
            munkanapok = 1
        start_serial = date_str_to_serial(r[5])
        if start_serial is None:
            continue

        start_month = serial_to_month_serial(start_serial)
        key = f"{adoazon}|{start_serial}|{munkanapok}"

        if current_month_serial and start_month > current_month_serial:
            # Jövőbeli kezdés → mentjük a következő hónapnak
            new_memory[key] = {
                'nev': nev, 'adoazonosito': adoazon, 'taj': taj,
                'start_serial': start_serial, 'munkanapok': munkanapok
            }
        else:
            # Aktuális vagy múltbeli kezdés → ebbe a statisztikába kerül
            current_entries.append({
                'nev': nev, 'adoazonosito': adoazon, 'taj': taj,
                'start_serial': start_serial, 'munkanapok': munkanapok
            })

    # A memóriából áthozott rekordok (előző hónapban bejelentve, most kezdenek)
    carried_count = 0
    for key, entry in memory.items():
        start_month = serial_to_month_serial(entry['start_serial'])
        if current_month_serial is None or start_month <= current_month_serial:
            # Ez a hónap már itt van → bekerül a statisztikába
            current_entries.append(entry)
            carried_count += 1
        else:
            # Még nem aktuális → marad a memóriában
            new_memory[key] = entry

    save_memory(new_memory)
    print(f"Áthozott rekord az előző hónapból: {carried_count}, következő hónapra mentve: {len(new_memory)}")

    # Struktúra felépítése
    by_date = {}
    by_name = {}

    for entry in current_entries:
        nev = entry['nev']
        adoazon = entry['adoazonosito']
        taj = entry['taj']

        if nev not in by_name:
            by_name[nev] = {'adoazonosito': adoazon, 'taj': taj, 'dates': set()}

        for i in range(entry['munkanapok']):
            serial = entry['start_serial'] + i
            by_date.setdefault(serial, []).append({'nev': nev})
            by_name[nev]['dates'].add(serial)

    sorted_dates = sorted(by_date.keys())
    sorted_names = sorted(by_name.keys(), key=lambda x: x.lower())
    month_serials = sorted(set(serial_to_month_serial(s) for s in sorted_dates))

    wb_out = Workbook()
    wb_out.remove(wb_out.active)

    RED_FILL  = PatternFill("solid", fgColor="FF0000")
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

    base = os.path.splitext(input_file)[0]
    output_file = base + '_statisztika.xlsx'
    wb_out.save(output_file)
    print(f"Kész! Kimenet: {output_file}")
    if sys.stdin.isatty():
        input("Nyomj Entert a kilépéshez...")

if __name__ == '__main__':
    main()
