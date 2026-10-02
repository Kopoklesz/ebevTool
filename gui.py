import getpass
import json
import os
import platform
import shutil
import sys
import threading
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from cryptography.fernet import Fernet
import webbrowser

import archive_import
import generate
import normalize
import worklog
import filename_utils
import dpapi_crypto
import updater
from dpapi_crypto import DPAPIError
from firebase_store import (ConflictError, FirebaseError, FirebaseStore,
                            entry_doc_id, months_between, ym_today)
from version import RELEASES_PAGE, __version__

CONFIG_FIELDS = ('FIREBASE_API_KEY', 'FIREBASE_PROJECT_ID', 'FERNET_KEY', 'ARCHIVE_DIR')


def config_path():
    # A korábbi verziók az .exe mellé írtak; egyszeri átköltöztetés után a
    # titkosított beállítás a felhasználói adatmappában él.
    filename_utils.migrate_legacy_file('config.dat', filename_utils.user_data_dir())
    return os.path.join(filename_utils.user_data_dir(), 'config.dat')


def _legacy_config_py_path():
    """A régi, olvasható config.py — forrásból futtatva még használatban lehet."""
    for folder in (filename_utils.user_data_dir(), filename_utils.app_dir()):
        path = os.path.join(folder, 'config.py')
        if os.path.exists(path):
            return path
    return os.path.join(filename_utils.app_dir(), 'config.py')


def _load_legacy_plaintext_config():
    path = _legacy_config_py_path()
    if not os.path.exists(path):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('ebevtool_legacy_config', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {k: getattr(module, k, None) for k in CONFIG_FIELDS}
    except Exception:
        return None


def save_runtime_config(data: dict):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    encrypted = dpapi_crypto.protect(raw)
    with open(config_path(), 'wb') as f:
        f.write(encrypted)


def load_runtime_config():
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, 'rb') as f:
                encrypted = f.read()
            raw = dpapi_crypto.unprotect(encrypted)
            data = json.loads(raw.decode('utf-8'))
            return SimpleNamespace(**{k: data.get(k) for k in CONFIG_FIELDS})
        except Exception:
            return None

    legacy = _load_legacy_plaintext_config()
    if legacy is not None:
        try:
            save_runtime_config(legacy)
            os.remove(_legacy_config_py_path())
        except Exception:
            pass
        return SimpleNamespace(**legacy)

    return None


config = load_runtime_config()


FIRESTORE_RULES = """rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /companies/{company}/{document=**} {
      allow read, write: if request.auth != null;
    }
    match /company_aliases/{token} {
      allow read, write: if request.auth != null;
    }
    match /persons/{taj} {
      allow read, write: if request.auth != null;
    }
  }
}"""

FIREBASE_CONSOLE_URL = 'https://console.firebase.google.com/'

# A Személyek nézet füle a régi, minden cégre közös személylistának.
LEGACY_PERSONS_TAB = '📦 Régi közös lista'

# Az ismeretlen-személy dialógus jelzése: a hátralévőket se kérdezze meg.
SKIP_ALL = object()


def default_archive_dir():
    """A kimeneti fájlok archívuma.

    Alapból a Dokumentumok alá kerül: ezeket a felhasználó meg akarja találni
    és megnyitni, ezért nem való rejtett alkalmazás-adatok közé — és végképp
    nem az .exe mellé.

    A korábbi verziók az .exe mellé archiváltak. Az ott lévő mappát nem
    mozgatjuk (nagy lehet, és lehet rá hivatkozás), de ha létezik és a
    Beállításokban nincs megadva más, továbbra is azt használjuk — így a
    frissítés nem szakítja ketté a meglévő archívumot.
    """
    configured = getattr(config, 'ARCHIVE_DIR', None) if config else None
    if configured:
        return configured
    legacy = os.path.join(filename_utils.app_dir(), 'archívum')
    if os.path.isdir(legacy):
        return legacy
    return os.path.join(filename_utils.documents_dir(), 'ebevTool archívum')


def machine_label():
    """Felhasználó/gép azonosító a 'ki dolgozta fel' jelzéshez.

    Nem hitelesített adat (a Firebase-bejelentkezés anonim) — csak arra jó,
    hogy a figyelmeztetésben emberi név szerepeljen.
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = '?'
    try:
        host = platform.node() or '?'
    except Exception:
        host = '?'
    return f'{user} / {host}'


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
        self.update_available = None

        self.persons_state = {}
        self.worklog_cache = None  # a munkanapló, első használatkor töltődik be
        self.worklog_missing = {}
        self._init_store()

        root.title('ebevTool – Statisztika generálás')
        root.geometry('1040x660')
        root.minsize(880, 560)

        setup_style(root)
        self._build_layout()

        if not DND_AVAILABLE:
            self.log('Figyelem: a drag&drop '
                     'nem működik — használd a Tallózás gombot.')
        if config is None:
            self.log('Figyelem: nincsenek elmentve Firebase-adatok — a Firebase '
                     'funkciók nem érhetők '
                     'el. Töltsd ki az oldalsávon a ⚙ Beállítások ablakot.')

    def _init_store(self):
        global config
        config = load_runtime_config()
        self._online = None
        if config is not None:
            self.store = FirebaseStore(config.FIREBASE_API_KEY,
                                       config.FIREBASE_PROJECT_ID,
                                       config.FERNET_KEY)
        else:
            self.store = None

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
        self.version_label = ttk.Label(brand, text=f'v{__version__}', style='BrandSub.TLabel')
        self.version_label.pack(anchor='w')

        nav = ttk.Frame(sidebar, style='Sidebar.TFrame')
        nav.pack(fill='x')
        self._add_nav_button(nav, 'process', '📂  Feldolgozás', self.show_process)
        self._add_nav_button(nav, 'history', '🕒  Előzmények', self.show_history)
        self._add_nav_button(nav, 'queue', '📋  Várakozási sor', self.show_queue)
        self._add_nav_button(nav, 'persons', '👤  Személyek', self.show_persons)

        ttk.Frame(sidebar, style='Sidebar.TFrame').pack(fill='both', expand=True)

        self.update_btn = ttk.Button(sidebar, text='🔄  Frissítés', style='Nav.TButton',
                                     command=self.open_update)
        self.update_btn.pack(fill='x', padx=10, pady=(0, 2))
        self._busy_widgets.append(self.update_btn)

        settings_btn = ttk.Button(sidebar, text='⚙  Beállítások', style='Nav.TButton',
                                  command=self.open_settings)
        settings_btn.pack(fill='x', padx=10, pady=(0, 2))
        self._busy_widgets.append(settings_btn)

        sep = tk.Frame(sidebar, bg=COLORS['sidebar_hover'], height=1)
        sep.pack(fill='x', padx=18, pady=(8, 8))
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
        self.pages['persons'] = self._build_placeholder_page(self.content, '👤  Személyek')
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
                               'céget és elkészíti a sablont.',
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
            # Az archívum csak az első feldolgozáskor jön létre; a Beállításokból
            # viszont már előtte is megnyithatónak kell lennie.
            os.makedirs(target, exist_ok=True)
            os.startfile(target)
        except Exception as e:
            messagebox.showerror('Hiba', f'Nem sikerült megnyitni:\n{e}')

    def _try_sign_in(self):
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
        companies = set(filename_utils.load_local_aliases().values())
        online, _ = self._try_sign_in()
        if online:
            try:
                companies.update(self.store.list_companies())
            except FirebaseError:
                pass
        return sorted(c for c in companies if c)

    def ask_company_dialog(self, filename):
        result = {'company': None}
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
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

        # A személyeket és az előzményeket egy menetben töltjük: háttérszálon
        # nem nyitható dialógus, ezért minden Firestore-olvasás ide kerül, és a
        # kérdések a főszálon futó callbackben jelennek meg.
        self.run_async(
            lambda: self._load_context_work(ctx),
            lambda loaded, error: self._on_context_loaded(loaded, error, ctx),
            'Adatok betöltése...')

    def _load_context_work(self, ctx):
        """A cég személyei, a régi közös személylista és a cég adott havi előzményei."""
        result = {'online': False, 'persons': {}, 'legacy_persons': {}, 'history': [],
                  'processed_months': set()}
        if not self.store:
            return result
        online, _ = self._try_sign_in()
        if not online:
            return result
        try:
            result['persons'] = self.store.load_persons(ctx['company'])
            # Csak akkor kérdezünk és mentünk személyt, ha a cég listáját
            # ténylegesen be tudtuk olvasni — különben mindenki ismeretlennek
            # látszana, és a válaszok felülírnák a meglévő adatlapokat.
            result['online'] = True
        except Exception:
            result['persons'] = {}
        try:
            result['legacy_persons'] = self.store.load_persons(None)
        except Exception:
            result['legacy_persons'] = {}
        try:
            history = self.store.load_history(ctx['company'])
            result['history'] = [row for row in history if row.get('year_month') == ctx['ym']]
            # a már feldolgozott hónapok: egy korábbi hónap javítása ezeket is érintheti
            result['processed_months'] = {row.get('year_month') for row in history
                                          if row.get('year_month')}
        except Exception:
            result['history'] = []
        return result

    def _on_context_loaded(self, loaded, error, ctx):
        loaded = loaded or {}
        ctx['persons'] = dict(loaded.get('persons') or {})
        ctx['legacy_persons'] = loaded.get('legacy_persons') or {}
        ctx['persons_online'] = bool(loaded.get('online'))
        ctx['processed_months'] = loaded.get('processed_months') or set()

        previous = loaded.get('history') or []
        if previous and not self._confirm_reprocess(ctx, previous):
            self.log('Megszakítva: ezt a hónapot már feldolgozták.')
            return

        self._process_file_check_persons(ctx)

    def _confirm_reprocess(self, ctx, previous):
        """Figyelmeztetés, ha a cég adott hónapja már fel lett dolgozva.

        Nem zárolás: ha ketten pontosan egyszerre indítanak, mindkettő átcsúszhat.
        A gyakorlati esetet (valaki ma, valaki holnap) viszont megfogja.
        """
        latest = max(previous, key=lambda r: r.get('processed_at') or '')
        when = (latest.get('processed_at') or '')[:19].replace('T', ' ')
        who = latest.get('created_by')

        lines = [f"Cég:\t{ctx['company']}", f"Hónap:\t{ctx['ym']}",
                 f"Készült:\t{when}" + (f'  ({who})' if who else '')]
        if len(previous) > 1:
            lines.append(f'Korábbi feldolgozások száma: {len(previous)}')

        return messagebox.askokcancel(
            'Ezt a hónapot már feldolgozták',
            'Ez a cég-hónap már szerepel az előzményekben:\n\n'
            + '\n'.join(lines)
            + '\n\nHa folytatod, új verzió készül — a korábbi megmarad.\n'
              'Folytatod a feldolgozást?',
            icon='warning')

    def _process_file_check_persons(self, ctx):
        if not ctx.get('persons_online'):
            # Kapcsolat nélkül a cég személylistája nem olvasható, és a beírt
            # adatokat menteni sem tudnánk: minden dolgozóra feleslegesen
            # rákérdeznénk. Az adatlapok ilyenkor kitöltetlenek maradnak.
            self.log('A személylista nem érhető el: a személyi adatlapok '
                     'kitöltetlenek maradnak, és senkire nem kérdezünk rá.')
            ctx['new_persons'] = []
            self.run_async(
                lambda: self._process_file_async(ctx),
                lambda result, error: self._process_file_finish(ctx, result, error),
                'Feldolgozás és mentés...')
            return
        persons = ctx['persons']
        legacy = ctx['legacy_persons']
        all_entries = ctx['current_entries'] + ctx['future_entries']
        seen = set()
        unknown_entries = []
        # (adatlap, régi dokumentumazonosító): régi, TAJ-alapú adatlapok,
        # amik most megkapják az adóazonosítót (és vele az új azonosítót)
        upgraded = []
        for entry in all_entries:
            ado, taj = entry.get('adoazonosito', ''), entry.get('taj', '')
            ident = generate.ado_key(ado) or 'taj:' + generate.taj_key(taj)
            if ident == 'taj:' or ident in seen:
                continue
            seen.add(ident)
            key, person = generate.find_person(persons, ado, taj)
            if person is None:
                unknown_entries.append(entry)
            elif generate.ado_key(ado) and not generate.ado_key(person.get('adoazonosito')):
                updated = dict(person, adoazonosito=ado)
                del persons[key]
                persons[FirebaseStore.person_doc_id(updated)] = updated
                upgraded.append((updated, key))
            elif generate.taj_key(taj) and generate.taj_key(person.get('taj')) != generate.taj_key(taj):
                # Az adóazonosító egyezik, a TAJ nem: valószínűleg elírás. A
                # kimenetbe a fájl TAJ-a kerül, az adatlap nem változik.
                self.log(f"Figyelem: {entry['nev']} ({ado}) — a fájlban a TAJ {normalize.normalize_taj(taj)}, "
                         f"az adatlapon {normalize.normalize_taj(person.get('taj')) or '(üres)'}. Az adóazonosító "
                         'alapján ugyanannak a személynek vettük; ha az adatlap a hibás, '
                         'javítsd a Személyek oldalon.')

        new_persons = []
        adopted = 0
        asked = 0
        skip_rest = False
        legacy_match = {id(e): generate.find_person(legacy, e['adoazonosito'], e['taj'])[1]
                        for e in unknown_entries}
        # ennyi kérdés jön (a régi listából átvettekre nem kérdezünk)
        to_ask = sum(1 for e in unknown_entries if legacy_match[id(e)] is None)
        for entry in unknown_entries:
            if legacy_match[id(entry)] is not None:
                # A régi, közös személylistában már megvan: rákérdezés nélkül
                # átvesszük ennek a cégnek a listájába.
                person_data = dict(legacy_match[id(entry)])
                if not generate.ado_key(person_data.get('adoazonosito')):
                    person_data['adoazonosito'] = entry['adoazonosito']
                adopted += 1
            elif skip_rest:
                # „Összes kihagyása” után már nem kérdezünk — a régi listából
                # átvehetőket (fenti ág) viszont továbbra is átvesszük.
                continue
            else:
                person_data = self._ask_person_dialog(
                    entry['nev'], entry['adoazonosito'], entry['taj'],
                    position=(asked + 1, to_ask))
                asked += 1
                if person_data is SKIP_ALL:
                    skip_rest = True
                    self.log(f'{to_ask - asked + 1} ismeretlen személy kihagyva — az '
                             'adatlapjuk kitöltetlen marad, legközelebb újra rákérdezünk.')
                    continue
            if person_data:
                persons[FirebaseStore.person_doc_id(person_data)] = person_data
                new_persons.append(person_data)

        if adopted:
            self.log(f'{adopted} személy adatai átvéve a régi közös listából '
                     f'a(z) {ctx["company"]} cég listájába.')
        ctx['new_persons'] = new_persons
        ctx['upgraded_persons'] = upgraded

        self.run_async(
            lambda: self._process_file_async(ctx),
            lambda result, error: self._process_file_finish(ctx, result, error),
            'Feldolgozás és mentés...')

    def _process_file_prepare(self, path):
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

        header, data_rows, fmt = generate.read_input(path)
        self.log(f'Felismert formátum: {fmt.label}')
        problems = generate.check_header(header, fmt)
        if problems:
            msg = ('A fejléc szerkezete eltér a várttól, ellenőrizd a fájlt!\n\n'
                   + '\n'.join(problems) + '\n\nFolytatod a feldolgozást?')
            if not messagebox.askokcancel('Fejléc figyelmeztetés', msg):
                self.log('Megszakítva a fejléc-ellenőrzés után.')
                return None

        self._log_flagged_rows(data_rows, fmt)

        row_problems = []
        withdrawn = {}
        current_month_serial, current_entries, future_entries = \
            generate.extract_entries(data_rows, fmt, problems=row_problems, withdrawn=withdrawn)
        seen_ids = set()
        for e in current_entries + future_entries:
            for value, check, what in ((e['adoazonosito'], normalize.valid_adoazonosito, 'adóazonosítója'),
                                       (e['taj'], normalize.valid_taj, 'TAJ-száma')):
                if value and (what, value) not in seen_ids and not check(value):
                    seen_ids.add((what, value))
                    self.log(f"FIGYELEM: {e['nev']} {what} ({value}) hibás ellenőrzőszámú — "
                             'valószínűleg elírás.')
        for nev, start in sorted(withdrawn.values(), key=lambda w: (w[1], w[0])):
            self.log(f'Visszavonás: {nev}, kezdés {generate.serial_to_date(start):%Y.%m.%d.} '
                     '— az előtte tett bejelentés nem számít bele.')
        if row_problems:
            for nev, problem in row_problems:
                self.log(f'FIGYELEM: {nev or "(név nélkül)"}: {problem}')
            listed = '\n'.join(f'• {nev or "(név nélkül)"}: {problem}'
                               for nev, problem in row_problems[:15])
            if len(row_problems) > 15:
                listed += f'\n… és még {len(row_problems) - 15} sor (lásd a naplót)'
            if not messagebox.askokcancel(
                    'Hibás sorok a fájlban',
                    f'{len(row_problems)} sort nem lehetett rendesen értelmezni:\n\n'
                    f'{listed}\n\nA statisztika ezek nélkül / így készül el. Folytatod?',
                    icon='warning'):
                self.log('Megszakítva a hibás sorok miatt.')
                return None
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
            'header': header, 'data_rows': data_rows, 'format': fmt,
            'current_entries': current_entries, 'future_entries': future_entries,
            'ym': ym, 'withdrawn': withdrawn,
        }

    def _log_flagged_rows(self, data_rows, fmt):
        """A kiszűrt (törölt/hibás) sorok megszámolása, a talált értékekkel együtt.

        Az új NAV-exportban nem ismert előre, milyen szöveggel jelöli a NAV a
        törölt vagy hibás rekordokat, ezért a ténylegesen előforduló eltérő
        értékeket kiírjuk a naplóba.
        """
        for label, value_fn in (('törölt', generate.torles_value),
                                ('hibás', generate.hiba_value)):
            values = {}
            for row in data_rows:
                value = value_fn(row, fmt)
                if value:
                    values[value] = values.get(value, 0) + 1
            if values:
                details = ', '.join(f'"{v}" ({n} db)' for v, n in sorted(values.items()))
                total = sum(values.values())
                self.log(f'Kiszűrve {total} {label} sor — {details}')

    def _process_file_async(self, ctx):
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
        to_withdraw = []
        to_restore = []
        stale = []
        rerun_months = set()
        future_ids = {entry_doc_id(e) for e in ctx['future_entries']}
        known_ids = {rec['id'] for rec in records}
        for e in ctx['future_entries'] if online else ():
            # Új vagy módosult áthúzódó rekord egy már feldolgozott hónapra:
            # az a hónap csak újrafuttatva veszi fel.
            e_ym = generate.serial_to_ym(generate.serial_to_month_serial(e['start_serial']))
            if entry_doc_id(e) not in known_ids and e_ym in ctx.get('processed_months', ()):
                rerun_months.add(e_ym)
        withdrawn = ctx.get('withdrawn') or {}
        for rec in records:
            entry_ym = generate.serial_to_ym(
                generate.serial_to_month_serial(rec['entry']['start_serial']))
            status = rec['status']
            # ennek a hónapnak a feldolgozása dönt róla: függő rekord, vagy amit
            # egy korábbi futás ebben a hónapban használt fel / vont vissza
            ours = status == 'pending' or (status in ('consumed', 'withdrawn')
                                           and rec['consumed_in'] == ctx['ym'])
            when = f"{generate.serial_to_date(rec['entry']['start_serial']):%Y.%m.%d.}"
            if ours and generate.is_withdrawn(rec['entry'], withdrawn):
                # Egy korábbi hónapból áthozott bejelentést ez a fájl visszavon:
                # nem számít bele. Nem töröljük, csak megjelöljük — így ha a
                # hónapot javított fájllal újra feldolgozzák, visszaállítható.
                if status != 'withdrawn':
                    to_withdraw.append((rec['id'], rec.get('version')))
                logs.append(('text', f"Áthozott bejelentés visszavonva: {rec['entry']['nev']}, "
                                     f"kezdés {when}"))
                continue
            if status == 'withdrawn' and ours:
                # Korábban ebben a hónapban visszavonták, a mostani fájl már nem:
                # úgy kezeljük, mintha még függőben lenne.
                if entry_ym <= ctx['ym']:
                    carried.append(rec['entry'])
                    to_consume.append((rec['id'], rec.get('version')))
                else:
                    to_restore.append((rec['id'], rec.get('version')))
            elif status == 'pending' and entry_ym <= ctx['ym']:
                carried.append(rec['entry'])
                # A beolvasáskori verzióval együtt: így az írás feltételes lesz,
                # és kiderül, ha közben más felhasználta ugyanezt a rekordot.
                to_consume.append((rec['id'], rec.get('version')))
            elif status == 'consumed' and rec['consumed_in'] == ctx['ym']:
                carried.append(rec['entry'])
            elif status == 'consumed' and generate.is_withdrawn(rec['entry'], withdrawn):
                # Egy már lezárt hónap statisztikájában szerepel: azt ez nem
                # módosítja (az a hónap a saját fájljából készül), csak jelezzük.
                logs.append(('text', f"Visszavonás egy lezárt hónapra ({rec['consumed_in']}): "
                                     f"{rec['entry']['nev']}, kezdés {when} — a munkanapló "
                                     'már nem számolja, a havi statisztika nem változik.'))
            elif (status in ('pending', 'consumed', 'withdrawn') and rec.get('source_ym') == ctx['ym']
                  and rec['id'] not in future_ids):
                # Egy korábbi feldolgozás tette a sorba ugyanebből a hónapból,
                # de az új (javított) fájlban már nincs benne: törölni kell,
                # különben jövő hónapban nem létező munkanapként számítana be.
                # Akkor is, ha egy későbbi hónap már felhasználta: annak a
                # statisztikája így elavult, újra kell futtatni (lásd lent).
                stale.append((rec['id'], rec.get('version')))
                if rec['status'] == 'consumed' and rec.get('consumed_in'):
                    rerun_months.add(rec['consumed_in'])

        entries = generate.merge_entries(ctx['current_entries'], carried)
        logs.append(('text', f"Rekordok a fájlból: {len(ctx['current_entries'])}, átvitt: {len(carried)}, "
                             f"jövő hónapra: {len(ctx['future_entries'])}"))

        if online and ctx.get('new_persons'):
            for person in ctx['new_persons']:
                try:
                    self.store.save_person(ctx['company'], person)
                except Exception as e:
                    logs.append(('text', f'Személy mentése Firestore-ba sikertelen: {e}'))
            logs.append(('text', f"{len(ctx['new_persons'])} új személy elmentve "
                                 f"a(z) {ctx['company']} cég listájába."))
        if online and ctx.get('upgraded_persons'):
            for person, old_doc_id in ctx['upgraded_persons']:
                try:
                    self.store.save_person(ctx['company'], person, old_doc_id=old_doc_id)
                except Exception as e:
                    logs.append(('text', f'Személy mentése Firestore-ba sikertelen: {e}'))
            logs.append(('text', f"{len(ctx['upgraded_persons'])} korábbi adatlap kiegészítve "
                                 'az adóazonosítóval.'))

        output_file = generate.generate_output(
            ctx['path'], ctx['header'], ctx['data_rows'], entries,
            fmt=ctx['format'], persons=ctx.get('persons'))
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
        conflict = False
        if online:
            try:
                history_extra = {'created_by': machine_label(), 'snapshot_id': None}
                snapshot = generate.build_snapshot(
                    ctx['header'], ctx['data_rows'], entries, ctx['format'])
                snapshot_meta = {
                    'year_month': ctx['ym'],
                    'filename': ctx['filename'],
                    'app_version': __version__,
                    'created_by': machine_label(),
                    'entry_count': len(entries),
                    'row_count': len(ctx['data_rows']),
                    'content_hash': generate.content_hash(output_file),
                }
                history_id = uuid.uuid4().hex[:24]
                # A snapshot előbb megy fel: ha elbukik, a history rekord
                # snapshot_id nélkül jön létre, és nem hivatkozik nemlétezőre.
                try:
                    self.store.save_snapshot(ctx['company'], history_id, snapshot, snapshot_meta)
                    history_extra['snapshot_id'] = history_id
                    logs.append(('text', 'A statisztika tartalma elmentve — bármelyik gépről '
                                         'letölthető az Előzményekből.'))
                except Exception as e:
                    logs.append(('text', f'A tartalom mentése nem sikerült (a fájl elkészült): {e}'))

                self.store.sync_processing(ctx['company'], ctx['future_entries'], to_consume,
                                           ctx['ym'], ctx['filename'],
                                           history_extra=history_extra,
                                           history_id=history_id,
                                           stale_ids=stale, withdraw_ids=to_withdraw,
                                           restore_ids=to_restore)
                deleted = self.store.cleanup_expired(ctx['company'])
                if deleted:
                    logs.append(('text', f'Takarítás: {deleted} lejárt rekord véglegesen törölve.'))
                logs.append(('text', f"Várakozási sor frissítve ({len(ctx['future_entries'])} mentve, "
                                     f"{len(to_consume)} felhasználva"
                                     + (f", {len(stale)} elavult törölve" if stale else '')
                                     + (f", {len(to_withdraw)} visszavonva" if to_withdraw else '')
                                     + ")."))
            except ConflictError:
                # Valaki más ugyanezeket a rekordokat közben felhasználta. A
                # várakozási sor érintetlen maradt (a commit atomikus), így a
                # helyzet tiszta: a fájl elkészült, de nem "könyveltük el".
                conflict = True
                logs.append(('text', 'ÜTKÖZÉS: közben valaki más is feldolgozta ezt a hónapot. '
                                     'A várakozási sor NEM módosult, a statisztika viszont '
                                     'elkészült — ellenőrizd, melyik verzió a helyes.'))
                if history_extra.get('snapshot_id'):
                    # Az árván maradt snapshotot takarítjuk: nincs history
                    # rekord, ami hivatkozna rá, így soha nem lenne elérhető.
                    try:
                        self.store.delete_snapshot(ctx['company'], history_extra['snapshot_id'])
                    except Exception:
                        pass
            except FirebaseError as e:
                firestore_warning = str(e)
                logs.append(('text', f'Firestore írás sikertelen: {e}'))

        if conflict or firestore_warning or no_connection:
            rerun_months = set()
        if rerun_months:
            logs.append(('text', 'FIGYELEM: ez a javítás a már feldolgozott '
                                 f"{', '.join(sorted(rerun_months))} hónap(ok)at is érinti — "
                                 'azokat is dolgozd fel újra.'))
        return {'logs': logs, 'no_connection': no_connection,
                'firestore_warning': firestore_warning, 'conflict': conflict,
                'rerun_months': sorted(rerun_months)}

    def _process_file_finish(self, ctx, result, error):
        self.worklog_cache = None
        if error:
            self.log(f'HIBA: {error}')
            messagebox.showerror('Hiba', f'A feldolgozás nem sikerült:\n{error}')
            return
        for item in result['logs']:
            if item[0] == 'text':
                self.log(item[1])
            else:
                self.log_link(item[1], item[2])
        if result.get('conflict'):
            messagebox.showwarning(
                'Ütközés — egyszerre ketten dolgoztátok fel',
                'Amíg ez a feldolgozás futott, valaki más ugyanezeket a '
                'rekordokat felhasználta.\n\n'
                'A statisztika elkészült és archiválva lett, de a várakozási '
                'sort NEM módosítottuk — így a másik gép munkája ép maradt, és '
                'az átvitt dolgozók nem vesztek el.\n\n'
                'Mit tegyél: egyeztess a kollégával, melyik verzió a helyes. '
                'Ha a tiéd, futtasd le újra a feldolgozást — akkor a friss '
                'állapotból dolgozik.')
            return

        if result.get('no_connection'):
            messagebox.showwarning(
                'Nincs kapcsolat',
                'A Firestore nem érhető el. A statisztika a korábbi hónapokból '
                'átvitt rekordok NÉLKÜL és kitöltetlen személyi adatlapokkal '
                'készül el, a jövő hónapra szóló rekordok pedig nem kerülnek '
                'mentésre!')
        if result.get('firestore_warning'):
            messagebox.showwarning(
                'Firestore hiba',
                f"A statisztika elkészült, de a várakozási sor frissítése "
                f"nem sikerült:\n{result['firestore_warning']}")
        if result.get('rerun_months'):
            months = ', '.join(result['rerun_months'])
            messagebox.showwarning(
                'Későbbi hónapot is újra kell futtatni',
                f"Ebben a fájlban változtak a(z) {months} hónapra áthúzódó "
                f"bejelentések, de azt a hónapot már feldolgozták.\n\n"
                f"A várakozási sort kijavítottuk — dolgozd fel újra a(z) {months} "
                f"havi fájlt is, különben annak a statisztikája a régi adatokat "
                f"tartalmazza.")

    # --- Előzmények nézet (beágyazott, nem külön ablak) ---

    def show_history(self):
        self._activate_nav('history')
        page = self.pages['history']
        page.tkraise()
        if not self.store:
            self._render_page_message(page, 'Nincs beállítva Firebase-kapcsolat (töltsd ki a ⚙ Beállítások ablakot).')
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
        self.history_state = {'trees': {}, 'rows': {}}

        frames, _, switcher_state = self._build_company_switcher(page.body, companies)
        self.history_state['switcher_state'] = switcher_state
        cols = {'#0': ('Év-hónap / fájlnév', 280), 'processed': ('Feldolgozva', 150),
                'by': ('Készítette', 150), 'saved': ('Letölthető', 90)}
        for company in companies:
            tree = self._make_tree(frames[company], ('processed', 'by', 'saved'), cols)
            self.history_state['trees'][company] = tree
            rows = self.history_state['rows'].setdefault(company, {})
            groups = {}
            for row in data[company]:
                groups.setdefault(row.get('year_month', '?'), []).append(row)
            for i, ym in enumerate(sorted(groups, reverse=True)):
                node = tree.insert('', 'end', text=ym, open=True,
                                   tags=('odd' if i % 2 else 'even',))
                for row in sorted(groups[ym], key=lambda r: r.get('processed_at', '')):
                    processed = (row.get('processed_at') or '')[:19].replace('T', ' ')
                    # A régi rekordokban nincs snapshot_id — azokhoz nincs tartalom.
                    has_snapshot = bool(row.get('snapshot_id'))
                    rows[row['_id']] = row
                    tree.insert(node, 'end', iid=row['_id'], text=row.get('filename', '?'),
                                values=(processed, row.get('created_by') or '—',
                                        '✓' if has_snapshot else '—'))

        btns = ttk.Frame(page.body)
        btns.pack(fill='x', pady=(10, 0))
        ttk.Button(btns, text='⬇  Kijelölt letöltése', style='Secondary.TButton',
                   command=self._download_selected_history).pack(side='left')
        ttk.Button(btns, text='🔄  Frissítés', style='Secondary.TButton',
                   command=self.show_history).pack(side='left', padx=8)

    def _download_selected_history(self):
        state = getattr(self, 'history_state', None)
        if not state or 'switcher_state' not in state:
            return
        company = state['switcher_state'].get('active')
        tree = state['trees'].get(company)
        if not tree:
            return
        # Csak a levélelemek (fájlok) érdekesek, az év-hónap csoportok nem.
        selected = [i for i in tree.selection() if i in state['rows'].get(company, {})]
        if not selected:
            messagebox.showinfo('Letöltés', 'Jelölj ki egy feldolgozott fájlt a listában.')
            return
        if len(selected) > 1:
            messagebox.showinfo('Letöltés', 'Egyszerre egy fájl tölthető le.')
            return

        row = state['rows'][company][selected[0]]
        snapshot_id = row.get('snapshot_id')
        if not snapshot_id:
            messagebox.showinfo(
                'Nincs mentett tartalom',
                'Ehhez a bejegyzéshez nincs elmentve a statisztika tartalma.\n\n'
                'A régebbi feldolgozások még csak a helyi archívumban érhetők el — '
                'a hónap újrafeldolgozásával utólag felkerül.')
            return

        suggested = os.path.splitext(row.get('filename') or 'statisztika')[0] + '_statisztika.xlsx'
        dest = filedialog.asksaveasfilename(
            title='Statisztika mentése', defaultextension='.xlsx',
            initialfile=suggested, filetypes=[('Excel fájlok', '*.xlsx')])
        if not dest:
            return

        def work():
            loaded = self.store.load_snapshot(company, snapshot_id)
            if not loaded:
                return {'ok': False, 'reason': 'A mentett tartalom nem található.'}
            args = generate.snapshot_to_args(loaded['payload'])
            # A személyi adatlapokat a cég jelenlegi listájából töltjük: a
            # snapshot szándékosan nem duplikálja a személyek kollekcióját.
            # Tartaléknak a régi közös lista szolgál — egy régi hónap
            # személyei még csak abban lehetnek; a cég saját adata erősebb.
            persons = {}
            for source in (company, None):
                try:
                    for doc_id, person in self.store.load_persons(source).items():
                        persons.setdefault(doc_id, person)
                except Exception:
                    pass
            # output_path megadva, ezért az első paraméter (input_path) nem
            # számít — a névképzéshez használná, amit itt a felhasználó ad meg.
            generate.generate_output(
                None, args['header'], args['data_rows'], args['entries'],
                output_path=dest, fmt=args['fmt'], persons=persons)
            return {'ok': True, 'meta': loaded['meta'], 'path': dest}

        self.run_async(work, self._on_history_downloaded, 'Statisztika újraépítése...')

    def _on_history_downloaded(self, result, error):
        if error:
            self.log(f'HIBA a letöltésnél: {error}')
            messagebox.showerror('Hiba', f'A letöltés nem sikerült:\n{error}')
            return
        if not result['ok']:
            messagebox.showwarning('Letöltés', result['reason'])
            return

        meta = result['meta']
        self.log_link('Letöltve: ', result['path'])

        # A fájl a mentett tartalomból épül újra, ezért ha a generálás azóta
        # változott, az eredmény eltérhet az annak idején beadott fájltól.
        saved_version = meta.get('app_version')
        if saved_version and saved_version != __version__:
            self.log(f'Megjegyzés: az eredeti a(z) {saved_version} verzióval készült, '
                     f'a mostani {__version__}. A tartalom azonos, a formátum eltérhet.')
        saved_hash = meta.get('content_hash')
        if saved_hash:
            try:
                if generate.content_hash(result['path']) != saved_hash:
                    self.log('Figyelem: az újraépített munkafüzet tartalma eltér az '
                             'eredetileg készülttől (a generálás azóta megváltozott).')
            except Exception:
                pass

    # --- Várakozási sor / Böngésző nézet (beágyazott, nem külön ablak) ---

    def show_queue(self):
        self._activate_nav('queue')
        page = self.pages['queue']
        page.tkraise()
        if not self.store:
            self._render_page_message(page, 'Nincs beállítva Firebase-kapcsolat (töltsd ki a ⚙ Beállítások ablakot).')
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
                status = {'pending': 'függőben', 'withdrawn': 'visszavonva'}.get(
                    rec['status'], 'felhasználva')
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

    def _make_tree(self, parent, extra_cols, col_spec, hscroll=False):
        """Táblázat függőleges (és kérésre vízszintes) görgetősávval.

        Vízszintes görgetésnél az oszlopok nem nyúlnak/zsugorodnak az ablakhoz
        (stretch=False), különben a hosszú tartalom sosem lógna ki, csak
        levágódna — így a széles táblázat oldalra görgethető.
        """
        wrap = tk.Frame(parent, bg=COLORS['card'])
        wrap.pack(fill='both', expand=True, padx=12, pady=12)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        tree = ttk.Treeview(wrap, columns=extra_cols)
        for key, (label, width) in col_spec.items():
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=60, stretch=not hscroll)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        if hscroll:
            hsb = ttk.Scrollbar(wrap, orient='horizontal', command=tree.xview)
            tree.configure(xscrollcommand=hsb.set)
            hsb.grid(row=1, column=0, sticky='ew')
            # Shift+görgő: oldalirányú görgetés
            tree.bind('<Shift-MouseWheel>',
                      lambda e: tree.xview_scroll(-1 if e.delta > 0 else 1, 'units'))
        tree.tag_configure('odd', background=COLORS['row_alt'])
        tree.tag_configure('even', background=COLORS['card'])
        return tree

    # --- Frissítés ---

    def check_update_silently(self):
        """Induláskori, csendes verzióellenőrzés — hiba esetén nem szól bele."""
        def work():
            return updater.check_for_update()

        def done(info, error):
            if error or not info:
                return
            self.update_available = info
            self.update_btn.configure(text='🔄  Frissítés  ●')
            self.log(f"Új verzió érhető el: {info['version']} "
                     f"(jelenlegi: {__version__}) — lásd a 🔄 Frissítés menüpontot.")

        # csendes ellenőrzés: nincs betöltő overlay, nem blokkolja a munkát
        def task():
            try:
                result = work()
                self.root.after(0, lambda: done(result, None))
            except Exception as e:
                self.root.after(0, lambda: done(None, e))

        threading.Thread(target=task, daemon=True).start()

    def open_update(self):
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
        dlg.title('Frissítés')
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text='🔄', font=('Segoe UI', 26), background=COLORS['card']).pack(pady=(20, 4))
        ttk.Label(dlg, text='Alkalmazás frissítése', background=COLORS['card'],
                  font=FONT_BOLD).pack(padx=24)
        ttk.Label(dlg, text=f'Jelenlegi verzió:  {__version__}', background=COLORS['card'],
                  foreground=COLORS['muted'], font=FONT_BASE).pack(padx=24, pady=(4, 0))

        status = ttk.Label(dlg, text='', background=COLORS['card'], foreground=COLORS['text'],
                           font=FONT_BASE, wraplength=420, justify='center')
        status.pack(padx=24, pady=(10, 4))

        notes = tk.Text(dlg, height=7, width=52, wrap='word', bd=0, bg=COLORS['row_alt'],
                        fg=COLORS['text'], font=('Segoe UI', 9), padx=10, pady=8)
        notes_visible = {'shown': False}

        bar = ttk.Progressbar(dlg, mode='determinate', length=420)

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(10, 20))
        close_btn = ttk.Button(btns, text='Bezárás', style='Secondary.TButton', command=dlg.destroy)
        close_btn.pack(side='left', padx=6)
        action_btn = ttk.Button(btns, text='Keresés...', style='Accent.TButton')
        action_btn.state(['disabled'])
        action_btn.pack(side='left', padx=6)

        state = {'info': None, 'downloaded': None}

        def show_notes(text):
            if not text:
                return
            if not notes_visible['shown']:
                notes.pack(padx=24, pady=(4, 4), before=btns)
                notes_visible['shown'] = True
            notes.configure(state='normal')
            notes.delete('1.0', 'end')
            notes.insert('1.0', text)
            notes.configure(state='disabled')

        # --- 3. lépés: telepítés ---

        def do_install():
            path = state['downloaded']
            # A többi nyitott ablak nem akadályozza a cserét, de azokban a régi
            # verzió fut tovább — ezért előbb kérjük a bezárásukat.
            others = updater.other_instances()
            while others:
                answer = messagebox.askyesnocancel(
                    'Másik ablak is nyitva',
                    f'Az ebevTool még {others} másik ablakban is fut.\n\n'
                    'Zárd be azokat, majd nyomd meg az Igen gombot.\n'
                    'A Nem gombbal mégis folytatod — a többi ablakban addig a régi '
                    'verzió fut tovább.\nA Mégse megszakítja a frissítést.',
                    icon='warning', parent=dlg)
                if answer is None:
                    return
                if answer is False:
                    updater.log(f'frissítés {others} nyitva hagyott másik ablakkal')
                    break
                others = updater.other_instances()
            if not messagebox.askokcancel(
                    'Újraindítás',
                    'A frissítés telepítéséhez az alkalmazás bezárul, majd '
                    'automatikusan újraindul az új verzióval.\n\nFolytatod?',
                    parent=dlg):
                return
            try:
                updater.apply_update(path)
            except updater.UpdateError as e:
                status.configure(text=str(e), foreground=COLORS['danger'])
                return
            self.root.destroy()

        # --- 2. lépés: letöltés ---

        def do_download():
            action_btn.state(['disabled'])
            close_btn.state(['disabled'])
            status.configure(text='Letöltés folyamatban...', foreground=COLORS['text'])
            bar.pack(padx=24, pady=(4, 8), before=btns)
            bar['value'] = 0

            def on_progress(done_bytes, total):
                def update_bar():
                    if total:
                        bar['value'] = done_bytes * 100 / total
                        status.configure(
                            text=f'Letöltés: {done_bytes / 1048576:.1f} / {total / 1048576:.1f} MB')
                    else:
                        status.configure(text=f'Letöltés: {done_bytes / 1048576:.1f} MB')
                self.root.after(0, update_bar)

            def work():
                return updater.download_asset(state['info'], progress=on_progress)

            def done(path, error):
                close_btn.state(['!disabled'])
                if error:
                    bar.pack_forget()
                    status.configure(text=str(error), foreground=COLORS['danger'])
                    action_btn.configure(text='Újra', command=do_download)
                    action_btn.state(['!disabled'])
                    return
                state['downloaded'] = path
                bar['value'] = 100
                status.configure(text='A letöltés kész. A telepítéshez az alkalmazás '
                                      'újraindul.', foreground=COLORS['success'])
                action_btn.configure(text='Telepítés és újraindítás', command=do_install)
                action_btn.state(['!disabled'])

            threading.Thread(
                target=lambda: self._thread_call(work, done), daemon=True).start()

        # --- 1. lépés: keresés ---

        def do_check():
            action_btn.state(['disabled'])
            status.configure(text='Frissítés keresése...', foreground=COLORS['text'])

            def done(info, error):
                if error:
                    status.configure(text=str(error), foreground=COLORS['danger'])
                    action_btn.configure(text='Újra', command=do_check)
                    action_btn.state(['!disabled'])
                    return
                if not info:
                    status.configure(text='Az alkalmazás naprakész. ✓',
                                     foreground=COLORS['success'])
                    action_btn.configure(text='Keresés újra', command=do_check)
                    action_btn.state(['!disabled'])
                    return

                state['info'] = info
                self.update_available = info
                status.configure(text=f"Új verzió érhető el:  {info['version']}",
                                 foreground=COLORS['text'])
                show_notes(info['notes'])

                if not updater.is_frozen():
                    status.configure(
                        text=f"Új verzió érhető el: {info['version']}\n\nForrásból futtatod "
                             "(python gui.py), ezért az automatikus csere nem "
                             "elérhető — frissíts 'git pull'-lal.",
                        foreground=COLORS['text'])
                    action_btn.configure(
                        text='Kiadás megnyitása',
                        command=lambda: webbrowser.open(info.get('page') or RELEASES_PAGE))
                    action_btn.state(['!disabled'])
                    return

                if not info.get('url'):
                    status.configure(
                        text=f"Új verzió érhető el: {info['version']}\n\nEhhez a kiadáshoz "
                             "nincs .exe csatolva, töltsd le kézzel.",
                        foreground=COLORS['danger'])
                    action_btn.configure(
                        text='Kiadás megnyitása',
                        command=lambda: webbrowser.open(info.get('page') or RELEASES_PAGE))
                    action_btn.state(['!disabled'])
                    return

                # Az írásjogot a letöltés ELŐTT nézzük meg: kár lenne 25 MB-ot
                # letölteni, hogy aztán a csere jogosultság híján elbukjon.
                if not updater.can_write_target():
                    status.configure(
                        text=f"Új verzió érhető el: {info['version']}\n\n"
                             "Az alkalmazás mappájába nincs írásjog, ezért az "
                             "automatikus csere nem lehetséges. Indítsd a programot "
                             "rendszergazdaként, vagy töltsd le kézzel.",
                        foreground=COLORS['danger'])
                    action_btn.configure(
                        text='Kiadás megnyitása',
                        command=lambda: webbrowser.open(info.get('page') or RELEASES_PAGE))
                    action_btn.state(['!disabled'])
                    return

                size = info.get('asset_size')
                if size:
                    status.configure(text=f"Új verzió érhető el:  {info['version']}"
                                          f"   ({size / 1048576:.1f} MB)")
                action_btn.configure(text='Letöltés', command=do_download)
                action_btn.state(['!disabled'])

            threading.Thread(
                target=lambda: self._thread_call(updater.check_for_update, done),
                daemon=True).start()

        action_btn.configure(command=do_check)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        # az ablak megnyitásakor rögtön indul a keresés
        self.root.after(0, do_check)

    def _thread_call(self, work_fn, on_done):
        """work_fn futtatása háttérszálon, az eredmény a Tk szálon kézbesítve."""
        try:
            result = work_fn()
            self.root.after(0, lambda: on_done(result, None))
        except Exception as e:
            self.root.after(0, lambda: on_done(None, e))

    # --- Beállítások (titkosított config.dat szerkesztése) ---

    def _write_config(self, api_key, project_id, fernet_key, archive_dir):
        data = {
            'FIREBASE_API_KEY': api_key,
            'FIREBASE_PROJECT_ID': project_id,
            'FERNET_KEY': fernet_key,
            'ARCHIVE_DIR': archive_dir or None,
        }
        try:
            save_runtime_config(data)
        except DPAPIError as e:
            raise RuntimeError(str(e)) from e

    def open_setup_guide(self):
        # A Beállítások ablakból nyílik: annak a tetején maradjon, és bezárás
        # után adja vissza neki a fókuszt — különben a Beállítások nyitva
        # maradna, miközben a főablak újra kattinthatóvá válik.
        owner = self.root.grab_current() or self.root
        dlg = tk.Toplevel(self.root)
        dlg.title('Útmutató — Firebase adatok beszerzése')
        dlg.configure(bg=COLORS['card'])
        dlg.transient(owner)
        dlg.grab_set()

        def close():
            dlg.destroy()
            if owner is not self.root and owner.winfo_exists():
                owner.grab_set()
        dlg.geometry('620x560')
        dlg.minsize(480, 360)

        header = ttk.Frame(dlg, style='Card.TFrame')
        header.pack(fill='x', padx=20, pady=(18, 6))
        ttk.Label(header, text='🧭  Honnan szerezzem meg az adatokat?', background=COLORS['card'],
                 font=FONT_HEAD).pack(anchor='w')
        ttk.Label(header, text='Kövesd sorban a lépéseket — csak egy Google-fiók kell hozzá.',
                 background=COLORS['card'], foreground=COLORS['muted'], font=FONT_BASE,
                 wraplength=560, justify='left').pack(anchor='w', pady=(4, 0))

        open_btn = ttk.Button(header, text='🔗  Firebase console megnyitása böngészőben',
                              style='Accent.TButton',
                              command=lambda: webbrowser.open(FIREBASE_CONSOLE_URL))
        open_btn.pack(anchor='w', pady=(10, 0))

        body = tk.Frame(dlg, bg=COLORS['card'])
        body.pack(fill='both', expand=True, padx=20, pady=(10, 6))
        text = tk.Text(body, wrap='word', bd=0, bg=COLORS['card'], fg=COLORS['text'],
                       font=FONT_BASE, padx=4, pady=4, cursor='arrow')
        scroll = ttk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        text.tag_configure('h', font=FONT_BOLD, foreground=COLORS['accent'], spacing1=14, spacing3=4)
        text.tag_configure('body', font=FONT_BASE, spacing3=2)
        text.tag_configure('code', font=('Consolas', 9), background=COLORS['row_alt'],
                           lmargin1=16, lmargin2=16, spacing1=4, spacing3=8)

        def h(t):
            text.insert('end', t + '\n', 'h')

        def p(t):
            text.insert('end', t + '\n', 'body')

        def code(t):
            text.insert('end', t + '\n', 'code')

        h('1. lépés — Firebase projekt létrehozása')
        p('• Nyisd meg a fenti gombbal a Firebase console-t, és jelentkezz be a Google-fiókoddal.')
        p('• Kattints az "Add project" / "Projekt hozzáadása" gombra.')
        p('• Adj neki egy tetszőleges nevet (pl. "ebevtool"), majd Tovább.')
        p('• A Google Analytics kérdésnél nyugodtan kapcsold ki, nincs rá szükség.')
        p('• Kattints a "Create project" / "Projekt létrehozása" gombra, és várd meg, míg elkészül.')

        h('2. lépés — Adatbázis (Firestore) létrehozása')
        p('• A bal oldali menüben: Build → Firestore Database.')
        p('• Kattints a "Create database" gombra.')
        p('• Módnak válaszd a "Native mode" / "Alapértelmezett mód" opciót.')
        p('• Régiónak válassz egy európai régiót, pl. europe-west3 (Frankfurt).')
        p('• A kezdő biztonsági szabályok nem számítanak, a következő lépésben úgyis felülírjuk.')

        h('3. lépés — Bejelentkezés engedélyezése az alkalmazásnak')
        p('• Bal oldali menü: Build → Authentication → "Get started".')
        p('• A "Sign-in method" fülön válaszd az "Anonymous" lehetőséget, kapcsold be, majd mentsd el.')
        p('• Ez teszi lehetővé, hogy az alkalmazás automatikusan, jelszó nélkül tudjon kapcsolódni.')

        h('4. lépés — Biztonsági szabályok beillesztése')
        p('• A Firestore Database oldalon kattints a "Rules" fülre.')
        p('• Töröld ki a meglévő szöveget, és illeszd be helyette az alábbit:')
        code(FIRESTORE_RULES)
        p('• Kattints a "Publish" gombra a mentéshez.')
        p('• Ez azt jelenti: csak az alkalmazáson keresztül, bejelentkezve lehet hozzáférni az '
          'adatokhoz — más nem éri el őket.')

        h('5. lépés — A három adat kimásolása')
        p('• Kattints a bal felső fogaskerék ikonra, majd a "Project settings" menüpontra.')
        p('• A "General" fülön találod:')
        p('    – Project ID  →  ezt írd be a Beállítások ablak "Firebase Project ID" mezőjébe')
        p('    – Web API Key  →  ezt írd be a "Firebase Web API Key" mezőbe')
        p('• A Fernet titkosítási kulcsot nem kell máshonnan másolni (kivétel, ha nem akarsz csatlakozni egy már létező adatbázishoz): a Beállítások ablakban az '
          '"Új kulcs generálása" gombbal egy kattintással létrehozható.')

        h('6. lépés — Mentés')
        p('• Zárd be ezt az ablakot, töltsd ki mindhárom mezőt a Beállítások ablakban, majd '
          'kattints a "Mentés" gombra.')
        p('• Ezzel kész is — az alkalmazás mostantól tudja használni az Előzmények és a '
          'Várakozási sor funkciókat.')

        text.configure(state='disabled')

        ttk.Button(dlg, text='Bezárás', style='Secondary.TButton', command=close).pack(pady=(0, 16))
        dlg.bind('<Escape>', lambda e: close())
        dlg.protocol('WM_DELETE_WINDOW', close)

    def open_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
        dlg.title('Beállítások')
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text='⚙️', font=('Segoe UI', 26), background=COLORS['card']).pack(pady=(20, 4))
        ttk.Label(dlg, text='Adatbázis-kapcsolat beállítása', background=COLORS['card'],
                 font=FONT_BOLD).pack(padx=24)
        ttk.Label(dlg, text='Ezek az adatok titkosítva, csak ezen a Windows-fiókban és gépen tárolódnak'
                          ' az adatbázisba feltöltött adatokat csak az tudja olvasni, akivel megegyezik az összes adat.'
                          ' Ha a Fernet kulcsot elhagyod, csak a teljes reset segíthet.',
                 background=COLORS['card'], foreground=COLORS['muted'], justify='center',
                 wraplength=380, font=FONT_BASE).pack(padx=24, pady=(4, 8))
        ttk.Button(dlg, text='❓  Hogyan találom meg ezeket az adatokat?', style='Secondary.TButton',
                  command=self.open_setup_guide).pack(padx=24, pady=(0, 12))

        form = ttk.Frame(dlg, style='Card.TFrame')
        form.pack(padx=24, fill='x')
        form.grid_columnconfigure(1, weight=1)

        api_key_var = tk.StringVar(value=getattr(config, 'FIREBASE_API_KEY', '') if config else '')
        project_id_var = tk.StringVar(value=getattr(config, 'FIREBASE_PROJECT_ID', '') if config else '')
        fernet_var = tk.StringVar(value=getattr(config, 'FERNET_KEY', '') if config else '')
        archive_var = tk.StringVar(value=getattr(config, 'ARCHIVE_DIR', None) or '' if config else '')

        def add_row(r, label):
            ttk.Label(form, text=label, background=COLORS['card'], font=FONT_BASE).grid(
                row=r, column=0, sticky='w', pady=(0, 8), padx=(0, 10))

        add_row(0, 'Firebase Web API Key:')
        ttk.Entry(form, textvariable=api_key_var, width=38).grid(row=0, column=1, sticky='ew', pady=(0, 8))

        add_row(1, 'Firebase Project ID:')
        ttk.Entry(form, textvariable=project_id_var, width=38).grid(row=1, column=1, sticky='ew', pady=(0, 8))

        add_row(2, 'Fernet titkosítási kulcs:')
        fernet_entry = ttk.Entry(form, textvariable=fernet_var, width=38, show='•')
        fernet_entry.grid(row=2, column=1, sticky='ew', pady=(0, 8))

        fernet_btns = ttk.Frame(form, style='Card.TFrame')
        fernet_btns.grid(row=3, column=1, sticky='w', pady=(0, 14))

        def toggle_fernet_visible():
            visible = fernet_entry.cget('show') == ''
            fernet_entry.configure(show='•' if visible else '')
            show_btn.configure(text='👁  Mutat' if visible else '🙈  Elrejt')

        show_btn = ttk.Button(fernet_btns, text='👁  Mutat', style='Secondary.TButton',
                              command=toggle_fernet_visible)
        show_btn.pack(side='left', padx=(0, 6))

        def gen_fernet():
            fernet_var.set(Fernet.generate_key().decode())

        ttk.Button(fernet_btns, text='Új kulcs generálása', style='Secondary.TButton',
                  command=gen_fernet).pack(side='left')

        add_row(4, 'Archívum mappa (opcionális):')
        ttk.Entry(form, textvariable=archive_var, width=38).grid(row=4, column=1, sticky='ew', pady=(0, 8))

        def browse_archive():
            path = filedialog.askdirectory(title='Archívum mappa kiválasztása')
            if path:
                archive_var.set(path)

        ttk.Button(form, text='Tallózás...', style='Secondary.TButton',
                  command=browse_archive).grid(row=5, column=1, sticky='w', pady=(0, 10))

        # Az adatok nem az .exe mellett vannak — mutassuk meg, hol keresse őket.
        ttk.Label(form, text='Üresen hagyva:\n' + default_archive_dir(),
                  background=COLORS['card'], foreground=COLORS['muted'],
                  font=FONT_BASE, justify='left').grid(
            row=6, column=1, sticky='w', pady=(0, 10))

        locations = ttk.Frame(dlg, style='Card.TFrame')
        locations.pack(padx=24, pady=(0, 6), anchor='w')
        ttk.Label(locations, text='Az alkalmazás fájljai:', background=COLORS['card'],
                  font=FONT_BOLD).pack(anchor='w')
        ttk.Label(locations,
                  text=f'Beállítások:  {filename_utils.user_data_dir()}\n'
                       f'Archívum:     {default_archive_dir()}',
                  background=COLORS['card'], foreground=COLORS['muted'],
                  font=FONT_BASE, justify='left').pack(anchor='w', pady=(2, 4))

        loc_btns = ttk.Frame(locations, style='Card.TFrame')
        loc_btns.pack(anchor='w')
        ttk.Button(loc_btns, text='📂  Beállítások mappa', style='Secondary.TButton',
                   command=lambda: self._open_path(filename_utils.user_data_dir())
                   ).pack(side='left', padx=(0, 6))
        ttk.Button(loc_btns, text='📂  Archívum', style='Secondary.TButton',
                   command=lambda: self._open_path(default_archive_dir())).pack(side='left')

        status_lbl = ttk.Label(dlg, text='', background=COLORS['card'], foreground=COLORS['danger'],
                               font=FONT_BASE, wraplength=380, justify='center')
        status_lbl.pack(padx=24)

        def do_save():
            api_key = api_key_var.get().strip()
            project_id = project_id_var.get().strip()
            fernet_key = fernet_var.get().strip()
            archive_dir = archive_var.get().strip()

            if not api_key or not project_id or not fernet_key:
                status_lbl.configure(text='A Web API Key, a Project ID és a Fernet kulcs kitöltése kötelező.')
                return
            try:
                Fernet(fernet_key.encode('ascii'))
            except Exception:
                status_lbl.configure(text='Érvénytelen Fernet kulcs — használd a generálás gombot, '
                                          'vagy másold be a korábban mentett kulcsot.')
                return

            try:
                self._write_config(api_key, project_id, fernet_key, archive_dir or None)
            except Exception as e:
                status_lbl.configure(text=f'A mentés nem sikerült: {e}')
                return

            self._init_store()
            dlg.destroy()
            self.log('Beállítások elmentve és betöltve (titkosítva, config.dat).')
            messagebox.showinfo('Kész', 'A beállítások elmentve, a kapcsolat azonnal életbe lép.')

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(6, 20))
        ttk.Button(btns, text='Mégse', style='Secondary.TButton', command=dlg.destroy).pack(side='left', padx=6)
        ttk.Button(btns, text='Mentés', style='Accent.TButton', command=do_save).pack(side='left', padx=6)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    # --- Reset ---

    def confirm_reset(self):
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
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
                 '   (MINDEN ismert cégnél), az archívumból betöltött munkanapló\n'
                 '•  A Firestore-ban tárolt összes személyes profil')
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
            self.store.delete_all_aliases(c)
            self.store.delete_all_persons(c)
            self.store.delete_all_worklog_imports(c)

        def work():
            online, err = self._try_sign_in()
            done_companies = []
            if online:
                companies = self.known_companies()
                self._parallel_map(companies, wipe_company)
                done_companies = companies
                try:
                    self.store.delete_all_persons(None)  # a régi közös lista
                except Exception:
                    pass
            return {'online': online, 'error': err, 'companies': done_companies}

        self.run_async(work, self._on_reset_done, 'Nullázás folyamatban...')

    def _on_reset_done(self, result, error):
        self.worklog_cache = None
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
        elif self.current_page == 'persons':
            self.show_persons()


    # --- Személyek nézet ---

    def show_persons(self):
        self._activate_nav('persons')
        # a munkanapló is frissüljön (más gépen közben feldolgozott hónapok)
        self.worklog_cache = None
        page = self.pages['persons']
        page.tkraise()
        if not self.store:
            self._render_page_message(page, 'Nincs beállítva Firebase-kapcsolat (töltsd ki a ⚙ Beállítások ablakot).')
            return

        def work():
            online, err = self._try_sign_in()
            if not online:
                return {'online': False, 'error': err}
            companies = self.known_companies()
            data = self._parallel_map(companies, self.store.load_persons)
            try:
                legacy = self.store.load_persons(None)
            except Exception:
                legacy = {}
            return {'online': True, 'companies': companies, 'data': data, 'legacy': legacy}

        self.run_async(work, self._on_persons_loaded_for_page, 'Személyek betöltése...')

    def _on_persons_loaded_for_page(self, result, error):
        page = self.pages['persons']
        if error:
            self._render_page_message(page, f'Hiba a személyek betöltésekor: {error}')
            return
        if not result['online']:
            extra = f' ({result["error"]})' if result.get('error') else ''
            self._render_page_message(page, f'A Firestore nem érhető el.{extra}')
            return

        # Fülek: cégenként egy, plusz a régi közös lista, ha még van benne valami.
        # A belső kulcs a cégnév, a régi listáé None (így hívja a store is).
        tabs = [(c, c) for c in result['companies']]
        data = dict(result['data'])
        if result['legacy']:
            tabs.append((LEGACY_PERSONS_TAB, None))
            data[None] = result['legacy']
        if not tabs:
            self._render_page_message(
                page, 'Még nincs egyetlen ismert cég sem.\n'
                      'Generáláskor a rendszer rákérdez az ismeretlen személyekre.')
            return

        # szerkesztés/törlés utáni újratöltéskor a keresés megmarad
        old_search = self.persons_state.get('search_var')
        try:
            previous_query = old_search.get() if old_search else ''
        except tk.TclError:
            previous_query = ''

        self._clear_body(page)
        labels = [label for label, _ in tabs]
        company_of = dict(tabs)

        tools_frame = ttk.Frame(page.body)
        tools_frame.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Button(tools_frame, text='🧹  Adatok ellenőrzése', style='Secondary.TButton',
                   command=self.open_data_check).pack(side='left')
        ttk.Button(tools_frame, text='📥  Régi hónapok az archívumból', style='Secondary.TButton',
                   command=self.import_archive).pack(side='left', padx=8)
        ttk.Label(tools_frame, text='Tipp: Shift + egérgörgő = oldalra görgetés',
                  style='Muted.TLabel').pack(side='right')

        btns_frame = ttk.Frame(page.body)
        btns_frame.pack(side='bottom', fill='x', pady=(10, 0))
        ttk.Button(btns_frame, text='📅  Munkanapló', style='Accent.TButton',
                   command=self._show_selected_worklog).pack(side='left')
        ttk.Button(btns_frame, text='✏  Szerkesztés', style='Secondary.TButton',
                   command=self._edit_selected_person).pack(side='left', padx=(8, 0))
        ttk.Button(btns_frame, text='🗑  Törlés', style='Secondary.TButton',
                   command=self._delete_selected_person).pack(side='left', padx=8)
        ttk.Button(btns_frame, text='🔄  Frissítés', style='Secondary.TButton',
                   command=self.show_persons).pack(side='left')

        # --- kereső: minden cég listájában egyszerre keres ---
        search_bar = ttk.Frame(page.body)
        search_bar.pack(fill='x', pady=(0, 12))
        ttk.Label(search_bar, text='🔍  Keresés:', font=FONT_BOLD,
                  background=COLORS['bg']).pack(side='left')
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_bar, textvariable=search_var, width=36, font=FONT_BASE)
        search_entry.pack(side='left', padx=(8, 8), ipady=3)
        ttk.Button(search_bar, text='✕', style='Secondary.TButton', width=3,
                   command=lambda: search_var.set('')).pack(side='left')
        search_info = ttk.Label(search_bar, text='név, adóazonosító vagy TAJ — az összes cégben',
                                style='Muted.TLabel')
        search_info.pack(side='left', padx=(12, 0))
        search_entry.bind('<Escape>', lambda e: search_var.set(''))

        browse = ttk.Frame(page.body)
        browse.pack(fill='both', expand=True)
        results = ttk.Frame(page.body, style='Card.TFrame')

        frames, select, switcher_state = self._build_company_switcher(browse, labels)
        self.persons_state = {'trees': {}, 'data': data, 'company_of': company_of,
                              'switcher_state': switcher_state, 'select': select,
                              'search_var': search_var, 'results_items': {},
                              'results_people': {}}

        cols = ('adoazonosito', 'taj', 'szul_nev', 'anya_neve', 'szul_hely_ido', 'lakcim')
        col_spec = {
            '#0': ('Név', 160),
            'adoazonosito': ('Adóazonosító', 110),
            'taj': ('TAJ-szám', 105),
            'szul_nev': ('Szül. név', 140),
            'anya_neve': ('Anyja neve', 140),
            'szul_hely_ido': ('Szül.hely, idő', 160),
            'lakcim': ('Lakcím', 180),
        }
        for label in labels:
            frame = frames[label]
            if company_of[label] is None:
                ttk.Label(frame, text='A régi, minden cégre közös lista. Feldolgozáskor '
                                      'innen automatikusan átkerülnek a személyek az adott '
                                      'cég listájába; ha már mind átkerült, ez a lista törölhető.',
                          style='Muted.TLabel', background=COLORS['card'],
                          wraplength=700, justify='left').pack(anchor='w', padx=12, pady=(10, 0))
            tree = self._make_tree(frame, cols, col_spec, hscroll=True)
            tree.bind('<Double-1>', lambda e: self._edit_selected_person())
            self.persons_state['trees'][label] = tree
            self._fill_persons_tree(tree, data[company_of[label]])

        results_tree = self._make_tree(
            results, ('adoazonosito', 'taj', 'cegek'),
            {'#0': ('Név / cég', 220), 'adoazonosito': ('Adóazonosító', 110),
             'taj': ('TAJ-szám', 105), 'cegek': ('Cégek', 260)},
            hscroll=True)
        results_tree.bind('<Double-1>', lambda e: self._open_search_result(e))
        self.persons_state['results_tree'] = results_tree

        def on_search(*_):
            query = search_var.get()
            if not query.strip():
                results.pack_forget()
                browse.pack(fill='both', expand=True)
                search_info.configure(text='név, adóazonosító vagy TAJ — az összes cégben')
                return
            browse.pack_forget()
            results.pack(fill='both', expand=True)
            people, hits = self._fill_search_results(results_tree, query)
            search_info.configure(
                text=f'{people} személy, {hits} céges adatlap' if people else 'Nincs találat.')

        search_var.trace_add('write', on_search)
        search_var.set(previous_query)
        search_entry.focus_set()
        search_entry.icursor('end')

    @staticmethod
    def _normalize_text(text):
        """Kisbetűs, ékezet nélküli alak: a 'Kovács' a 'kovacs'-ra is találjon."""
        decomposed = unicodedata.normalize('NFKD', str(text or '').lower())
        return ''.join(c for c in decomposed if not unicodedata.combining(c))

    def _search_persons(self, query):
        """A keresésnek megfelelő személyek, cégek szerint csoportosítva.

        Minden szónak illeszkednie kell a névre, a születési névre, az
        adóazonosítóra vagy a TAJ-ra (a számok szóközök nélkül). Ugyanaz a
        személy több cégnél is szerepelhet: az adóazonosító (ennek hiányában a
        TAJ) alapján egy csoportba kerülnek. Visszatérés: csoportok listája,
        mindegyik [(fül-felirat, dokumentumazonosító, adatlap), ...].
        """
        state = self.persons_state
        # a kötőjellel/ponttal tagolt számot (pl. TAJ: 123-456-789) egyben keressük
        tokens = []
        for t in self._normalize_text(query).split():
            digits = t.replace('-', '').replace('.', '')
            tokens.append(digits if digits.isdigit() else t)
        matches = []
        for label, company in state['company_of'].items():
            for doc_id, p in state['data'][company].items():
                haystack = ' '.join((self._normalize_text(p.get('nev')),
                                     self._normalize_text(p.get('szul_nev')),
                                     generate.ado_key(p.get('adoazonosito')),
                                     generate.taj_key(p.get('taj'))))
                if all(t in haystack for t in tokens):
                    matches.append((label, doc_id, p))

        groups = {}
        by_taj = {}
        # Előbb az adóazonosítós adatlapok, hogy egy régi (adóazonosító
        # nélküli) adatlap a TAJ-a alapján hozzájuk csatlakozhasson.
        matches.sort(key=lambda m: not generate.ado_key(m[2].get('adoazonosito')))
        for label, doc_id, p in matches:
            ado = generate.ado_key(p.get('adoazonosito'))
            taj = generate.taj_key(p.get('taj'))
            if ado:
                gkey = 'ado:' + ado
                if taj:
                    by_taj.setdefault(taj, gkey)
            elif taj:
                gkey = by_taj.get(taj, 'taj:' + taj)
            else:
                gkey = f'doc:{label}:{doc_id}'
            groups.setdefault(gkey, []).append((label, doc_id, p))
        return sorted(groups.values(),
                      key=lambda g: self._normalize_text(g[0][2].get('nev')))

    def _fill_search_results(self, tree, query):
        tree.delete(*tree.get_children())
        items = self.persons_state['results_items'] = {}
        people = self.persons_state['results_people'] = {}
        groups = self._search_persons(query)
        if not groups:
            tree.insert('', 'end', iid='__empty__', text='(Nincs találat.)')
            self._autosize_columns(tree)
            return 0, 0
        hits = 0
        for i, group in enumerate(groups):
            first = group[0][2]
            ado = next((p.get('adoazonosito') for _, _, p in group if p.get('adoazonosito')), '')
            labels = sorted({label for label, _, _ in group})
            parent = tree.insert('', 'end', text=first.get('nev', ''), open=True,
                                 values=(ado, normalize.normalize_taj(first.get('taj', '')), ', '.join(labels)),
                                 tags=('odd' if i % 2 else 'even',))
            taj = next((p.get('taj') for _, _, p in group if p.get('taj')), '')
            people[parent] = (ado, taj, first.get('nev', ''))
            # egy céges találatnál a szülősor is egyértelműen azt az adatlapot jelenti
            if len(group) == 1:
                items[parent] = group[0][:2]
            for label, doc_id, p in sorted(group, key=lambda g: g[0].lower()):
                # ha egy cégnél másképp írták a nevet, az is látsszon
                other_name = p.get('nev', '') != first.get('nev', '')
                text = f'🏢  {label}' + (f"  ({p.get('nev', '')})" if other_name else '')
                child = tree.insert(parent, 'end', text=text,
                                    values=(p.get('adoazonosito', ''), normalize.normalize_taj(p.get('taj', '')), ''),
                                    tags=('odd' if i % 2 else 'even',))
                items[child] = (label, doc_id)
                people[child] = (p.get('adoazonosito', ''), p.get('taj', ''), p.get('nev', ''))
                hits += 1
        self._autosize_columns(tree)
        return len(groups), hits

    def _open_search_result(self, event=None):
        """Dupla katt egy találaton: a személy során a munkanapló nyílik meg,
        a cég-soron a cég fülére ugrik, a személyt kijelölve."""
        state = self.persons_state
        tree = state['results_tree']
        sel = tree.selection()
        if sel and tree.get_children(sel[0]):
            self._show_selected_worklog()
            return 'break'  # a dupla katt ne csukja össze a sort
        picked = state['results_items'].get(sel[0]) if sel else None
        if not picked:
            return
        label, doc_id = picked
        state['search_var'].set('')
        state['select'](label)
        tree = state['trees'][label]
        if tree.exists(doc_id):
            tree.selection_set(doc_id)
            tree.focus(doc_id)
            tree.see(doc_id)

    # --- Munkanapló (személyenkénti összesítés) ---

    def _selected_identity(self):
        """(adóazonosító, TAJ, név) a kijelölt személyhez — a keresőben a
        személy sorára (több cég esetén is) vagy a cég-sorra, a fül-nézetben a
        kijelölt sorra. None, ha nincs kijelölés."""
        state = self.persons_state
        if not state.get('trees'):
            return None
        if state['search_var'].get().strip():
            sel = state['results_tree'].selection()
            return state['results_people'].get(sel[0]) if sel else None
        label = state['switcher_state']['active']
        sel = [i for i in state['trees'][label].selection() if i != '__empty__']
        person = state['data'][state['company_of'][label]].get(sel[0]) if sel else None
        if not person:
            return None
        return person.get('adoazonosito', ''), person.get('taj', ''), person.get('nev', '')

    def _show_selected_worklog(self):
        identity = self._selected_identity()
        if not identity:
            messagebox.showinfo('Munkanapló', 'Válassz ki egy személyt a listából.')
            return
        self._with_worklog(lambda people: self._open_worklog_window(identity, people))

    def _with_worklog(self, then):
        """A munkanapló betöltése (egyszer, utána a gyorsítótárból)."""
        if self.worklog_cache is not None:
            then(self.worklog_cache)
            return

        def done(people, error):
            if error:
                messagebox.showerror('Hiba', f'A munkanapló betöltése nem sikerült:\n{error}')
                return
            self.worklog_cache = people
            then(people)

        self.run_async(self._load_worklog_work, done, 'Munkanapló betöltése...')

    def _load_worklog_work(self):
        online, err = self._try_sign_in()
        if not online:
            raise FirebaseError(f'A Firestore nem érhető el. {err or ""}'.strip())
        companies = self.known_companies()
        histories = self._parallel_map(companies, self.store.load_history)
        imports = self._parallel_map(companies, self.store.load_worklog_imports)

        latest = {c: worklog.latest_processing(histories[c]) for c in companies}
        wanted = [(c, ym, row.get('snapshot_id'))
                  for c in companies for ym, row in latest[c].items()]

        def load(item):
            if not item[2]:
                return None
            try:
                loaded = self.store.load_snapshot(item[0], item[2])
            except Exception:
                return None  # egy olvashatatlan hónap ne vigye el az egész naplót
            return loaded['payload'] if loaded else None

        payloads = self._parallel_map(wanted, load)
        data = {c: {'snapshots': {}, 'imports': imports[c]} for c in companies}
        # azok a hónapok, amelyek legutóbbi feldolgozásának tartalma nem érhető
        # el (és az archívumból sincs pótolva) — ezek napjai hiányozhatnak
        missing = {}
        for (c, ym, sid), payload in payloads.items():
            if payload:
                data[c]['snapshots'][ym] = payload
            elif ym not in imports[c]:
                missing.setdefault(c, []).append(ym)
        self.worklog_missing = {c: sorted(m) for c, m in missing.items()}
        return worklog.build(data)

    def _open_worklog_window(self, identity, people):
        ado, taj, nev = identity
        records = worklog.find(people, ado, taj, nev)
        record = worklog.merge(records)
        summary = worklog.summarize(record)

        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)
        dlg.title(f'Munkanapló — {record["nev"] or nev}')
        dlg.configure(bg=COLORS['card'])
        dlg.geometry('720x520')
        dlg.minsize(560, 380)

        head = ttk.Frame(dlg, style='Card.TFrame')
        head.pack(fill='x', padx=20, pady=(16, 6))
        ttk.Label(head, text=f'📅  {record["nev"] or nev}', background=COLORS['card'],
                  font=FONT_BOLD).pack(anchor='w')
        ttk.Label(head, text=f'Adóazonosító: {record["adoazonosito"] or ado or "—"}   •   '
                             f'TAJ: {normalize.normalize_taj(record["taj"] or taj) or "—"}',
                  background=COLORS['card'], foreground=COLORS['muted'],
                  font=FONT_BASE).pack(anchor='w')

        if summary['companies']:
            n_comp = len(summary['companies'])
            text = (f"Összesen {summary['total_days']} munkanap"
                    + (f' {n_comp} cégnél' if n_comp > 1 else '')
                    + f" — első: {summary['first']:%Y.%m.%d.}, utolsó: {summary['last']:%Y.%m.%d.}")
            if summary['total_unique_days'] != summary['total_days']:
                text += (f"\n(ebből {summary['total_days'] - summary['total_unique_days']} napon "
                         'egyszerre több cégnél is szerepel)')
        else:
            text = 'Ehhez a személyhez nincs rögzített munkanap a mentett havi statisztikákban.'
        ttk.Label(head, text=text, background=COLORS['card'], font=FONT_BASE,
                  justify='left').pack(anchor='w', pady=(6, 0))

        notes = []
        if record['withdrawn']:
            listed = ', '.join(f'{c}: {d:%Y.%m.%d.}' for c, d, _ in sorted(record['withdrawn'])[:6])
            more = len(record['withdrawn']) - 6
            notes.append(f'Visszavont bejelentés (nem számít bele): {listed}'
                         + (f' és még {more}' if more > 0 else ''))
        if any(c['archive_months'] for c in summary['companies']):
            notes.append('A (archív) jelű hónapok a helyi archívumból lettek betöltve.')
        gaps = ['{}: {}'.format(c['company'], ', '.join(self.worklog_missing[c['company']]))
                for c in summary['companies'] if self.worklog_missing.get(c['company'])]
        if gaps:
            notes.append('Hiányos lehet — ezeknek a hónapoknak a legutóbbi feldolgozása nem '
                         'érhető el (régebbi verzió vagy sikertelen mentés; a 📥 archívum-'
                         'betöltés pótolhatja): ' + '; '.join(gaps))
        notes.append('Forrás: a havi statisztikák legutóbbi feldolgozása (újrafeltöltéskor '
                     'a javított verzió számít).')
        ttk.Label(head, text='\n'.join(notes), background=COLORS['card'],
                  foreground=COLORS['muted'], font=FONT_BASE, wraplength=660,
                  justify='left').pack(anchor='w', pady=(6, 0))

        # a gombsor előbb kerül fel, hogy kis ablakban se lógjon le
        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(side='bottom', pady=(8, 16))
        ttk.Button(btns, text='📄  Mentés Excelbe', style='Secondary.TButton',
                   command=lambda: self._export_worklog(record, summary, dlg)).pack(side='left', padx=6)
        ttk.Button(btns, text='Bezárás', style='Accent.TButton',
                   command=dlg.destroy).pack(side='left', padx=6)

        body = ttk.Frame(dlg, style='Card.TFrame')
        body.pack(fill='both', expand=True, padx=8)
        tree = self._make_tree(body, ('napok', 'elso', 'utolso', 'datumok'),
                               {'#0': ('Cég / hónap', 200), 'napok': ('Napok', 60),
                                'elso': ('Első nap', 95), 'utolso': ('Utolsó nap', 95),
                                'datumok': ('Napok listája', 300)},
                               hscroll=True)
        for i, c in enumerate(summary['companies']):
            parent = tree.insert('', 'end', text=f"🏢  {c['company']}", open=True,
                                 values=(c['count'], f"{c['first']:%Y.%m.%d.}",
                                         f"{c['last']:%Y.%m.%d.}", ''),
                                 tags=('odd' if i % 2 else 'even',))
            for ym, days in c['months']:
                archive = ' (archív)' if ym in c['archive_months'] else ''
                tree.insert(parent, 'end', text=f'{ym}{archive}',
                            values=(len(days), f'{days[0]:%Y.%m.%d.}', f'{days[-1]:%Y.%m.%d.}',
                                    ', '.join(f'{d:%m.%d.}' for d in days)),
                            tags=('odd' if i % 2 else 'even',))
        self._autosize_columns(tree)

        dlg.bind('<Escape>', lambda e: dlg.destroy())

    def _export_worklog(self, record, summary, parent):
        name = record['nev'] or 'szemely'
        dest = filedialog.asksaveasfilename(
            parent=parent, title='Munkanapló mentése', defaultextension='.xlsx',
            initialfile=f'{filename_utils.safe_folder_name(name)}_munkanaplo.xlsx',
            filetypes=[('Excel fájlok', '*.xlsx')])
        if not dest:
            return
        try:
            worklog.export_xlsx(record, summary, dest)
        except Exception as e:
            messagebox.showerror('Hiba', f'A mentés nem sikerült:\n{e}', parent=parent)
            return
        self.log_link('Munkanapló mentve: ', dest)
        messagebox.showinfo('Kész', f'A munkanapló elmentve:\n{dest}', parent=parent)

    # --- Adatok ellenőrzése és egységesítése (a már rögzített személyekre) ---

    FIELD_LABELS = {'nev': 'Név', 'szul_nev': 'Szül. név', 'anya_neve': 'Anyja neve',
                    'szul_hely_ido': 'Szül.hely, idő', 'lakcim': 'Lakcím',
                    'adoazonosito': 'Adóazonosító', 'taj': 'TAJ-szám'}

    def open_data_check(self):
        state = self.persons_state
        if not state.get('data'):
            messagebox.showinfo('Adatok ellenőrzése', 'Nincsenek betöltött személyek.')
            return
        changes, issues = self._collect_data_check(state['company_of'], state['data'])
        self._open_data_check_window(changes, issues)

    @staticmethod
    def _collect_data_check(company_of, data):
        """(javaslatok, problémák) az összes rögzített adatlapra.

        javaslat: (fül, cég, dok.azonosító, személy, mező, régi, új)
        probléma: (fül, cég, dok.azonosító, személy, szöveg)
        """
        changes, issues = [], []
        by_ado, by_taj = {}, {}
        for label, company in company_of.items():
            for doc_id, p in sorted(data[company].items(), key=lambda x: x[1].get('nev', '').lower()):
                for field, old, new in normalize.person_changes(p):
                    changes.append((label, company, doc_id, p, field, old, new))
                for text in normalize.check_person(p):
                    issues.append((label, company, doc_id, p, text))
                ado, taj = generate.ado_key(p.get('adoazonosito')), generate.taj_key(p.get('taj'))
                if ado:
                    by_ado.setdefault(ado, []).append((label, company, doc_id, p))
                if taj:
                    by_taj.setdefault(taj, []).append((label, company, doc_id, p))

        # cégeken átívelő ellentmondások
        def norm_name(p):
            return App._normalize_text(normalize.normalize_name(p.get('nev', '')))

        for ado, group in by_ado.items():
            names = {norm_name(p) for _, _, _, p in group}
            if len(names) > 1:
                listed = ', '.join(sorted({f'{p.get("nev")} ({label})' for label, _, _, p in group}))
                for label, company, doc_id, p in group:
                    issues.append((label, company, doc_id, p,
                                   f'Ugyanez az adóazonosító más névvel is szerepel: {listed}'))
        for taj, group in by_taj.items():
            ados = {generate.ado_key(p.get('adoazonosito')) for _, _, _, p in group} - {''}
            if len(ados) > 1:
                listed = ', '.join(sorted({f'{p.get("nev")} – {p.get("adoazonosito")} ({label})'
                                           for label, _, _, p in group}))
                for label, company, doc_id, p in group:
                    issues.append((label, company, doc_id, p,
                                   f'Ugyanez a TAJ-szám más adóazonosítóval is szerepel '
                                   f'(valamelyik elírás lehet): {listed}'))
        return changes, issues

    def _open_data_check_window(self, changes, issues):
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)
        dlg.title('Adatok ellenőrzése')
        dlg.configure(bg=COLORS['card'])
        dlg.geometry('900x560')
        dlg.minsize(640, 400)

        ttk.Label(dlg, text='🧹  Adatok ellenőrzése és egységesítése', background=COLORS['card'],
                  font=FONT_BOLD).pack(anchor='w', padx=20, pady=(16, 2))
        ttk.Label(dlg, text='Csak a már rögzített adatlapokat vizsgálja; a feldolgozott '
                            'Excel-fájlokhoz és a statisztikákhoz nem nyúl. Semmi nem változik, '
                            'amíg az „Alkalmazás” gombot meg nem nyomod.',
                  background=COLORS['card'], foreground=COLORS['muted'], font=FONT_BASE,
                  wraplength=840, justify='left').pack(anchor='w', padx=20, pady=(0, 8))

        nb = ttk.Notebook(dlg)
        nb.pack(fill='both', expand=True, padx=12)

        # --- 1. fül: egységesítési javaslatok ---
        tab1 = ttk.Frame(nb, style='Card.TFrame')
        nb.add(tab1, text=f'  Egységesítés ({len(changes)})  ')
        ttk.Label(tab1, text='A kijelölt sorok kerülnek alkalmazásra (alapból mind). '
                             'Ctrl+katt: egy sor ki/be, Shift+katt: tartomány.',
                  background=COLORS['card'], foreground=COLORS['muted'],
                  font=FONT_BASE).pack(anchor='w', padx=12, pady=(10, 0))
        ctree = self._make_tree(tab1, ('ceg', 'mezo', 'regi', 'uj'),
                                {'#0': ('Név', 160), 'ceg': ('Cég', 120), 'mezo': ('Mező', 100),
                                 'regi': ('Jelenleg', 220), 'uj': ('Javasolt', 220)},
                                hscroll=True)
        change_of = {}
        for i, ch in enumerate(changes):
            label, company, doc_id, p, field, old, new = ch
            iid = ctree.insert('', 'end', text=p.get('nev', ''),
                               values=(label, self.FIELD_LABELS.get(field, field), old, new),
                               tags=('odd' if i % 2 else 'even',))
            change_of[iid] = ch
        if changes:
            ctree.selection_set(list(change_of))
        else:
            ctree.insert('', 'end', text='(Minden adat egységes — nincs javaslat.)')
        self._autosize_columns(ctree)

        # --- 2. fül: problémák ---
        tab2 = ttk.Frame(nb, style='Card.TFrame')
        nb.add(tab2, text=f'  Problémák ({len(issues)})  ')
        ttk.Label(tab2, text='Ezeket nem lehet automatikusan javítani. Dupla kattintás: '
                             'a személy szerkesztése.',
                  background=COLORS['card'], foreground=COLORS['muted'],
                  font=FONT_BASE).pack(anchor='w', padx=12, pady=(10, 0))
        itree = self._make_tree(tab2, ('ceg', 'problema'),
                                {'#0': ('Név', 160), 'ceg': ('Cég', 120), 'problema': ('Probléma', 520)},
                                hscroll=True)
        issue_of = {}
        for i, (label, company, doc_id, p, text) in enumerate(issues):
            iid = itree.insert('', 'end', text=p.get('nev', ''), values=(label, text),
                               tags=('odd' if i % 2 else 'even',))
            issue_of[iid] = (company, doc_id, p)
        if not issues:
            itree.insert('', 'end', text='(Nem találtunk problémát.)')
        self._autosize_columns(itree)

        def edit_issue(_e=None):
            sel = itree.selection()
            if sel and sel[0] in issue_of:
                dlg.destroy()
                self._open_person_edit_dialog(*issue_of[sel[0]])

        itree.bind('<Double-1>', edit_issue)

        def apply():
            picked = [change_of[i] for i in ctree.selection() if i in change_of]
            if not picked:
                messagebox.showinfo('Egységesítés', 'Nincs kijelölt javaslat.', parent=dlg)
                return
            per_person = {}
            for label, company, doc_id, p, field, old, new in picked:
                key = (company, doc_id)
                per_person.setdefault(key, dict(p))[field] = new
            if not messagebox.askyesno(
                    'Egységesítés',
                    f'{len(picked)} mező módosul {len(per_person)} adatlapon. Folytatod?',
                    parent=dlg):
                return

            def work():
                failed = []
                for (company, doc_id), updated in per_person.items():
                    try:
                        self.store.save_person(company, updated, old_doc_id=doc_id)
                    except Exception as e:
                        failed.append(f'{updated.get("nev")}: {e}')
                return failed

            def done(failed, error):
                if error or failed:
                    messagebox.showerror('Hiba', 'Néhány adatlap mentése nem sikerült:\n'
                                         + (str(error) if error else '\n'.join(failed[:10])))
                else:
                    self.log(f'Egységesítés: {len(picked)} mező javítva {len(per_person)} adatlapon.')
                dlg.destroy()
                self.show_persons()

            self.run_async(work, done, 'Egységesítés mentése...')

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(8, 16))
        ttk.Button(btns, text='Bezárás', style='Secondary.TButton',
                   command=dlg.destroy).pack(side='left', padx=6)
        if changes:
            ttk.Button(btns, text='✓  Kijelöltek alkalmazása', style='Accent.TButton',
                       command=apply).pack(side='left', padx=6)
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        if not changes and issues:
            nb.select(tab2)

    # --- Régi hónapok betöltése a helyi archívumból (munkanaplóhoz) ---

    def import_archive(self):
        if not self.store:
            messagebox.showinfo('Archívum', 'Nincs beállítva Firebase-kapcsolat.')
            return
        roots = archive_import.candidate_archive_roots(getattr(config, 'ARCHIVE_DIR', None) if config else None)
        if not roots:
            folder = filedialog.askdirectory(title='Az archívum mappája')
            if not folder:
                return
            roots = [folder]

        def work():
            known = self.known_companies()
            warnings = []
            items = []
            for root_dir in roots:
                items += archive_import.scan_archive(root_dir, warnings=warnings)
            result = archive_import.build_import(
                items, lambda folder: archive_import.match_company_folder(folder, known))
            result['warnings'] = warnings + result['warnings']
            result['roots'] = roots
            result['persons_plan'] = self._plan_archive_persons(
                archive_import.collect_person_details(result['imports']))
            return result

        self.run_async(work, self._confirm_archive_import, 'Archívum átvizsgálása...')

    def _plan_archive_persons(self, details):
        """Az archívumban talált személyi adatok összevetése a cégek listájával.

        Új adatlap csak akkor készül, ha a cégnél még nincs ilyen személy; a
        meglévőnél csak az ÜRES mezők töltődnek ki — kitöltött adatot nem írunk
        felül (az eltéréseket csak megszámoljuk).
        Visszatérés: {'new': [(cég, adatlap)], 'update': [(cég, adatlap, régi
        dok.azonosító)], 'conflicts': int}
        """
        plan = {'new': [], 'update': [], 'conflicts': 0}

        def same(a, b):
            return ' '.join(self._normalize_text(a).split()) == ' '.join(self._normalize_text(b).split())

        for company, people in details.items():
            existing = dict(self.store.load_persons(company))
            for ap in people:
                if not (generate.ado_key(ap['adoazonosito']) or generate.taj_key(ap['taj'])):
                    continue  # azonosító nélkül nem párosítható
                key, cur = generate.find_person(existing, ap['adoazonosito'], ap['taj'])
                if cur is None:
                    person = {'adoazonosito': ap['adoazonosito'],
                              'taj': normalize.normalize_taj(ap['taj']),
                              'nev': ap['nev'], **ap['details']}
                    plan['new'].append((company, person))
                    existing[FirebaseStore.person_doc_id(person)] = person
                    continue
                updated = dict(cur)
                for field, value in ap['details'].items():
                    if not (cur.get(field) or '').strip():
                        updated[field] = value
                    elif not same(cur.get(field), value):
                        plan['conflicts'] += 1
                if (not generate.ado_key(cur.get('adoazonosito'))
                        and generate.ado_key(ap['adoazonosito'])):
                    updated['adoazonosito'] = ap['adoazonosito']
                if updated != cur:
                    plan['update'].append((company, updated, key))
                    existing.pop(key, None)
                    existing[FirebaseStore.person_doc_id(updated)] = updated
        return plan

    def _confirm_archive_import(self, result, error):
        if error:
            messagebox.showerror('Hiba', f'Az archívum átvizsgálása nem sikerült:\n{error}')
            return
        imports = result['imports']
        plan = result['persons_plan']
        for w in result['warnings']:
            self.log(f'Archívum: {w}')
        for item in result['unresolved']:
            self.log(f"Archívum — kihagyva: {item['path']} ({item.get('reason', '')})")
        if not imports:
            messagebox.showinfo('Archívum', 'Az archívumban nem találtunk betölthető hónapot.\n\n'
                                            'Átvizsgált mappák:\n' + '\n'.join(result['roots']))
            return
        companies = sorted({c for c, _ in imports})
        superseded = sum(len(v['superseded']) for v in imports.values())
        text = (f"{len(imports)} hónap betölthető {len(companies)} cégtől "
                f"({', '.join(companies[:5])}{' …' if len(companies) > 5 else ''}).\n\n")
        if superseded:
            text += (f'{superseded} régebbi fájl kimarad, mert ugyanarra a hónapra van újabb '
                     '(újrafeltöltött) változat.\n')
        if result['unresolved']:
            text += f"{len(result['unresolved'])} fájl nem azonosítható (lásd a naplót).\n"
        if plan['new'] or plan['update']:
            text += (f"\nSzemélyi adatok az archívumból: {len(plan['new'])} új adatlap, "
                     f"{len(plan['update'])} meglévő kiegészítése (csak az üres mezők).\n")
            if plan['conflicts']:
                text += (f"{plan['conflicts']} mezőben az archív adat eltér a már rögzítettől — "
                         'ott a meglévő marad.\n')
        text += ('\nA munkanaplóhoz betöltött hónapok a várakozási sorhoz és az előzményekhez '
                 'nem nyúlnak. Ahol egy hónapnak már van felhőben mentett tartalma, ott az '
                 'számít. Újbóli betöltés felülírja ugyanazt a hónapot.\n\nBetöltöd?')
        if not messagebox.askyesno('Régi hónapok betöltése', text):
            return

        def work():
            failed = []
            for (company, ym), item in sorted(imports.items()):
                try:
                    # a munkanaplóhoz csak a napok kellenek, a személyi adatok nem
                    self.store.save_worklog_import(company, ym, {
                        'source': os.path.basename(item['source']),
                        'persons': [{k: v for k, v in p.items() if k != 'details'}
                                    for p in item['persons']],
                    })
                except Exception as e:
                    failed.append(f'{company} {ym}: {e}')
            for company, person in plan['new']:
                try:
                    self.store.save_person(company, person)
                except Exception as e:
                    failed.append(f"{company} – {person.get('nev')}: {e}")
            for company, person, old_doc_id in plan['update']:
                try:
                    self.store.save_person(company, person, old_doc_id=old_doc_id)
                except Exception as e:
                    failed.append(f"{company} – {person.get('nev')}: {e}")
            return failed

        def done(failed, error):
            self.worklog_cache = None
            if error or failed:
                messagebox.showerror('Hiba', 'Néhány elem betöltése nem sikerült:\n'
                                     + (str(error) if error else '\n'.join(failed[:10])))
                return
            summary = f'{len(imports)} hónap betöltve a munkanaplóba.'
            if plan['new'] or plan['update']:
                summary += (f"\nSzemélyi adatok: {len(plan['new'])} új adatlap, "
                            f"{len(plan['update'])} kiegészítve.")
            self.log('Archívum: ' + summary.replace('\n', ' '))
            messagebox.showinfo('Kész', summary)
            if self.current_page == 'persons':
                self.show_persons()

        self.run_async(work, done, 'Betöltés...')

    def _fill_persons_tree(self, tree, persons):
        tree.delete(*tree.get_children())
        if not persons:
            tree.insert('', 'end', iid='__empty__',
                        text='(Ennél a cégnél még nincsenek személyek rögzítve.)')
            self._autosize_columns(tree)
            return
        for i, (key, p) in enumerate(sorted(persons.items(),
                                            key=lambda x: x[1].get('nev', '').lower())):
            tree.insert('', 'end', iid=key, text=p.get('nev', ''),
                        values=(p.get('adoazonosito', ''), normalize.normalize_taj(p.get('taj', '')),
                                p.get('szul_nev', ''), p.get('anya_neve', ''),
                                p.get('szul_hely_ido', ''), p.get('lakcim', '')),
                        tags=('odd' if i % 2 else 'even',))
        self._autosize_columns(tree)

    @staticmethod
    def _autosize_columns(tree, padding=24, max_width=700):
        """Az oszlopok szélessége a leghosszabb tartalomhoz igazítva.

        A széles oszlopok miatt a táblázat kilóghat az ablakból — ezt a
        vízszintes görgetősáv kezeli, így a hosszú lakcím sem vágódik le.
        """
        # ugyanazokkal a betűkkel mérünk, mint amikkel a 'Treeview' stílus rajzol
        font = tkfont.Font(font=FONT_BASE)
        head_font = tkfont.Font(font=FONT_BOLD)
        columns = ('#0',) + tuple(tree['columns'])
        widths = {c: head_font.measure(tree.heading(c, 'text')) for c in columns}
        stack = list(tree.get_children())
        while stack:
            iid = stack.pop()
            stack.extend(tree.get_children(iid))
            item = tree.item(iid)
            texts = [item['text']] + [str(v) for v in item['values']]
            for col, text in zip(columns, texts):
                widths[col] = max(widths[col], font.measure(text))
        for col, w in widths.items():
            # a '#0' oszlopban a fa-behúzás is helyet foglal
            extra = 40 if col == '#0' else 0
            tree.column(col, width=min(w + padding + extra, max_width))

    def _selected_person(self, action):
        """(cég, dokumentumazonosító, személy) a kijelölt sorhoz, vagy None."""
        state = self.persons_state
        if not state.get('trees'):
            return None
        if state['search_var'].get().strip():
            sel = state['results_tree'].selection()
            picked = state['results_items'].get(sel[0]) if sel else None
            if not picked:
                messagebox.showinfo(action, 'Válassz ki egy találatot — ha a személy több '
                                            'cégnél is szerepel, a cég sorát a neve alatt.')
                return None
            label, key = picked
        else:
            label = state['switcher_state']['active']
            tree = state['trees'][label]
            sel = [i for i in tree.selection() if i != '__empty__']
            if not sel:
                messagebox.showinfo(action, 'Válassz ki egy személyt a listából.')
                return None
            key = sel[0]
        company = state['company_of'][label]
        person = state['data'][company].get(key)
        if not person:
            return None
        return company, key, person

    def _edit_selected_person(self):
        picked = self._selected_person('Szerkesztés')
        if picked:
            self._open_person_edit_dialog(*picked)

    def _delete_selected_person(self):
        picked = self._selected_person('Törlés')
        if not picked:
            return
        company, key, person = picked
        where = f'a(z) {company} cég listájából' if company else 'a régi közös listából'
        if not messagebox.askyesno('Törlés megerősítése',
                                   f'Véglegesen törlöd {person.get("nev") or key} adatait {where}?'):
            return

        def work():
            self.store.delete_person(company, key)

        def done(_, error):
            if error:
                messagebox.showerror('Hiba', f'Törlés sikertelen: {error}')
                return
            self.show_persons()

        self.run_async(work, done, 'Törlés...')

    def _open_person_edit_dialog(self, company, doc_id, person):
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
        dlg.title('Személy szerkesztése')
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text='✏️', font=('Segoe UI', 22), background=COLORS['card']).pack(pady=(18, 4))
        ttk.Label(dlg, text=person.get('nev', ''), background=COLORS['card'],
                  font=FONT_BOLD).pack()
        ttk.Label(dlg, text=company or LEGACY_PERSONS_TAB, background=COLORS['card'],
                  foreground=COLORS['muted'], font=FONT_BASE).pack(pady=(0, 10))

        form = ttk.Frame(dlg, style='Card.TFrame')
        form.pack(padx=24, fill='x')
        form.grid_columnconfigure(1, weight=1)

        # Az azonosítók is javíthatók (pl. elírt TAJ); az adóazonosító
        # módosításakor az adatlap új azonosítóra költözik (lásd save_person).
        fields = [
            ('adoazonosito', 'Adóazonosító:'),
            ('taj', 'TAJ-szám:'),
            ('szul_nev', 'Születési név:'),
            ('anya_neve', 'Anyja neve:'),
            ('szul_hely_ido', 'Szül.hely, idő:'),
            ('lakcim', 'Lakcím:'),
        ]
        vars_ = {}
        for r, (key, label) in enumerate(fields):
            ttk.Label(form, text=label, background=COLORS['card'], font=FONT_BASE).grid(
                row=r, column=0, sticky='w', pady=(0, 8), padx=(0, 10))
            var = tk.StringVar(value=person.get(key, ''))
            ttk.Entry(form, textvariable=var, width=34).grid(row=r, column=1, sticky='ew', pady=(0, 8))
            vars_[key] = var

        status_lbl = ttk.Label(dlg, text='', background=COLORS['card'],
                               foreground=COLORS['success'], font=FONT_BASE)
        status_lbl.pack(padx=24, pady=(4, 0))

        def do_save():
            updated = dict(person)
            for key, var in vars_.items():
                updated[key] = var.get().strip()
            if not generate.ado_key(updated['adoazonosito']) and not generate.taj_key(updated['taj']):
                messagebox.showwarning('Hiányzó azonosító',
                                       'Az adóazonosító és a TAJ-szám közül legalább '
                                       'az egyiket meg kell adni.', parent=dlg)
                return
            bad = []
            if updated['adoazonosito'] and not normalize.valid_adoazonosito(updated['adoazonosito']):
                bad.append(f"Az adóazonosító ({updated['adoazonosito']})")
            updated['taj'] = normalize.normalize_taj(updated['taj'])
            if updated['taj'] and not normalize.valid_taj(updated['taj']):
                bad.append(f"A TAJ-szám ({updated['taj']})")
            if bad and not messagebox.askyesno(
                    'Hibás ellenőrzőszám',
                    '\n'.join(f'{b} ellenőrzőszáma nem stimmel.' for b in bad)
                    + '\n\nValószínűleg elírás. Mégis elmented így?', parent=dlg):
                return
            new_id = FirebaseStore.person_doc_id(updated)
            others = {k: p for k, p in self.persons_state['data'][company].items() if k != doc_id}
            if new_id in others:
                messagebox.showwarning('Már létező személy',
                                       f'Ezzel az azonosítóval már van adatlap ebben a listában '
                                       f'({others[new_id].get("nev", "")}).', parent=dlg)
                return

            def work():
                self.store.save_person(company, updated, old_doc_id=doc_id)
                return updated

            def done(result, error):
                if error:
                    messagebox.showerror('Hiba', f'Mentés sikertelen: {error}')
                    return
                status_lbl.configure(text='✓ Elmentve')
                dlg.after(700, dlg.destroy)
                self.show_persons()

            self.run_async(work, done, 'Mentés...')

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(8, 20))
        ttk.Button(btns, text='Mégse', style='Secondary.TButton', command=dlg.destroy).pack(side='left', padx=6)
        ttk.Button(btns, text='Mentés', style='Accent.TButton', command=do_save).pack(side='left', padx=6)
        dlg.bind('<Return>', lambda e: do_save())
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    def _ask_person_dialog(self, nev, adoazonosito, taj, position=None):
        """Adatlap bekérése. Visszatérés: dict, None (kihagyva) vagy SKIP_ALL."""
        result = {'data': None}
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)  # mindig a főablak fölött marad
        dlg.title('Ismeretlen személy')
        dlg.configure(bg=COLORS['card'])
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text='👤', font=('Segoe UI', 22), background=COLORS['card']).pack(pady=(18, 4))
        heading = 'Ismeretlen személy'
        if position and position[1] > 1:
            heading += f'  ({position[0]} / {position[1]})'
        ttk.Label(dlg, text=heading, background=COLORS['card'], font=FONT_BOLD).pack()
        ttk.Label(dlg, text=f'{nev}  •  Adóazonosító: {adoazonosito or "—"}  •  '
                            f'TAJ: {normalize.normalize_taj(taj) or "—"}',
                  background=COLORS['card'],
                  foreground=COLORS['muted'], font=FONT_BASE).pack(pady=(2, 4))
        ttk.Label(dlg, text='Add meg az adatait, vagy hagyd üresen és nyomj OK-t.\n'
                            'A személy üresen hagyva is bekerül a statisztikába, '
                            'csak az adatlapja marad kitöltetlen.',
                  background=COLORS['card'], foreground=COLORS['muted'], font=FONT_BASE,
                  justify='center', wraplength=360).pack(padx=24, pady=(0, 12))

        form = ttk.Frame(dlg, style='Card.TFrame')
        form.pack(padx=24, fill='x')
        form.grid_columnconfigure(1, weight=1)

        fields = [
            ('szul_nev', 'Születési név:'),
            ('anya_neve', 'Anyja neve:'),
            ('szul_hely_ido', 'Szül.hely, idő:'),
            ('lakcim', 'Lakcím:'),
        ]
        vars_ = {}
        for r, (key, label) in enumerate(fields):
            ttk.Label(form, text=label, background=COLORS['card'], font=FONT_BASE).grid(
                row=r, column=0, sticky='w', pady=(0, 8), padx=(0, 10))
            var = tk.StringVar()
            ttk.Entry(form, textvariable=var, width=34).grid(row=r, column=1, sticky='ew', pady=(0, 8))
            vars_[key] = var

        def do_ok():
            # Üresen hagyva is elfogadjuk: a személy így is bekerül a
            # statisztikába, csak az adatlapja marad kitöltetlen. Az üres
            # profilt is elmentjük, így legközelebb nem kérdez rá újra.
            values = {k: v.get().strip() for k, v in vars_.items()}
            result['data'] = {'adoazonosito': adoazonosito, 'taj': normalize.normalize_taj(taj),
                              'nev': nev, **values}
            dlg.destroy()

        def do_skip_all():
            result['data'] = SKIP_ALL
            dlg.destroy()

        btns = ttk.Frame(dlg, style='Card.TFrame')
        btns.pack(pady=(8, 6))
        remaining = position[1] - position[0] + 1 if position else 1
        if remaining > 1:
            ttk.Button(btns, text=f'Összes kihagyása ({remaining})', style='Secondary.TButton',
                       command=do_skip_all).pack(side='left', padx=6)
        ttk.Button(btns, text='OK', style='Accent.TButton', command=do_ok).pack(side='left', padx=6)
        if remaining > 1:
            ttk.Label(dlg, text='A kihagyott személyek adatlapja kitöltetlen marad, '
                                'és legközelebb újra rákérdezünk.',
                      background=COLORS['card'], foreground=COLORS['muted'], font=FONT_BASE,
                      wraplength=360, justify='center').pack(padx=24, pady=(0, 16))
        else:
            btns.pack_configure(pady=(8, 20))
        dlg.bind('<Return>', lambda e: do_ok())
        dlg.bind('<Escape>', lambda e: dlg.destroy())
        dlg.wait_window()
        return result['data']


def main():
    updater.cleanup_leftovers()
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    app = App(root)
    root.after(1500, app.check_update_silently)
    if len(sys.argv) > 1:
        root.after(200, lambda: app.process_file(sys.argv[1]))
    root.mainloop()


if __name__ == '__main__':
    main()
