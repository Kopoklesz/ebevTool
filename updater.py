"""Alkalmazás-frissítés GitHub Releases-ből.

A frissítés menete:
  1. check_for_update()  – lekérdezi a legfrissebb release-t a GitHub API-ról
  2. download_asset()    – letölti az új .exe-t egy ideiglenes fájlba
  3. apply_update()      – elindít egy takarító batch-et, ami az app kilépése
                           után lecseréli a futó .exe-t, majd újraindítja

A 3. lépés azért kell, mert Windows alatt a futó .exe fájl zárolva van, így
saját magát nem tudja felülírni — a cserét egy külső folyamatnak kell végeznie,
miután a program kilépett.

Forrásból (python gui.py) futtatva a csere nem értelmezhető, ilyenkor csak
értesítés van, letöltés nincs.
"""

import os
import subprocess
import sys
import tempfile

import requests

from version import (RELEASES_API, RELEASES_PAGE, __version__, is_newer)

TIMEOUT = 15
DOWNLOAD_TIMEOUT = 300
USER_AGENT = f'ebevTool/{__version__}'

# Csak ilyen kiterjesztésű release-asset jöhet szóba frissítésként.
ASSET_SUFFIX = '.exe'


class UpdateError(Exception):
    pass


def is_frozen():
    """Igaz, ha PyInstaller-rel csomagolt .exe-ként futunk."""
    return getattr(sys, 'frozen', False)


def current_exe():
    return os.path.abspath(sys.executable)


def check_for_update():
    """A legfrissebb release adatai, vagy None ha nincs újabb verzió.

    Visszatérés: {'version', 'notes', 'url', 'asset_name', 'asset_size'}
    """
    try:
        r = requests.get(RELEASES_API, timeout=TIMEOUT,
                         headers={'User-Agent': USER_AGENT,
                                  'Accept': 'application/vnd.github+json'})
    except Exception as e:
        raise UpdateError(f'Nem sikerült elérni a GitHubot: {e}') from e

    if r.status_code == 404:
        raise UpdateError('Nincs közzétett kiadás a GitHubon (vagy a repó nem publikus).')
    if r.status_code == 403:
        raise UpdateError('A GitHub átmenetileg korlátozza a lekérdezéseket, '
                          'próbáld később.')
    if not r.ok:
        raise UpdateError(f'GitHub hiba ({r.status_code}).')

    try:
        data = r.json()
    except Exception as e:
        raise UpdateError(f'Értelmezhetetlen válasz a GitHubtól: {e}') from e

    tag = data.get('tag_name') or data.get('name')
    if not tag:
        raise UpdateError('A kiadásnak nincs verziószáma.')
    if not is_newer(tag):
        return None

    asset = None
    for candidate in data.get('assets') or []:
        name = candidate.get('name', '')
        if name.lower().endswith(ASSET_SUFFIX):
            asset = candidate
            break

    return {
        'version': str(tag).strip(),
        'notes': (data.get('body') or '').strip(),
        'url': asset.get('browser_download_url') if asset else None,
        'asset_name': asset.get('name') if asset else None,
        'asset_size': asset.get('size') if asset else None,
        'page': data.get('html_url') or RELEASES_PAGE,
    }


def download_asset(info, progress=None):
    """Letölti a release .exe-jét ideiglenes fájlba, és visszaadja az útvonalát.

    A 'progress' egy opcionális callback: progress(letöltött_bájt, összes_bájt).
    """
    url = info.get('url')
    if not url:
        raise UpdateError('A kiadáshoz nincs letölthető .exe fájl csatolva.')

    try:
        r = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                         headers={'User-Agent': USER_AGENT})
        r.raise_for_status()
    except Exception as e:
        raise UpdateError(f'A letöltés nem sikerült: {e}') from e

    total = int(r.headers.get('Content-Length') or info.get('asset_size') or 0)
    target_dir = os.path.dirname(current_exe()) if is_frozen() else tempfile.gettempdir()

    fd, temp_path = tempfile.mkstemp(prefix='ebevTool_update_', suffix='.exe',
                                     dir=target_dir)
    downloaded = 0
    try:
        with os.fdopen(fd, 'wb') as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    except Exception as e:
        _silent_remove(temp_path)
        raise UpdateError(f'A letöltés megszakadt: {e}') from e

    if total and downloaded != total:
        _silent_remove(temp_path)
        raise UpdateError('A letöltött fájl hiányos, próbáld újra.')
    if downloaded == 0:
        _silent_remove(temp_path)
        raise UpdateError('A letöltött fájl üres.')

    return temp_path


def _silent_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass


# A takarító batch: megvárja, míg a futó .exe elengedi a fájlt, lecseréli,
# majd újraindítja az alkalmazást és törli önmagát.
_SWAP_BATCH = """@echo off
chcp 65001 > nul
set "TARGET={target}"
set "SOURCE={source}"

rem Megvárjuk, míg a futó példány kilép és elengedi a fájlt (max ~30 mp).
set /a TRIES=0
:wait
set /a TRIES+=1
if %TRIES% GTR 60 goto failed
move /y "%TARGET%" "%TARGET%.old" > nul 2>&1
if errorlevel 1 (
    ping -n 2 127.0.0.1 > nul
    goto wait
)

move /y "%SOURCE%" "%TARGET%" > nul 2>&1
if errorlevel 1 goto restore

rem A régi példányt még az újraindítás előtt takarítjuk el, hogy ne
rem zárolhassa az elinduló új verzió. Ha mégis bent marad, a program
rem induláskori cleanup_leftovers() hívása később törli.
del "%TARGET%.old" > nul 2>&1
start "" "%TARGET%"
goto cleanup

:restore
rem A csere nem sikerült - visszaállítjuk az eredeti állományt.
move /y "%TARGET%.old" "%TARGET%" > nul 2>&1
del "%SOURCE%" > nul 2>&1
start "" "%TARGET%"
goto cleanup

:failed
del "%SOURCE%" > nul 2>&1
start "" "%TARGET%"

:cleanup
del "%~f0" > nul 2>&1
"""


def apply_update(new_exe_path):
    """Elindítja a cserét végző batch-et. A hívónak ezután ki kell lépnie.

    A batch megvárja, míg a futó .exe elengedi a fájlt, lecseréli az újra,
    majd újraindítja az alkalmazást.
    """
    if not is_frozen():
        raise UpdateError('A frissítés csak a csomagolt .exe verzióban '
                          'működik (forrásból: git pull).')
    if not os.path.exists(new_exe_path):
        raise UpdateError('A letöltött frissítés nem található.')

    target = current_exe()
    fd, batch_path = tempfile.mkstemp(prefix='ebevTool_update_', suffix='.bat',
                                      dir=os.path.dirname(target))
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(_SWAP_BATCH.format(target=target, source=os.path.abspath(new_exe_path)))

    creationflags = 0
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        creationflags |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, 'DETACHED_PROCESS'):
        creationflags |= subprocess.DETACHED_PROCESS

    try:
        subprocess.Popen(['cmd', '/c', batch_path], creationflags=creationflags,
                         close_fds=True)
    except Exception as e:
        _silent_remove(batch_path)
        _silent_remove(new_exe_path)
        raise UpdateError(f'A frissítés indítása nem sikerült: {e}') from e


def cleanup_leftovers():
    """A korábbi frissítés maradékainak eltakarítása (csendben, hiba esetén is).

    Induláskor érdemes meghívni: a '.old' fájlt a batch általában törli, de ha
    a régi példány még futott, ottmaradhat.
    """
    if not is_frozen():
        return
    exe = current_exe()
    _silent_remove(exe + '.old')
    folder = os.path.dirname(exe)
    try:
        for name in os.listdir(folder):
            if name.startswith('ebevTool_update_') and name.endswith(('.bat', '.exe')):
                path = os.path.join(folder, name)
                # Csak a régebbi, biztosan elárvult fájlokat töröljük.
                try:
                    if os.path.getmtime(path) < os.path.getmtime(exe):
                        _silent_remove(path)
                except Exception:
                    pass
    except Exception:
        pass
