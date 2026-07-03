import ctypes
from ctypes import wintypes

_APP_ENTROPY = b'ebevTool-config-v1'

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_ubyte)),
    ]


_crypt32 = ctypes.WinDLL('crypt32.dll')
_kernel32 = ctypes.WinDLL('kernel32.dll')

_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptProtectData.restype = wintypes.BOOL

_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL

_kernel32.LocalFree.argtypes = [ctypes.c_void_p]


class DPAPIError(Exception):
    pass


def _to_blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buf  # a buf-ot életben kell tartani, amíg a blob-ot használjuk


def _from_blob(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(blob.pbData)


def protect(data: bytes) -> bytes:
    """A megadott bájtsorozatot az aktuális Windows-felhasználóhoz és géphez
    köti; a visszaadott bájtok csak ugyanezzel a fiókkal fejthetők vissza."""
    in_blob, _in_buf = _to_blob(data)
    entropy_blob, _entropy_buf = _to_blob(_APP_ENTROPY)
    out_blob = DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob), 'ebevTool config', ctypes.byref(entropy_blob),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise DPAPIError(f'A titkosítás nem sikerült (Windows hibakód: {ctypes.GetLastError()}).')
    return _from_blob(out_blob)


def unprotect(data: bytes) -> bytes:
    """A protect() által titkosított bájtok visszafejtése. DPAPIError-t dob,
    ha az adat más felhasználótól/géptől származik, vagy sérült."""
    in_blob, _in_buf = _to_blob(data)
    entropy_blob, _entropy_buf = _to_blob(_APP_ENTROPY)
    out_blob = DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(entropy_blob),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise DPAPIError(f'A visszafejtés nem sikerült (Windows hibakód: {ctypes.GetLastError()}).')
    return _from_blob(out_blob)
