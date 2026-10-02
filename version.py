"""Az alkalmazás verziószáma és verzió-összehasonlítás.

A verziószám formátuma dátum alapú: ÉÉÉÉ.HH.NN[.n], pl. '2026.08.04' vagy
'2026.08.04.2' (ha egy napon több kiadás készül). Ugyanez a szám kerül a
GitHub release tag-jébe is, így a kettő közvetlenül összehasonlítható.

Kiadáskor EZT az egy sort kell átírni, majd ugyanezzel a névvel tag-elni:
    git tag 2026.08.04 && git push origin 2026.08.04
"""

__version__ = '2026.10.02.3'

# A GitHub repó, ahonnan a frissítés érkezik (publikus, token nem kell).
GITHUB_OWNER = 'Kopoklesz'
GITHUB_REPO = 'ebevTool'

RELEASES_PAGE = f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest'
RELEASES_API = (f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}'
                '/releases/latest')


def parse_version(text):
    """Verziószám -> összehasonlítható számlista.

    Elfogadja a 'v' előtagot és a záró pontot is ('v2026.08.04.' -> [2026,8,4]).
    A nem szám részeket 0-ként kezeli, így egy elrontott tag sem okoz hibát.
    """
    cleaned = str(text or '').strip().lstrip('vV').rstrip('.').strip()
    parts = []
    for chunk in cleaned.split('.'):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parts.append(int(chunk))
        except ValueError:
            digits = ''.join(c for c in chunk if c.isdigit())
            parts.append(int(digits) if digits else 0)
    return parts or [0]


def is_newer(candidate, current=__version__):
    """Igaz, ha a 'candidate' verzió újabb, mint a 'current'.

    A rövidebb verziószámot nullákkal egészítjük ki, így a '2026.08.04' és a
    '2026.08.04.0' egyenértékű, a '2026.08.04.1' pedig újabb náluk.
    """
    a, b = parse_version(candidate), parse_version(current)
    length = max(len(a), len(b))
    a += [0] * (length - len(a))
    b += [0] * (length - len(b))
    return a > b
