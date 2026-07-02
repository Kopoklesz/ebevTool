import json
import os
import re
import sys
import unicodedata

MONTHS = {
    'JANUAR': 1, 'FEBRUAR': 2, 'MARCIUS': 3, 'APRILIS': 4,
    'MAJUS': 5, 'JUNIUS': 6, 'JULIUS': 7, 'AUGUSZTUS': 8,
    'SZEPTEMBER': 9, 'OKTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12,
}

def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


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


def alias_token(filename):
    """A fájlnév cégre utaló része: hónapnév és számok nélkül, normalizálva.

    Ez a token azonosítja a fájlnév-mintát az alias táblában, így pl. a
    'VALAMI JÚLIUS.xlsx' és 'VALAMI AUGUSZTUS 2.xlsx' ugyanahhoz a
    megjegyzett céghez tartozik.
    """
    name = normalize(os.path.splitext(os.path.basename(filename))[0])
    for month_name in MONTHS:
        name = name.replace(month_name, ' ')
    name = re.sub(r'[^A-Z]+', ' ', name).strip()
    return re.sub(r'\s+', '_', name)


def _local_alias_path():
    return os.path.join(app_dir(), 'aliases.json')


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
