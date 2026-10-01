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


def short_path(path):
    """A Windows rövid (8.3) útvonala, ami garantáltan ékezetmentes.

    Erre azért van szükség, mert a cserét végző batch-et a cmd a rendszer
    kódlapján olvassa, a konzol kódlapja viszont ettől eltérhet (magyar
    Windowson tipikusan ANSI cp1250 / OEM cp852 / konzol UTF-8). Ha az
    útvonalban ékezet van — például a felhasználó neve miatt —, a cmd nem
    találja meg a fájlt, és a frissítés csendben elbukik.

    A rövid név ASCII, így minden kódlapon ugyanazt jelenti. Ha a rendszeren
    ki van kapcsolva a 8.3-as névgenerálás, az eredeti utat adjuk vissza.
    """
    if sys.platform != 'win32':
        return str(path)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 32768)
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return str(path)


def batch_safe_path(path):
    """A batch számára biztonságos útvonal: rövid (8.3) MAPPA + eredeti fájlnév.

    A mappát rövidítjük, mert az ékezetes lehet (felhasználónév), és a csere
    alatt végig létezik. A fájlnevet viszont NEM: a csere közben a régi fájl
    átnevezésre kerül, így a rövid neve (pl. STATIS~1.EXE) megszűnik, és a
    'move' szó szerint ezen a néven hozná létre az új .exe-t. A fájlnév csak
    akkor rövidül, ha nem ASCII — ezt a batch máshogy nem tudná leírni.
    """
    folder, name = os.path.split(os.path.abspath(path))
    if not name.isascii():
        return short_path(path)
    return os.path.join(short_path(folder), name)


def can_write_target():
    """Igaz, ha a futó .exe mappájába tudunk írni.

    A cserét egy batch végzi, ami átnevezi és felülírja az .exe-t — ehhez
    írásjog kell a mappára. Ha a program 'Program Files' alá van telepítve,
    ez rendszergazda nélkül nem megy, és a frissítés csendben elhalna.
    Inkább előre megnézzük, és érthető üzenetet adunk.
    """
    if not is_frozen():
        return False
    folder = os.path.dirname(current_exe())
    try:
        fd, probe = tempfile.mkstemp(prefix='.ebevTool_write_test_', dir=folder)
        os.close(fd)
        _silent_remove(probe)
        return True
    except Exception:
        return False


def _update_workdir():
    """Az ideiglenes frissítő-fájlok helye.

    Nem az .exe mellé dolgozunk: ott a felhasználó látja a félkész fájlokat,
    és a Program Files alatt írásjogunk sem feltétlenül van. A rendszer temp
    mappája viszont más köteten lehet, ahonnan a batch 'move' parancsa nem
    tudja átvinni a fájlt — ezért ilyenkor egy saját almappát használunk a
    célkötet gyökerében, és azt a csere végén takarítjuk.
    """
    temp_dir = tempfile.gettempdir()
    if not is_frozen():
        return temp_dir
    try:
        exe_drive = os.path.splitdrive(current_exe())[0].upper()
        temp_drive = os.path.splitdrive(os.path.abspath(temp_dir))[0].upper()
        if exe_drive and exe_drive == temp_drive:
            return temp_dir
        # Eltérő kötet: a célkötetre tesszük, hogy a 'move' atomikus maradjon.
        fallback = os.path.join(exe_drive + os.sep, 'ebevTool_update_tmp')
        os.makedirs(fallback, exist_ok=True)
        return fallback
    except Exception:
        return temp_dir


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

    fd, temp_path = tempfile.mkstemp(prefix='ebevTool_update_', suffix='.exe',
                                     dir=_update_workdir())
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
#
# Három dologra kell figyelni:
#   * a 'move' köteten belül átnevez, köteten át viszont másol — ha a forrás
#     más meghajtón van, a parancs lassabb, de működik; a célfájl zárolása
#     viszont mindkét esetben megbukhat, ezért újrapróbálunk;
#   * a 'move' hibakódját nem az 'errorlevel' jelzi megbízhatóan minden
#     Windows-verzión, ezért a csere tényét a fájl létezésével ellenőrizzük;
#   * a batch szövege ASCII — ékezet nélkül! A cmd a sorokat a rendszer
#     kódlapján olvassa, ezért az UTF-8 ékezetek eltörhetnek, és a szétesett
#     'rem' sorok parancsként futnának le.
_SWAP_BATCH = """@echo off
set "TARGET={target}"
set "SOURCE={source}"
set "BACKUP=%TARGET%.old"

rem Megvarjuk, mig a futo peldany kilep es elengedi a fajlt (max ~60 mp).
set /a TRIES=0
:wait
set /a TRIES+=1
if %TRIES% GTR 120 goto failed
move /y "%TARGET%" "%BACKUP%" > nul 2>&1
if exist "%TARGET%" (
    ping -n 2 127.0.0.1 > nul
    goto wait
)

rem A csere: koteten at ez masolas, ezert eltarthat par masodpercig.
move /y "%SOURCE%" "%TARGET%" > nul 2>&1
if not exist "%TARGET%" goto restore

rem A regi peldanyt meg az ujrainditas elott takaritjuk el, hogy ne
rem zarolhassa az elindulo uj verzio. Ha megis bent marad, a program
rem indulaskori cleanup_leftovers() hivasa kesobb torli.
del "%BACKUP%" > nul 2>&1
start "" "%TARGET%"
goto cleanup

:restore
rem A csere nem sikerult - visszaallitjuk az eredeti allomanyt.
if exist "%BACKUP%" move /y "%BACKUP%" "%TARGET%" > nul 2>&1
del "%SOURCE%" > nul 2>&1
if exist "%TARGET%" start "" "%TARGET%"
goto cleanup

:failed
rem A futo peldany nem engedte el a fajlt - nem cserelunk, csak takaritunk.
del "%SOURCE%" > nul 2>&1
if exist "%BACKUP%" if not exist "%TARGET%" move /y "%BACKUP%" "%TARGET%" > nul 2>&1
if exist "%TARGET%" start "" "%TARGET%"

:cleanup
del "%~f0" > nul 2>&1
"""


def _clean_child_env():
    """A futó példány környezete a PyInstaller saját változói nélkül.

    A csomagolt .exe induláskor _PYI_* változókba írja a saját ideiglenes
    mappáját. Ha ezeket a cserélő batch örökli, az általa újraindított új
    .exe — mivel ugyanazon az útvonalon van — a régi példány gyerekének hiszi
    magát, és annak (kilépéskor már törölt) mappájából töltené a Pythont:
    „Failed to load Python DLL”. A PYINSTALLER_RESET_ENVIRONMENT=1 a
    PyInstaller előírt jelzése arra, hogy az új folyamat önálló példány.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper.startswith('_PYI_') or upper in ('_MEIPASS', '_MEIPASS2'):
            continue
        if meipass and meipass.lower() in value.lower():
            if ';' in value:
                # útvonal-lista (pl. PATH): csak a régi mappára mutató elemek mennek
                value = ';'.join(p for p in value.split(';')
                                 if meipass.lower() not in p.lower())
            else:
                # pl. a tkinter TCL_LIBRARY / TK_LIBRARY változója
                continue
        env[key] = value
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


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
    if not can_write_target():
        raise UpdateError(
            'Az alkalmazás mappájába nincs írásjog, ezért a csere nem '
            'végezhető el:\n'
            f'{os.path.dirname(current_exe())}\n\n'
            'Indítsd a programot rendszergazdaként, vagy másold át egy olyan '
            'mappába, ahová írhatsz (pl. Dokumentumok).')

    target = current_exe()
    fd, batch_path = tempfile.mkstemp(prefix='ebevTool_update_', suffix='.bat',
                                      dir=_update_workdir())
    # Rövid (8.3) mappaútvonalakat adunk a batch-nek: azok ékezetmentesek, így
    # a cmd kódlapjától függetlenül megtalálja a fájlokat. Enélkül egy ékezetes
    # felhasználónévnél a csere csendben elbukna. A fájlnév marad (lásd
    # batch_safe_path), különben az új .exe 'STATIS~1.EXE' néven jönne létre.
    body = _SWAP_BATCH.format(target=batch_safe_path(target),
                              source=batch_safe_path(new_exe_path))
    # A batch szövege így végig ASCII — nincs kódlap-függő értelmezés.
    with os.fdopen(fd, 'wb') as f:
        f.write(body.encode('ascii', errors='replace'))

    # Csak CREATE_NO_WINDOW: a DETACHED_PROCESS mellett a Windows figyelmen
    # kívül hagyja, és a batch minden 'ping'-je saját, látható konzolablakot
    # kapna. Így a batch egy rejtett konzolt kap, amit a gyerekei is örökölnek.
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    try:
        subprocess.Popen(['cmd', '/c', batch_path], creationflags=creationflags,
                         close_fds=True, env=_clean_child_env())
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
    # A '.old' az .exe mellé kerül (a batch nevezi át) — ez marad a helyén.
    _silent_remove(exe + '.old')

    # A félkész letöltéseket és batch-eket a munkamappában keressük, de a régi
    # verziók még az .exe mellé tették, ezért ott is takarítunk.
    folders = {_update_workdir(), os.path.dirname(exe)}
    for folder in folders:
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
