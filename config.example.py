"""Konfigurációs sablon.

Másold le ezt a fájlt `config.py` néven, és töltsd ki az értékeket a
FIREBASE_SETUP.md útmutató alapján. A config.py NEM kerül verziókezelésbe
(.gitignore), de a PyInstaller build belefordítja az exe-be.
"""

# Firebase projekt Web API kulcsa (Project settings → General → Web API Key).
FIREBASE_API_KEY = 'IDE_A_WEB_API_KEY'

# Firebase projekt azonosító (Project settings → Project ID)
FIREBASE_PROJECT_ID = 'ide-a-project-id'

# Fernet titkosítási kulcs a személyes adatok kliensoldali titkosításához.
# Generálás (egyszer!):
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# FIGYELEM: ha ez a kulcs elveszik vagy megváltozik, a Firestore-ban tárolt
# rekordok visszafejthetetlenné válnak!
FERNET_KEY = 'IDE_A_FERNET_KULCS'

# Helyi archívum mappa; None esetén a program melletti 'archívum' almappa.
ARCHIVE_DIR = None
