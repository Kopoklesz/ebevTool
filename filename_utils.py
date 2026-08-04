import json
import os
import re
import shutil
import sys
import unicodedata

MONTHS = {
    'JANUAR': 1, 'FEBRUAR': 2, 'MARCIUS': 3, 'APRILIS': 4,
    'MAJUS': 5, 'JUNIUS': 6, 'JULIUS': 7, 'AUGUSZTUS': 8,
    'SZEPTEMBER': 9, 'OKTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12,
}

APP_NAME = 'ebevTool'


def app_dir():
    """A futtatható állomány (vagy forrásból futtatva a forrás) mappája.

    FIGYELEM: ide nem írunk semmit — az .exe mellé kerülő fájlok
    rendetlenséget okoznak, és a Program Files alatt írásjogunk sincs.
    Az adatoknak a 'user_data_dir()' / 'documents_dir()' való.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def user_data_dir():
    """A felhasználó gépi beállításainak helye (rejtett alkalmazás-adat).

    Windows: %APPDATA%\\ebevTool  (pl. C:\\Users\\<név>\\AppData\\Roaming\\ebevTool)
    Ide kerül a config.dat és az aliases.json — olyan fájlok, amiket a
    felhasználónak nem kell kézzel nyitogatnia.
    """
    base = os.environ.get('APPDATA')
    if not base:
        # Nem Windows vagy hiányzó környezeti változó — ilyenkor a
        # felhasználói mappa rejtett almappája a bevett hely.
        base = os.path.join(os.path.expanduser('~'), '.config')
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def documents_dir():
    """A felhasználó Dokumentumok mappája (átirányítást is figyelembe véve).

    Ide kerül az archívum: azt a felhasználó meg akarja találni és böngészni,
    ezért nem való rejtett alkalmazás-adatok közé.
    """
    if sys.platform == 'win32':
        try:
            import ctypes
            import ctypes.wintypes
            # A Dokumentumok mappa átirányítható (OneDrive, hálózati profil),
            # ezért a rendszertől kérdezzük meg, nem tippelünk.
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            CSIDL_PERSONAL, SHGFP_TYPE_CURRENT = 5, 0
            if ctypes.windll.shell32.SHGetFolderPathW(
                    None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def migrate_legacy_file(filename, target_dir):
    """Egy régi, .exe mellé került fájl átmozgatása az új helyére.

    A korábbi verziók az alkalmazás mappájába írtak. Frissítés után ezeket
    egyszer átköltöztetjük, hogy a beállítások ne vesszenek el. Csendben
    dolgozik: ha bármi hiba van, marad a régi állapot.
    """
    old_path = os.path.join(app_dir(), filename)
    new_path = os.path.join(target_dir, filename)
    if not os.path.exists(old_path) or os.path.exists(new_path):
        return False
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.move(old_path, new_path)
        return True
    except Exception:
        return False


def normalize(text):
    """Ékezet-mentesítés és nagybetűsítés."""
    text = unicodedata.normalize('NFKD', str(text))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return text.upper()


def detect_month(filename):
    """A fájlnévben szereplő magyar hónapnév → hónap sorszám (1-12) vagy None."""
    name = normalize(os.path.splitext(os.path.basename(filename))[0])
    for month_name, month_num in MONTHS.items():
        if month_name in name:
            return month_num
    return None


def safe_folder_name(text):
    """Fájlrendszer-barát mappanév (Windows-tiltott karakterek cseréje)."""
    return re.sub(r'[<>:"/\\|?*]', '_', text).strip() or 'ismeretlen'


# Az új NAV-export fájlneve: Egyszerusitett_<foglalkoztató adószáma>_<riportazonosító>
NAV_EXPORT_RE = re.compile(r'^EGYSZERUSITETT_(\d{8})_\d+$')


def tax_number(filename):
    """A NAV-export fájlnevében szereplő foglalkoztatói adószám törzsszáma, vagy None."""
    name = normalize(os.path.splitext(os.path.basename(filename))[0])
    match = NAV_EXPORT_RE.match(name)
    return match.group(1) if match else None


def alias_token(filename):
    """A fájlnév cégre utaló része, normalizálva.

    Ez a token azonosítja a fájlnév-mintát az alias táblában, így pl. a
    'VALAMI JÚLIUS.xlsx' és 'VALAMI AUGUSZTUS 2.xlsx' ugyanahhoz a
    megjegyzett céghez tartozik.

    Az új NAV-export fájlneve nem tartalmaz cégnevet, csak a foglalkoztató
    adószámát ('Egyszerusitett_<adószám>_<riportazonosító>.xlsx') — itt az
    adószám azonosítja a céget. Enélkül minden cég ugyanarra az
    'EGYSZERUSITETT' tokenre esne össze.
    """
    adoszam = tax_number(filename)
    if adoszam:
        return f'EGYSZERUSITETT_{adoszam}'

    name = normalize(os.path.splitext(os.path.basename(filename))[0])
    for month_name in MONTHS:
        name = name.replace(month_name, ' ')
    name = re.sub(r'[^A-Z]+', ' ', name).strip()
    return re.sub(r'\s+', '_', name)


def _local_alias_path():
    # A korábbi verziók az .exe mellé írtak; egyszeri átköltöztetés után az
    # alias-cache a felhasználói adatmappában él.
    migrate_legacy_file('aliases.json', user_data_dir())
    return os.path.join(user_data_dir(), 'aliases.json')


def load_local_aliases():
    path = _local_alias_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def get_local_alias(token):
    return load_local_aliases().get(token)


def set_local_alias(token, company):
    aliases = load_local_aliases()
    aliases[token] = company
    with open(_local_alias_path(), 'w', encoding='utf-8') as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)


def reset_local_aliases():
    """A helyi alias-cache (aliases.json) végleges törlése."""
    path = _local_alias_path()
    if os.path.exists(path):
        os.remove(path)
