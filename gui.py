import os
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

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


# --- vizuális stílus ---

COLORS = {
    'bg': '#f3f5f8',
    'sidebar': '#1f2a3a',
    'sidebar_hover': '#2a3648',
    'sidebar_active': '#2f6fed',
    'sidebar_text': '#dbe2ef',
    'sidebar_muted': '#8a97ac',
    'card': '#ffffff',
    'border': '#dde2ea',
    'text': '#1f2933',
    'muted': '#6b7686',
    'accent': '#2f6fed',
    'accent_dark': '#2457bf',
    'danger': '#e0483e',
    'danger_dark': '#b8362d',
    'success': '#2f9e5c',
    'row_alt': '#f5f7fb',
}

FONT_BASE = ('Segoe UI', 10)
FONT_BOLD = ('Segoe UI', 10, 'bold')
FONT_HEAD = ('Segoe UI', 13, 'bold')
FONT_BRAND = ('Segoe UI', 14, 'bold')


def setup_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    root.configure(bg=COLORS['bg'])

    style.configure('TFrame', background=COLORS['bg'])
    style.configure('Card.TFrame', background=COLORS['card'])
    style.configure('Sidebar.TFrame', background=COLORS['sidebar'])

    style.configure('Brand.TLabel', background=COLORS['sidebar'], foreground='#ffffff',
                     font=FONT_BRAND)
    style.configure('BrandSub.TLabel', background=COLORS['sidebar'], foreground=COLORS['sidebar_muted'],
                     font=('Segoe UI', 8))
    style.configure('Heading.TLabel', background=COLORS['bg'], foreground=COLORS['text'], font=FONT_HEAD)
    style.configure('Muted.TLabel', background=COLORS['bg'], foreground=COLORS['muted'], font=FONT_BASE)
    style.configure('CardMuted.TLabel', background=COLORS['card'], foreground=COLORS['muted'], font=FONT_BASE)

    style.configure('Nav.TButton', background=COLORS['sidebar'], foreground=COLORS['sidebar_text'],
                     font=FONT_BASE, borderwidth=0, focusthickness=0, padding=(14, 10), anchor='w')
    style.map('Nav.TButton',
              background=[('active', COLORS['sidebar_hover'])],
              foreground=[('active', '#ffffff')])

    style.configure('NavActive.TButton', background=COLORS['sidebar_active'], foreground='#ffffff',
                     font=FONT_BOLD, borderwidth=0, focusthickness=0, padding=(14, 10), anchor='w')
    style.map('NavActive.TButton', background=[('active', COLORS['sidebar_active'])])

    style.configure('Accent.TButton', background=COLORS['accent'], foreground='#ffffff',
                     font=FONT_BOLD, borderwidth=0, focusthickness=0, padding=(14, 8))
    style.map('Accent.TButton', background=[('active', COLORS['accent_dark']), ('disabled', '#9db8f2')])

    style.configure('Secondary.TButton', background=COLORS['card'], foreground=COLORS['text'],
                     font=FONT_BASE, borderwidth=1, relief='solid', padding=(12, 7))
    style.map('Secondary.TButton', background=[('active', COLORS['row_alt'])])

    style.configure('Path.TEntry', fieldbackground=COLORS['card'], foreground=COLORS['text'],
                     bordercolor=COLORS['border'], lightcolor=COLORS['border'], darkcolor=COLORS['border'],
                     borderwidth=1, relief='solid', padding=(10, 0))
    style.map('Path.TEntry', foreground=[('readonly', COLORS['muted'])],
              fieldbackground=[('readonly', COLORS['card'])])

    style.configure('Company.TCombobox', fieldbackground=COLORS['card'], foreground=COLORS['text'],
                     bordercolor=COLORS['border'], lightcolor=COLORS['border'], darkcolor=COLORS['border'],
                     borderwidth=1, relief='solid', arrowsize=14, padding=(10, 6))

    style.configure('Danger.TButton', background=COLORS['sidebar'], foreground='#ff8a80',
                     font=FONT_BASE, borderwidth=0, focusthickness=0, padding=(14, 10), anchor='w')
    style.map('Danger.TButton', background=[('active', COLORS['danger'])], foreground=[('active', '#ffffff')])

    style.configure('DangerSolid.TButton', background=COLORS['danger'], foreground='#ffffff',
                     font=FONT_BOLD, borderwidth=0, focusthickness=0, padding=(14, 8))
    style.map('DangerSolid.TButton',
              background=[('active', COLORS['danger_dark']), ('disabled', '#efb1ac')])

    style.configure('Treeview', background=COLORS['card'], fieldbackground=COLORS['card'],
                     foreground=COLORS['text'], rowheight=27, font=FONT_BASE, borderwidth=0)
    style.configure('Treeview.Heading', font=FONT_BOLD, background='#eef1f6',
                     foreground=COLORS['text'], relief='flat', padding=(6, 6))
    style.map('Treeview.Heading', background=[('active', '#e4e9f2')])
    style.map('Treeview', background=[('selected', COLORS['accent'])],
              foreground=[('selected', '#ffffff')])

    style.configure('Pill.TButton', background=COLORS['row_alt'], foreground=COLORS['muted'],
                     font=('Segoe UI', 10, 'bold'), borderwidth=0, focusthickness=0, padding=(16, 8))
    style.map('Pill.TButton', background=[('active', '#e4e9f2')], foreground=[('active', COLORS['text'])])

    style.configure('PillActive.TButton', background=COLORS['accent'], foreground='#ffffff',
                     font=('Segoe UI', 10, 'bold'), borderwidth=0, focusthickness=0, padding=(16, 8))
    style.map('PillActive.TButton', background=[('active', COLORS['accent_dark'])])

    return style


class App:
    def __init__(self, root):
        self.root = root
        self.store = None
        self._online = None
        self._busy_widgets = []
        self.current_page = 'process'
        self.nav_buttons = {}
        self.history_state = {}
        self.queue_state = {'trees': {}, 'companies': []}

        if config is not None:
            self.store = FirebaseStore(config.FIREBASE_API_KEY,
                                       config.FIREBASE_PROJECT_ID,
                                       config.FERNET_KEY)

        root.title('ebevTool – Statisztika generálás')
        root.geometry('1040x660')
        root.minsize(880, 560)

        setup_style(root)
        self._build_layout()

        if not DND_AVAILABLE:
            self.log('Figyelem: a tkinterdnd2 csomag nem elérhető, a drag&drop '
                     'nem működik — használd a Tallózás gombot. (pip install tkinterdnd2)')
        if config is None:
            self.log('Figyelem: nincs config.py — a Firebase funkciók (várakozási '
                     'sor, előzmények, aliasok) nem érhetők el. Másold le a '
                     'config.example.py-t config.py néven és töltsd ki '
                     '(lásd FIREBASE_SETUP.md).')

    # --- elrendezés ---

    def _build_layout(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill='both', expand=True)

        # --- oldalsáv ---
        sidebar = ttk.Frame(outer, style='Sidebar.TFrame', width=210)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)

        brand = ttk.Frame(sidebar, style='Sidebar.TFrame')
        brand.pack(fill='x', pady=(20, 24), padx=18)
        ttk.Label(brand, text='📊  ebevTool', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(brand, text='Statisztika generálás', style='BrandSub.TLabel').pack(anchor='w', pady=(2, 0))

        nav = ttk.Frame(sidebar, style='Sidebar.TFrame')
        nav.pack(fill='x')
        self._add_nav_button(nav, 'process', '📂  Feldolgozás', self.show_process)
        self._add_nav_button(nav, 'history', '🕒  Előzmények', self.show_history)
        self._add_nav_button(nav, 'queue', '📋  Várakozási sor', self.show_queue)

        ttk.Frame(sidebar, style='Sidebar.TFrame').pack(fill='both', expand=True)

        sep = tk.Frame(sidebar, bg=COLORS['sidebar_hover'], height=1)
        sep.pack(fill='x', padx=18, pady=(0, 8))
        reset_btn = ttk.Button(sidebar, text='🗑  Reset', style='Danger.TButton',
                               command=self.confirm_reset)
        reset_btn.pack(fill='x', padx=10, pady=(0, 18))
        self._busy_widgets.append(reset_btn)

        # --- tartalom ---
        self.content = ttk.Frame(outer)
        self.content.pack(side='left', fill='both', expand=True)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {}
        self.pages['process'] = self._build_process_page(self.content)
        self.pages['history'] = self._build_placeholder_page(self.content, '🕒  Előzmények')
        self.pages['queue'] = self._build_placeholder_page(self.content, '📋  Várakozási sor')
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky='nsew')

        # --- betöltő overlay (kerekített kártya + forgó spinner) ---
        self.loading_overlay = tk.Canvas(self.content, highlightthickness=0, bg=COLORS['bg'])
        self._loading_text = 'Betöltés...'
        self._loading_active = False
        self._spinner_angle = 0
        self._spinner_job = None
        self.loading_overlay.bind('<Configure>', lambda e: self._draw_loading_card())

        self.show_process()

    def _add_nav_button(self, parent, key, text, command):
        btn = ttk.Button(parent, text=text, style='Nav.TButton', command=command)
        btn.pack(fill='x', padx=10, pady=2)
        self.nav_buttons[key] = btn
        self._busy_widgets.append(btn)

    def _activate_nav(self, key):
        self.current_page = key
        for k, btn in self.nav_buttons.items():
            btn.configure(style='NavActive.TButton' if k == key else 'Nav.TButton')

    def _build_process_page(self, parent):
        page = ttk.Frame(parent)
        page.grid_rowconfigure(3, weight=1)
        page.grid_columnconfigure(0, weight=1)

        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky='ew', padx=24, pady=(18, 12))
        ttk.Label(header, text='Excel feldolgozás', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(header, text='Húzd ide a fájlt, vagy tallózd be — a rendszer felismeri a '
                               'céget és elkészíti a statisztikát.',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 0))

        path_row = ttk.Frame(page)
        path_row.grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 10))
        path_row.grid_columnconfigure(0, weight=1)
        self.file_path_var = tk.StringVar(value='Nincs fájl kiválasztva…')
        path_entry = ttk.Entry(path_row, textvariable=self.file_path_var, style='Path.TEntry',
                               font=FONT_BASE, state='readonly')
        path_entry.grid(row=0, column=0, sticky='ew', ipady=5)
        browse_btn = ttk.Button(path_row, text='📁  Tallózás...', style='Accent.TButton', command=self._browse)
        browse_btn.grid(row=0, column=1, padx=(10, 0))
        self._busy_widgets.append(browse_btn)

        drop_card = tk.Frame(page, bg=COLORS['card'], highlightbackground=COLORS['border'],
                             highlightthickness=1, bd=0)
        drop_card.grid(row=2, column=0, sticky='ew', padx=24, pady=(0, 14))
        self.drop_label = tk.Label(
            drop_card, text='⬇  vagy húzd ide az Excel fájlt',
            bg=COLORS['card'], fg=COLORS['muted'], font=FONT_BASE, justify='center')
        self.drop_label.pack(fill='x', padx=16, pady=14)
        if DND_AVAILABLE:
            for target in (self.drop_label, path_entry):
                target.drop_target_register(DND_FILES)
                target.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_label.dnd_bind('<<DragEnter>>', lambda e: drop_card.configure(highlightbackground=COLORS['accent']))
            self.drop_label.dnd_bind('<<DragLeave>>', lambda e: drop_card.configure(highlightbackground=COLORS['border']))

        log_card = tk.Frame(page, bg=COLORS['card'], highlightbackground=COLORS['border'],
                            highlightthickness=1, bd=0)
        log_card.grid(row=3, column=0, sticky='nsew', padx=24, pady=(0, 22))
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)
        ttk.Label(log_card, text='Napló', style='CardMuted.TLabel', font=FONT_BOLD,
                  background=COLORS['card']).grid(row=0, column=0, sticky='w', padx=14, pady=(10, 4))
        self.status = tk.Text(log_card, state='disabled', wrap='word', bd=0, bg=COLORS['card'],
                              fg=COLORS['text'], font=('Consolas', 9), padx=14, pady=6)
        scroll = ttk.Scrollbar(log_card, command=self.status.yview)
        self.status.configure(yscrollcommand=scroll.set)
        self.status.grid(row=1, column=0, sticky='nsew', padx=(0, 0), pady=(0, 10))
        scroll.grid(row=1, column=1, sticky='ns', pady=(0, 10), padx=(0, 8))

        return page

    def _build_placeholder_page(self, parent, title):
        page = ttk.Frame(parent)
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky='ew', padx=24, pady=(22, 10))
        ttk.Label(header, text=title, style='Heading.TLabel').pack(side='left')
        body = ttk.Frame(page)
        body.grid(row=1, column=0, sticky='nsew', padx=24, pady=(0, 22))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        page.header = header
        page.body = body
        return page

    def show_process(self):
        self._activate_nav('process')
        self.pages['process'].tkraise()

    # --- betöltés / háttérszál segédek ---

    def show_loading(self, text='Betöltés...'):
        self._loading_text = text
        self._loading_active = True
        self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        # tk.Canvas felülírja a .lift()-et (tag_raise-re), ezért közvetlen Tk hívással emeljük ki
        self.loading_overlay.tk.call('raise', self.loading_overlay._w)
        self._draw_loading_card()
        self._spin_tick()
        self._set_busy(True)

    def hide_loading(self):
        self._loading_active = False
        if self._spinner_job is not None:
            self.root.after_cancel(self._spinner_job)
            self._spinner_job = None
        self.loading_overlay.place_forget()
        self._set_busy(False)

    @staticmethod
    def _round_rect_points(x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    def _draw_loading_card(self):
        """A betöltő overlay statikus része: elhomályosított háttér + lebegő,
        lekerekített kártya (a spinner ívét külön a _spin_tick rajzolja újra)."""
        c = self.loading_overlay
        if not self._loading_active:
            return
        w = c.winfo_width() or self.content.winfo_width()
        h = c.winfo_height() or self.content.winfo_height()
        c.delete('static')
        c.create_rectangle(0, 0, w, h, fill='#e9ecf2', outline='', tags='static')
        cw, ch = 260, 150
        cx, cy = w / 2, h / 2
        x1, y1, x2, y2 = cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2
        c.create_polygon(*self._round_rect_points(x1 + 5, y1 + 8, x2 + 5, y2 + 8, 20),
                         smooth=True, fill='#d7dce6', outline='', tags='static')
        c.create_polygon(*self._round_rect_points(x1, y1, x2, y2, 20),
                         smooth=True, fill=COLORS['card'], outline=COLORS['border'], tags='static')
        c.create_text(cx, cy + 44, text=self._loading_text, font=FONT_BOLD,
                      fill=COLORS['text'], tags='static')
        self._spinner_center = (cx, cy - 16)

    def _spin_tick(self):
        if not self._loading_active:
            return
        c = self.loading_overlay
        c.delete('spinner')
        cx, cy = getattr(self, '_spinner_center', (0, 0))
        r = 22
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline='#e4e8f0', width=4, tags='spinner')
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=self._spinner_angle, extent=100,
                    style='arc', width=4, outline=COLORS['accent'], tags='spinner')
        self._spinner_angle = (self._spinner_angle - 10) % 360
        self._spinner_job = self.root.after(30, self._spin_tick)

    def _set_busy(self, busy):
        state = 'disabled' if busy else '!disabled'
        for w in self._busy_widgets:
            try:
                w.state([state]) if hasattr(w, 'state') else w.configure(state='disabled' if busy else 'normal')
            except tk.TclError:
                pass

    def run_async(self, work_fn, on_done, loading_text='Betöltés...'):
        self.show_loading(loading_text)

        def task():
            try:
                result = work_fn()
                self.root.after(0, lambda: self._finish_async(on_done, result, None))
            except Exception as e:
                self.root.after(0, lambda: self._finish_async(on_done, None, e))

        threading.Thread(target=task, daemon=True).start()

    def _finish_async(self, on_done, result, error):
        self.hide_loading()
        on_done(result, error)

    @staticmethod
    def _parallel_map(items, fn, max_workers=8):
        """items minden elemére lefuttatja fn-t párhuzamosan (külön szálakon),
        {item: eredmény} alakban adja vissza. Cégenkénti Firestore-hívásokhoz,
        hogy ne soros kör-utakban, hanem egyszerre fussanak."""
        if not items:
            return {}
        with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as ex:
            results = list(ex.map(fn, items))
        return dict(zip(items, results))

    # --- segédek ---

    def log(self, msg):
        self.status.configure(state='normal')
        self.status.insert('end', msg + '\n')
        self.status.see('end')
        self.status.configure(state='disabled')
        self.root.update_idletasks()

    def log_link(self, prefix, path):
        """Naplósor, ahol a fájl/mappa útvonala kattintható link (megnyitja Intézőben)."""
        self.status.configure(state='normal')
        self.status.insert('end', prefix)
        start = self.status.index('end-1c')
        self.status.insert('end', path)
        end = self.status.index('end-1c')
        self._link_counter = getattr(self, '_link_counter', 0) + 1
        tag = f'link_{self._link_counter}'
        self.status.tag_add(tag, start, end)
        self.status.tag_configure(tag, foreground=COLORS['accent'], underline=True)
        self.status.tag_bind(tag, '<Enter>', lambda e: self.status.configure(cursor='hand2'))
        self.status.tag_bind(tag, '<Leave>', lambda e: self.status.configure(cursor=''))
        self.status.tag_bind(tag, '<Button-1>', lambda e, p=path: self._open_path(p))
        self.status.insert('end', '\n')
        self.status.see('end')
        self.status.configure(state='disabled')
        self.root.update_idletasks()

    def _open_path(self, path):
        target = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            os.startfile(target)
        except Exception as e:
            messagebox.showerror('Hiba', f'Nem sikerült megnyitni:\n{e}')

    def _try_sign_in(self):
        """Szálbiztos bejelentkezés-ellenőrzés: nem nyúl UI-elemhez."""
        if not self.store:
            return False, None
        if self._online is not None:
            return self._online, None
        try:
            self.store.sign_in()
            self._online = True
            return True, None
        except FirebaseError as e:
            self._online = False
            return False, e

    def store_online(self):
        """Lazy bejelentkezés (fő szálról hívva); False, ha nincs config vagy kapcsolat."""
        online, err = self._try_sign_in()
        if err:
            self.log(f'Firebase nem érhető el: {err}')
        return online

    # --- fájl kiválasztás ---

    def _browse(self):
        path = filedialog.askopenfilename(
            title='Excel fájl kiválasztása',
            filetypes=[('Excel fájlok', '*.xlsx'), ('Minden fájl', '*.*')])
        if path:
            self.file_path_var.set(path)
            self.process_file(path)

    def _on_drop(self, event):
        data = event.data.strip()
        if data.startswith('{'):
            path = data[1:data.index('}')]
        else:
            path = data.split()[0] if ' ' in data and not os.path.exists(data) else data
        self.file_path_var.set(path)
        self.process_file(path)

    # --- cégfelismerés ---

    def known_companies(self):
        """Korábban megismert cégek (helyi + Firestore aliasok alapján), rendezve.

        Szálbiztos: nem nyúl UI-elemhez, ezért háttérszálról is hívható."""
        companies = set(filename_utils.load_local_aliases().values())
        online, _ = self._try_sign_in()
        if online:
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
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)
        ttk.Label(dlg, text='🏢', font=('Segoe UI', 22), background=COLORS['card']).pack(pady=(20, 4))
        ttk.Label(dlg, text=f'Nem ismerhető fel a cég a fájlnévből:\n{filename}',
                  background=COLORS['card'], foreground=COLORS['muted'], justify='center',
                  font=FONT_BASE).pack(padx=24)
        ttk.Label(dlg, text='Add meg vagy válaszd ki a céget:', background=COLORS['card'],
                  font=FONT_BOLD).pack(padx=24, pady=(10, 6))
        var = tk.StringVar()
        combo = ttk.Combobox(dlg, textvariable=var, values=self.known_companies(), width=32,
                             style='Company.TCombobox', font=('Segoe UI', 11))
        combo.pack(padx=24, ipady=3)
        combo.focus_set()

        def choose():
            value = var.get().strip()
            if value:
                result['company'] = value
            dlg.destroy()

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=18)
        ttk.Button(btns, text='Mégse', style='Secondary.TButton', command=dlg.destroy).pack(side='left', padx=6)
        ttk.Button(btns, text='OK', style='Accent.TButton', command=choose).pack(side='left', padx=6)
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
            ctx = self._process_file_prepare(path)
        except Exception as e:
            self.log(f'HIBA: {e}')
            messagebox.showerror('Hiba', f'A feldolgozás nem sikerült:\n{e}')
            return
        if ctx is None:
            return
        self.run_async(
            lambda: self._process_file_async(ctx),
            lambda result, error: self._process_file_finish(ctx, result, error),
            'Feldolgozás és mentés...')

    def _process_file_prepare(self, path):
        """Fő szálon fut: fájlbeolvasás, cégfelismerés, megerősítő párbeszédek.
        Visszaadja a háttérszálnak szükséges kontextust, vagy None-t megszakításkor."""
        self._online = None  # kapcsolat újrapróbálása minden futásnál
        if not os.path.exists(path):
            messagebox.showerror('Hiba', f'Nem található a fájl:\n{path}')
            return None
        filename = os.path.basename(path)
        self.log(f'--- Beolvasás: {path}')

        company = self.resolve_company(path)
        if company is None:
            self.log('Megszakítva: nem lett cég kiválasztva.')
            return None
        self.log(f'Cég: {company}')

        header, data_rows = generate.read_input(path)
        problems = generate.check_header(header)
        if problems:
            msg = ('A fejléc szerkezete eltér a várttól, ellenőrizd a fájlt!\n\n'
                   + '\n'.join(problems) + '\n\nFolytatod a feldolgozást?')
            if not messagebox.askokcancel('Fejléc figyelmeztetés', msg):
                self.log('Megszakítva a fejléc-ellenőrzés után.')
                return None

        current_month_serial, current_entries, future_entries = \
            generate.extract_entries(data_rows)
        if current_month_serial is None:
            messagebox.showerror(
                'Hiba', 'Nem határozható meg a fájl hónapja (nincsenek '
                'érvényes bejelentési dátumok).')
            return None
        ym = generate.serial_to_ym(current_month_serial)
        self.log(f'A fájl hónapja (a bejelentési dátumok alapján): {ym}')

        fn_month = filename_utils.detect_month(filename)
        if fn_month and fn_month != int(ym[5:7]):
            if not messagebox.askokcancel(
                    'Hónap eltérés',
                    f'A fájlnévben szereplő hónap ({fn_month}.) eltér az '
                    f'adatokból számítottól ({ym}). Folytatod?'):
                self.log('Megszakítva hónap-eltérés miatt.')
                return None

        if months_between(ym, ym_today()) > 6:
            if not messagebox.askokcancel(
                    'Régi hónap',
                    'Ez a hónap több mint fél éve volt esedékes, a hozzá tartozó '
                    'átvitt adatok időközben véglegesen törlődtek — a kimenet '
                    'emiatt hiányos lehet. Folytatod?'):
                self.log('Megszakítva.')
                return None

        return {
            'path': path, 'filename': filename, 'company': company,
            'header': header, 'data_rows': data_rows,
            'current_entries': current_entries, 'future_entries': future_entries,
            'ym': ym,
        }

    def _process_file_async(self, ctx):
        """Háttérszálon fut: nem nyúl UI-elemhez, csak naplósorokat gyűjt."""
        logs = []
        online, err = self._try_sign_in()
        records = []
        if online:
            try:
                records = self.store.load_memory(ctx['company'])
            except FirebaseError as e:
                online = False
                logs.append(('text', f'Firestore olvasás sikertelen: {e}'))
        no_connection = not online
        if no_connection:
            logs.append(('text', 'Feldolgozás Firestore nélkül (hiányos lehet).'))

        carried = []
        to_consume = []
        for rec in records:
            entry_ym = generate.serial_to_ym(
                generate.serial_to_month_serial(rec['entry']['start_serial']))
            if rec['status'] == 'pending' and entry_ym <= ctx['ym']:
                carried.append(rec['entry'])
                to_consume.append(rec['id'])
            elif rec['status'] == 'consumed' and rec['consumed_in'] == ctx['ym']:
                carried.append(rec['entry'])

        entries = generate.merge_entries(ctx['current_entries'], carried)
        logs.append(('text', f"Rekordok a fájlból: {len(ctx['current_entries'])}, átvitt: {len(carried)}, "
                             f"jövő hónapra: {len(ctx['future_entries'])}"))

        output_file = generate.generate_output(ctx['path'], ctx['header'], ctx['data_rows'], entries)
        logs.append(('link', 'Kész! Kimenet: ', output_file))

        try:
            dest_dir = os.path.join(default_archive_dir(),
                                    filename_utils.safe_folder_name(ctx['company']), ctx['ym'])
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(output_file, dest_dir)
            logs.append(('link', 'Archiválva: ', os.path.join(dest_dir, os.path.basename(output_file))))
        except Exception as e:
            logs.append(('text', f'Az archiválás nem sikerült: {e}'))

        firestore_warning = None
        if online:
            try:
                self.store.sync_processing(ctx['company'], ctx['future_entries'], to_consume,
                                           ctx['ym'], ctx['filename'])
                deleted = self.store.cleanup_expired(ctx['company'])
                if deleted:
                    logs.append(('text', f'Takarítás: {deleted} lejárt rekord véglegesen törölve.'))
                logs.append(('text', f"Várakozási sor frissítve ({len(ctx['future_entries'])} mentve, "
                                     f"{len(to_consume)} felhasználva)."))
            except FirebaseError as e:
                firestore_warning = str(e)
                logs.append(('text', f'Firestore írás sikertelen: {e}'))

        return {'logs': logs, 'no_connection': no_connection, 'firestore_warning': firestore_warning}

    def _process_file_finish(self, ctx, result, error):
        if error:
            self.log(f'HIBA: {error}')
            messagebox.showerror('Hiba', f'A feldolgozás nem sikerült:\n{error}')
            return
        for item in result['logs']:
            if item[0] == 'text':
                self.log(item[1])
            else:
                self.log_link(item[1], item[2])
        if result.get('no_connection'):
            messagebox.showwarning(
                'Nincs kapcsolat',
                'A Firestore nem érhető el. A statisztika a korábbi hónapokból '
                'átvitt rekordok NÉLKÜL készül el, és a jövő hónapra szóló '
                'rekordok nem kerülnek mentésre!')
        if result.get('firestore_warning'):
            messagebox.showwarning(
                'Firestore hiba',
                f"A statisztika elkészült, de a várakozási sor frissítése "
                f"nem sikerült:\n{result['firestore_warning']}")

    # --- Előzmények nézet (beágyazott, nem külön ablak) ---

    def show_history(self):
        self._activate_nav('history')
        page = self.pages['history']
        page.tkraise()
        if not self.store:
            self._render_page_message(page, 'Nincs beállítva Firebase-kapcsolat (config.py hiányzik).')
            return

        def work():
            online, err = self._try_sign_in()
            if not online:
                return {'online': False, 'error': err}
            companies = self.known_companies()
            data = self._parallel_map(companies, self.store.load_history)
            return {'online': True, 'companies': companies, 'data': data}

        self.run_async(work, self._on_history_loaded, 'Előzmények betöltése...')

    def _on_history_loaded(self, result, error):
        page = self.pages['history']
        if error:
            self._render_page_message(page, f'Hiba az előzmények betöltésekor: {error}')
            return
        if not result['online']:
            extra = f' ({result["error"]})' if result.get('error') else ''
            self._render_page_message(page, f'A Firestore nem érhető el.{extra}')
            return
        companies, data = result['companies'], result['data']
        if not companies:
            self._render_page_message(page, 'Még nincs egyetlen ismert cég sem.')
            return
        self._clear_body(page)
        frames, _, _ = self._build_company_switcher(page.body, companies)
        for company in companies:
            tree = self._make_tree(frames[company], ('processed',),
                                   {'#0': ('Év-hónap / fájlnév', 300), 'processed': ('Feldolgozva', 200)})
            groups = {}
            for row in data[company]:
                groups.setdefault(row.get('year_month', '?'), []).append(row)
            for i, ym in enumerate(sorted(groups, reverse=True)):
                node = tree.insert('', 'end', text=ym, open=True,
                                   tags=('odd' if i % 2 else 'even',))
                for row in sorted(groups[ym], key=lambda r: r.get('processed_at', '')):
                    processed = (row.get('processed_at') or '')[:19].replace('T', ' ')
                    tree.insert(node, 'end', text=row.get('filename', '?'), values=(processed,))

    # --- Várakozási sor / Böngésző nézet (beágyazott, nem külön ablak) ---

    def show_queue(self):
        self._activate_nav('queue')
        page = self.pages['queue']
        page.tkraise()
        if not self.store:
            self._render_page_message(page, 'Nincs beállítva Firebase-kapcsolat (config.py hiányzik).')
            return

        def work():
            online, err = self._try_sign_in()
            if not online:
                return {'online': False, 'error': err}
            companies = self.known_companies()
            data = self._parallel_map(companies, self.store.load_memory)
            return {'online': True, 'companies': companies, 'data': data}

        self.run_async(work, self._on_queue_loaded, 'Várakozási sor betöltése...')

    def _on_queue_loaded(self, result, error):
        page = self.pages['queue']
        if error:
            self._render_page_message(page, f'Hiba a várakozási sor betöltésekor: {error}')
            return
        if not result['online']:
            extra = f' ({result["error"]})' if result.get('error') else ''
            self._render_page_message(page, f'A Firestore nem érhető el.{extra}')
            return
        companies, data = result['companies'], result['data']
        if not companies:
            self._render_page_message(page, 'Még nincs egyetlen ismert cég sem.')
            return
        self._clear_body(page)
        self.queue_state = {'trees': {}, 'companies': companies}

        frames, _, switcher_state = self._build_company_switcher(page.body, companies)
        self.queue_state['switcher_state'] = switcher_state
        cols = {'#0': ('Év-hónap / név', 220), 'start': ('Kezdés', 100), 'days': ('Munkanapok', 90),
                'status': ('Státusz', 100), 'consumed': ('Felhasználva (hónap)', 130)}
        for company in companies:
            tree = self._make_tree(frames[company], ('start', 'days', 'status', 'consumed'), cols)
            self.queue_state['trees'][company] = tree
            self._fill_queue_tree(tree, data[company])

        btns = ttk.Frame(page.body)
        btns.pack(fill='x', pady=(10, 0))
        del_btn = ttk.Button(btns, text='🗑  Kijelölt törlése', style='Secondary.TButton',
                             command=self._delete_selected)
        del_btn.pack(side='left')
        ttk.Button(btns, text='🔄  Frissítés', style='Secondary.TButton',
                  command=self.show_queue).pack(side='left', padx=8)

    def _fill_queue_tree(self, tree, records):
        tree.delete(*tree.get_children())
        groups = {}
        for rec in records:
            ym = generate.serial_to_ym(generate.serial_to_month_serial(rec['entry']['start_serial']))
            groups.setdefault(ym, []).append(rec)
        for i, ym in enumerate(sorted(groups, reverse=True)):
            node = tree.insert('', 'end', text=ym, open=True, tags=('odd' if i % 2 else 'even',))
            for rec in sorted(groups[ym], key=lambda r: r['entry']['nev'].lower()):
                e = rec['entry']
                status = 'függőben' if rec['status'] == 'pending' else 'felhasználva'
                tree.insert(node, 'end', iid=f"{rec['id']}",
                            text=e['nev'],
                            values=(generate.serial_to_iso(e['start_serial']),
                                    e['munkanapok'], status, rec['consumed_in'] or ''))

    def _delete_selected(self):
        company = self.queue_state['switcher_state']['active']
        tree = self.queue_state['trees'][company]
        selected = [i for i in tree.selection() if tree.parent(i)]
        if not selected:
            messagebox.showinfo('Törlés', 'Válassz ki egy rekordot a listából.')
            return
        if not messagebox.askyesno(
                'Törlés megerősítése',
                f'{len(selected)} rekord VÉGLEGESEN törlődik a várakozási '
                'sorból. Biztos vagy benne?'):
            return

        def work():
            for doc_id in selected:
                self.store.delete_record(company, doc_id)
            return self.store.load_memory(company)

        def done(records, error):
            if error:
                messagebox.showerror('Hiba', f'Törlés sikertelen: {error}')
                return
            self._fill_queue_tree(tree, records)

        self.run_async(work, done, 'Törlés...')

    # --- lapon belüli segédek ---

    def _clear_body(self, page):
        for w in page.body.winfo_children():
            w.destroy()

    def _render_page_message(self, page, text):
        self._clear_body(page)
        wrap = ttk.Frame(page.body)
        wrap.place(relx=0.5, rely=0.4, anchor='center')
        ttk.Label(wrap, text='ℹ️', font=('Segoe UI', 24), background=COLORS['bg']).pack()
        ttk.Label(wrap, text=text, style='Muted.TLabel', wraplength=420, justify='center').pack(pady=(8, 0))

    def _build_company_switcher(self, body, companies):
        """Pill-gombsor a cégek közti váltáshoz — a natív Notebook fül helyett,
        hogy a jóváhagyott oldalsáv-navigációval egységes, letisztultabb hangulatot adjon.
        Visszaadja: (cégenkénti tartalom-frame dict, kijelölő függvény, {'active': ...} állapot)."""
        bar_wrap = tk.Frame(body, bg=COLORS['bg'])
        bar_wrap.pack(fill='x', pady=(0, 12))
        bar = ttk.Frame(bar_wrap)
        bar.pack(anchor='w')
        holder = ttk.Frame(body)
        holder.pack(fill='both', expand=True)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)

        buttons = {}
        frames = {}
        state = {'active': None}

        def select(company):
            state['active'] = company
            for c, b in buttons.items():
                b.configure(style='PillActive.TButton' if c == company else 'Pill.TButton')
            frames[company].tkraise()

        for company in companies:
            btn = ttk.Button(bar, text=company, style='Pill.TButton',
                             command=lambda c=company: select(c))
            btn.pack(side='left', padx=(0, 8))
            buttons[company] = btn
            frame = ttk.Frame(holder, style='Card.TFrame')
            frame.grid(row=0, column=0, sticky='nsew')
            frames[company] = frame

        select(companies[0])
        return frames, select, state

    def _make_tree(self, parent, extra_cols, col_spec):
        wrap = tk.Frame(parent, bg=COLORS['card'])
        wrap.pack(fill='both', expand=True, padx=12, pady=12)
        tree = ttk.Treeview(wrap, columns=extra_cols)
        for key, (label, width) in col_spec.items():
            tree.heading(key, text=label)
            tree.column(key, width=width)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        tree.tag_configure('odd', background=COLORS['row_alt'])
        tree.tag_configure('even', background=COLORS['card'])
        return tree

    # --- Reset ---

    def confirm_reset(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('Nullázás megerősítése')
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text='⚠️', font=('Segoe UI', 26), background=COLORS['card']).pack(pady=(20, 4))
        ttk.Label(dlg, text='Ez a művelet véglegesen törli az alábbiakat:',
                  background=COLORS['card'], font=FONT_BOLD).pack(padx=24)
        items = ('•  Helyi alias-cache (aliases.json)\n'
                 '•  Az állapot napló tartalma\n'
                 '•  A Firestore teljes várakozási sora és előzményei\n'
                 '   (MINDEN ismert cégnél)')
        ttk.Label(dlg, text=items, background=COLORS['card'], foreground=COLORS['muted'],
                  justify='left', font=FONT_BASE).pack(padx=24, pady=(8, 4), anchor='w')
        ttk.Label(dlg, text='A művelet nem vonható vissza.', background=COLORS['card'],
                  foreground=COLORS['danger'], font=FONT_BOLD).pack(padx=24, pady=(2, 10))

        ttk.Label(dlg, text='A megerősítéshez írd be: TÖRLÉS', background=COLORS['card'],
                  font=FONT_BASE).pack(padx=24)
        var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=var, width=20, justify='center')
        entry.pack(pady=(4, 14))
        entry.focus_set()

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(0, 20))
        confirm_btn = ttk.Button(btns, text='Végleges törlés', style='DangerSolid.TButton')
        confirm_btn.state(['disabled'])

        def on_change(*_):
            if var.get().strip().upper() == 'TÖRLÉS':
                confirm_btn.state(['!disabled'])
            else:
                confirm_btn.state(['disabled'])

        var.trace_add('write', on_change)

        def do_confirm():
            dlg.destroy()
            self._perform_reset()

        ttk.Button(btns, text='Mégse', style='Secondary.TButton', command=dlg.destroy).pack(side='left', padx=6)
        confirm_btn.configure(command=do_confirm)
        confirm_btn.pack(side='left', padx=6)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    def _perform_reset(self):
        def wipe_company(c):
            self.store.delete_all_memory(c)
            self.store.delete_all_history(c)

        def work():
            online, err = self._try_sign_in()
            done_companies = []
            if online:
                companies = self.known_companies()
                self._parallel_map(companies, wipe_company)
                done_companies = companies
            return {'online': online, 'error': err, 'companies': done_companies}

        self.run_async(work, self._on_reset_done, 'Nullázás folyamatban...')

    def _on_reset_done(self, result, error):
        filename_utils.reset_local_aliases()
        self.status.configure(state='normal')
        self.status.delete('1.0', 'end')
        self.status.configure(state='disabled')
        self._online = None

        if error:
            self.log(f'Nullázás közben hiba történt: {error}')
            messagebox.showerror('Hiba', f'A nullázás nem sikerült teljesen:\n{error}')
            return

        if not result['online']:
            self.log('Helyi adatok törölve. A Firestore nem volt elérhető, a felhő adatai nem törlődtek.')
            messagebox.showwarning(
                'Részleges nullázás',
                'A helyi adatok (alias-cache, napló) törlődtek, de a Firestore nem volt '
                'elérhető — a felhőben tárolt várakozási sor és előzmények megmaradtak.')
        else:
            n = len(result['companies'])
            self.log(f'Nullázás kész: {n} cég felhő-adatai és a helyi cache törölve.')
            messagebox.showinfo('Kész', 'Minden kiválasztott adat nullázva.')

        if self.current_page == 'history':
            self.show_history()
        elif self.current_page == 'queue':
            self.show_queue()


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:
        root.after(200, lambda: app.process_file(sys.argv[1]))
    root.mainloop()


if __name__ == '__main__':
    main()
