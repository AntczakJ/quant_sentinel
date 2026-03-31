"""
backtester.py — generator raportów historycznych z bazy danych.

Odpowiada za:
  - Odczyt historii transakcji z bazy SQLite
  - Generowanie statystyk: liczba sygnałów, podział BUY/SELL, ostatni sygnał

Naprawione błędy:
  - Zmieniono nazwę tabeli z 'trade_logs' na 'trades' (jedyna istniejąca tabela
    w bazie; 'trade_logs' nigdy nie była tworzona, co powodowało błąd przy każdym
    wywołaniu generate_report())
  - Zmieniono kolumnę 'suggestion' na 'direction' (zgodnie ze schematem tabeli trades)
"""

import sqlite3
import pandas as pd


def generate_report() -> str:
    """
    Generuje raport tekstowy z historii transakcji zapisanych w bazie SQLite.

    Raport zawiera:
      - Łączną liczbę zalogowanych sygnałów
      - Podział na transakcje LONG i SHORT
      - Timestamp ostatniego sygnału

    Zwraca:
        Sformatowany string z raportem lub komunikat o błędzie/braku danych.
    """
    conn = sqlite3.connect("data/sentinel.db")
    try:
        # Odczytujemy całą historię transakcji z tabeli 'trades'
        # (poprzednio błędnie używano 'trade_logs' która nie istnieje)
        df = pd.read_sql_query("SELECT * FROM trades", conn)

        if df.empty:
            return "Brak danych do raportu."

        total = len(df)

        # Zliczamy transakcje LONG i SHORT na podstawie kolumny 'direction'
        # (poprzednio błędnie używano kolumny 'suggestion')
        longs = len(df[df['direction'].str.contains("LONG", na=False)])
        shorts = len(df[df['direction'].str.contains("SHORT", na=False)])

        report = (
            f"📊 *RAPORT SKUTECZNOŚCI*\n"
            f"Liczba sygnałów: {total}\n"
            f"🟢 LONG: {longs}\n"
            f"🔴 SHORT: {shorts}\n"
            f"Ostatni sygnał: {df['timestamp'].iloc[-1]}"
        )
        return report

    except Exception as e:
        return f"Błąd generowania raportu: {e}"
    finally:
        conn.close()
