import os
import shutil
import sys

# Windows: ékezetes argumentumok helyes kezelése Win32 API-val
if sys.platform == 'win32':
    import ctypes
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

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

import generate
import filename_utils
from firebase_store import FirebaseError, FirebaseStore, months_between, ym_today

try:
    import config
except ImportError:
    config = None


def default_archive_dir():
    configured = getattr(config, 'ARCHIVE_DIR', None) if config else None
    return configured or os.path.join(filename_utils.app_dir(), 'archívum')


class App:
    def __init__(self, root):
        self.root = root
        self.store = None
        self._online = None
        if config is not None:
            self.store = FirebaseStore(config.FIREBASE_API_KEY,
                                       config.FIREBASE_PROJECT_ID,
                                       config.FERNET_KEY)

        root.title('ebevTool – Statisztika generálás')
        root.geometry('620x480')

        self.drop_label = tk.Label(
            root, text='Húzd ide az Excel fájlt\nvagy használd a Tallózás gombot',
            relief='groove', bd=2, height=5, bg='#f0f0f0')
        self.drop_label.pack(fill='x', padx=12, pady=(12, 6))
        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind('<<Drop>>', self._on_drop)

        btn_row = tk.Frame(root)
        btn_row.pack(fill='x', padx=12, pady=6)
        tk.Button(btn_row, text='Tallózás...', command=self._browse).pack(side='left')
        tk.Button(btn_row, text='Előzmények', command=self.open_history).pack(side='left', padx=(8, 0))
        tk.Button(btn_row, text='Várakozási sor', command=self.open_queue).pack(side='left', padx=(8, 0))

        self.status = tk.Text(root, state='disabled', wrap='word')
        scroll = tk.Scrollbar(root, command=self.status.yview)
        self.status.configure(yscrollcommand=scroll.set)
        self.status.pack(side='left', fill='both', expand=True, padx=(12, 0), pady=(6, 12))
        scroll.pack(side='right', fill='y', padx=(0, 12), pady=(6, 12))

        if not DND_AVAILABLE:
            self.log('Figyelem: a tkinterdnd2 csomag nem elérhető, a drag&drop '
                     'nem működik — használd a Tallózás gombot. (pip install tkinterdnd2)')
        if config is None:
            self.log('Figyelem: nincs config.py — a Firebase funkciók (várakozási '
                     'sor, előzmények, aliasok) nem érhetők el. Másold le a '
                     'config.example.py-t config.py néven és töltsd ki '
                     '(lásd FIREBASE_SETUP.md).')

    # --- segédek ---

    def log(self, msg):
        self.status.configure(state='normal')
        self.status.insert('end', msg + '\n')
        self.status.see('end')
        self.status.configure(state='disabled')
        self.root.update_idletasks()

    def store_online(self):
        """Lazy bejelentkezés; False, ha nincs config vagy nincs kapcsolat."""
        if not self.store:
            return False
        if self._online is None:
            try:
                self.store.sign_in()
                self._online = True
            except FirebaseError as e:
                self._online = False
                self.log(f'Firebase nem érhető el: {e}')
        return self._online

    # --- fájl kiválasztás ---

    def _browse(self):
        path = filedialog.askopenfilename(
            title='Excel fájl kiválasztása',
            filetypes=[('Excel fájlok', '*.xlsx'), ('Minden fájl', '*.*')])
        if path:
            self.process_file(path)

    def _on_drop(self, event):
        data = event.data.strip()
        if data.startswith('{'):
            path = data[1:data.index('}')]
        else:
            path = data.split()[0] if ' ' in data and not os.path.exists(data) else data
        self.process_file(path)

    # --- cégfelismerés ---

    def known_companies(self):
        """Korábban megismert cégek (helyi + Firestore aliasok alapján), rendezve."""
        companies = set(filename_utils.load_local_aliases().values())
        if self.store_online():
            try:
                companies.update(self.store.list_companies())
            except FirebaseError:
                pass
        return sorted(c for c in companies if c)

    def ask_company_dialog(self, filename):
        """Modális popup: korábban megismert cégek közül választás vagy új
        cégnév megadása; None, ha bezárták."""
        result = {'company': None}
        dlg = tk.Toplevel(self.root)
        dlg.title('Cég kiválasztása')
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=f'Nem ismerhető fel a cég a fájlnévből:\n{filename}\n\n'
                           'Add meg vagy válaszd ki a céget:', padx=20, pady=12).pack()
        var = tk.StringVar()
        combo = ttk.Combobox(dlg, textvariable=var, values=self.known_companies(), width=30)
        combo.pack(padx=20)
        combo.focus_set()

        def choose():
            value = var.get().strip()
            if value:
                result['company'] = value
            dlg.destroy()

        btns = tk.Frame(dlg)
        btns.pack(pady=14)
        tk.Button(btns, text='OK', width=10, command=choose).pack(side='left', padx=8)
        tk.Button(btns, text='Mégse', width=10, command=dlg.destroy).pack(side='left', padx=8)
        dlg.bind('<Return>', lambda e: choose())
        dlg.wait_window()
        return result['company']

    def resolve_company(self, path):
        filename = os.path.basename(path)
        token = filename_utils.alias_token(filename)
        if token:
            company = filename_utils.get_local_alias(token)
            if not company and self.store_online():
                try:
                    company = self.store.get_alias(token)
                    if company:
                        filename_utils.set_local_alias(token, company)
                except FirebaseError:
                    pass
            if company:
                self.log(f'Cég a megjegyzett alias alapján: {company}')
                return company

        company = self.ask_company_dialog(filename)
        if company and token:
            filename_utils.set_local_alias(token, company)
            if self.store_online():
                try:
                    self.store.set_alias(token, company)
                except FirebaseError as e:
                    self.log(f'Az alias mentése Firestore-ba nem sikerült: {e}')
        return company

    # --- feldolgozás ---

    def process_file(self, path):
        try:
            self._process_file(path)
        except Exception as e:
            self.log(f'HIBA: {e}')
            messagebox.showerror('Hiba', f'A feldolgozás nem sikerült:\n{e}')

    def _process_file(self, path):
        self._online = None  # kapcsolat újrapróbálása minden futásnál
        if not os.path.exists(path):
            messagebox.showerror('Hiba', f'Nem található a fájl:\n{path}')
            return
        filename = os.path.basename(path)
        self.log(f'--- Beolvasás: {path}')

        company = self.resolve_company(path)
        if company is None:
            self.log('Megszakítva: nem lett cég kiválasztva.')
            return
        self.log(f'Cég: {company}')

        header, data_rows = generate.read_input(path)
        problems = generate.check_header(header)
        if problems:
            msg = ('A fejléc szerkezete eltér a várttól, ellenőrizd a fájlt!\n\n'
                   + '\n'.join(problems) + '\n\nFolytatod a feldolgozást?')
            if not messagebox.askokcancel('Fejléc figyelmeztetés', msg):
                self.log('Megszakítva a fejléc-ellenőrzés után.')
                return

        current_month_serial, current_entries, future_entries = \
            generate.extract_entries(data_rows)
        if current_month_serial is None:
            messagebox.showerror(
                'Hiba', 'Nem határozható meg a fájl hónapja (nincsenek '
                'érvényes bejelentési dátumok).')
            return
        ym = generate.serial_to_ym(current_month_serial)
        self.log(f'A fájl hónapja (a bejelentési dátumok alapján): {ym}')

        # Keresztellenőrzés a fájlnévbeli hónapnévvel
        fn_month = filename_utils.detect_month(filename)
        if fn_month and fn_month != int(ym[5:7]):
            if not messagebox.askokcancel(
                    'Hónap eltérés',
                    f'A fájlnévben szereplő hónap ({fn_month}.) eltér az '
                    f'adatokból számítottól ({ym}). Folytatod?'):
                self.log('Megszakítva hónap-eltérés miatt.')
                return

        # Fél évnél régebbi hónap újrafeldolgozása
        if months_between(ym, ym_today()) > 6:
            if not messagebox.askokcancel(
                    'Régi hónap',
                    'Ez a hónap több mint fél éve volt esedékes, a hozzá tartozó '
                    'átvitt adatok időközben véglegesen törlődtek — a kimenet '
                    'emiatt hiányos lehet. Folytatod?'):
                self.log('Megszakítva.')
                return

        # Várakozási sor betöltése Firestore-ból
        online = self.store_online()
        records = []
        if online:
            try:
                records = self.store.load_memory(company)
            except FirebaseError as e:
                online = False
                self.log(f'Firestore olvasás sikertelen: {e}')
        if not online:
            messagebox.showwarning(
                'Nincs kapcsolat',
                'A Firestore nem érhető el. A statisztika a korábbi hónapokból '
                'átvitt rekordok NÉLKÜL készül el, és a jövő hónapra szóló '
                'rekordok nem kerülnek mentésre!')
            self.log('Feldolgozás Firestore nélkül (hiányos lehet).')

        carried = []
        to_consume = []  # most esedékessé vált pending rekordok doc id-jai
        for rec in records:
            entry_ym = generate.serial_to_ym(
                generate.serial_to_month_serial(rec['entry']['start_serial']))
            if rec['status'] == 'pending' and entry_ym <= ym:
                carried.append(rec['entry'])
                to_consume.append(rec['id'])
            elif rec['status'] == 'consumed' and rec['consumed_in'] == ym:
                # Újrafeldolgozás: az ebben a hónapban már felhasznált rekordok
                # ismét beszámítanak, így a kimenet megegyezik az elsővel.
                carried.append(rec['entry'])

        entries = generate.merge_entries(current_entries, carried)
        self.log(f'Rekordok a fájlból: {len(current_entries)}, átvitt: {len(carried)}, '
                 f'jövő hónapra: {len(future_entries)}')

        output_file = generate.generate_output(path, header, data_rows, entries)
        self.log(f'Kész! Kimenet: {output_file}')

        # Helyi archívum
        try:
            dest_dir = os.path.join(default_archive_dir(),
                                    filename_utils.safe_folder_name(company), ym)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(output_file, dest_dir)
            self.log(f'Archiválva: {os.path.join(dest_dir, os.path.basename(output_file))}')
        except Exception as e:
            self.log(f'Az archiválás nem sikerült: {e}')

        # Firestore frissítések
        if online:
            try:
                for entry in future_entries:
                    self.store.upsert_pending(company, entry)
                for doc_id in to_consume:
                    self.store.mark_consumed(company, doc_id, ym)
                self.store.add_history(company, filename, ym)
                deleted = self.store.cleanup_expired(company)
                if deleted:
                    self.log(f'Takarítás: {deleted} lejárt rekord véglegesen törölve.')
                self.log(f'Várakozási sor frissítve ({len(future_entries)} mentve, '
                         f'{len(to_consume)} felhasználva).')
            except FirebaseError as e:
                self.log(f'Firestore írás sikertelen: {e}')
                messagebox.showwarning(
                    'Firestore hiba',
                    f'A statisztika elkészült, de a várakozási sor frissítése '
                    f'nem sikerült:\n{e}')

    # --- Előzmények nézet ---

    def open_history(self):
        if not self.store_online():
            messagebox.showerror('Nincs kapcsolat',
                                 'Az Előzmények nézethez Firestore kapcsolat szükséges.')
            return
        companies = self.known_companies()
        if not companies:
            messagebox.showinfo('Előzmények', 'Még nincs egyetlen ismert cég sem.')
            return
        win = tk.Toplevel(self.root)
        win.title('Előzmények')
        win.geometry('560x420')
        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=8, pady=8)
        for company in companies:
            frame = ttk.Frame(nb)
            nb.add(frame, text=company)
            tree = ttk.Treeview(frame, columns=('processed',))
            tree.heading('#0', text='Év-hónap / fájlnév')
            tree.heading('processed', text='Feldolgozva')
            tree.column('#0', width=300)
            tree.column('processed', width=200)
            tree.pack(fill='both', expand=True)
            try:
                rows = self.store.load_history(company)
            except FirebaseError as e:
                messagebox.showerror('Hiba', f'Előzmények betöltése sikertelen: {e}')
                win.destroy()
                return
            groups = {}
            for row in rows:
                groups.setdefault(row.get('year_month', '?'), []).append(row)
            for ym in sorted(groups, reverse=True):
                node = tree.insert('', 'end', text=ym, open=True)
                for row in sorted(groups[ym], key=lambda r: r.get('processed_at', '')):
                    processed = (row.get('processed_at') or '')[:19].replace('T', ' ')
                    tree.insert(node, 'end', text=row.get('filename', '?'),
                                values=(processed,))

    # --- Várakozási sor / Böngésző nézet ---

    def open_queue(self):
        if not self.store_online():
            messagebox.showerror('Nincs kapcsolat',
                                 'A Várakozási sor nézethez Firestore kapcsolat szükséges.')
            return
        companies = self.known_companies()
        if not companies:
            messagebox.showinfo('Várakozási sor', 'Még nincs egyetlen ismert cég sem.')
            return
        win = tk.Toplevel(self.root)
        win.title('Várakozási sor / Böngésző')
        win.geometry('760x460')
        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=8, pady=(8, 0))

        trees = {}

        def load_tab(company, tree):
            tree.delete(*tree.get_children())
            try:
                records = self.store.load_memory(company)
            except FirebaseError as e:
                messagebox.showerror('Hiba', f'Betöltés sikertelen: {e}')
                return
            groups = {}
            for rec in records:
                ym = generate.serial_to_ym(
                    generate.serial_to_month_serial(rec['entry']['start_serial']))
                groups.setdefault(ym, []).append(rec)
            for ym in sorted(groups, reverse=True):
                node = tree.insert('', 'end', text=ym, open=True)
                for rec in sorted(groups[ym], key=lambda r: r['entry']['nev'].lower()):
                    e = rec['entry']
                    status = 'függőben' if rec['status'] == 'pending' else 'felhasználva'
                    tree.insert(node, 'end', iid=f"{company}:{rec['id']}",
                                text=e['nev'],
                                values=(generate.serial_to_iso(e['start_serial']),
                                        e['munkanapok'], status,
                                        rec['consumed_in'] or ''))

        def delete_selected():
            company = companies[nb.index(nb.select())]
            tree = trees[company]
            selected = [i for i in tree.selection() if ':' in i]
            if not selected:
                messagebox.showinfo('Törlés', 'Válassz ki egy rekordot a listából.')
                return
            if not messagebox.askyesno(
                    'Törlés megerősítése',
                    f'{len(selected)} rekord VÉGLEGESEN törlődik a várakozási '
                    'sorból. Biztos vagy benne?'):
                return
            try:
                for iid in selected:
                    self.store.delete_record(company, iid.split(':', 1)[1])
            except FirebaseError as e:
                messagebox.showerror('Hiba', f'Törlés sikertelen: {e}')
            load_tab(company, tree)

        for company in companies:
            frame = ttk.Frame(nb)
            nb.add(frame, text=company)
            tree = ttk.Treeview(frame, columns=('start', 'days', 'status', 'consumed'))
            tree.heading('#0', text='Év-hónap / név')
            tree.heading('start', text='Kezdés')
            tree.heading('days', text='Munkanapok')
            tree.heading('status', text='Státusz')
            tree.heading('consumed', text='Felhasználva (hónap)')
            tree.column('#0', width=240)
            tree.column('start', width=100)
            tree.column('days', width=90)
            tree.column('status', width=100)
            tree.column('consumed', width=130)
            tree.pack(fill='both', expand=True)
            trees[company] = tree
            load_tab(company, tree)

        btns = tk.Frame(win)
        btns.pack(fill='x', padx=8, pady=8)
        tk.Button(btns, text='Kijelölt rekord törlése', command=delete_selected).pack(side='left')
        tk.Button(btns, text='Frissítés',
                  command=lambda: [load_tab(c, t) for c, t in trees.items()]).pack(side='left', padx=8)


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:
        root.after(200, lambda: app.process_file(sys.argv[1]))
    root.mainloop()


if __name__ == '__main__':
    main()
