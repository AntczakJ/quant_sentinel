"""
__init__.py — oznacza katalog src/ jako pakiet Pythona.

Dzięki temu możliwe są importy w stylu:
    from src.core.config import TOKEN
    from src.core.database import NewsDB
    from src.main import run_bot

Plik celowo pozostaje pusty — inicjalizacja modułów odbywa się
w ich własnych plikach, nie tutaj.
"""
