"""
technical_analysis.py — zaawansowana analiza techniczna na danych OHLCV.

Odpowiada za:
  - Wyznaczanie trendu na podstawie SMA(50) z danych dziennych (D1)
  - Obliczanie RSI(14) z danych godzinnych (H1)
  - Analizę wolumenu (porównanie bieżącego wolumenu do średniej 20-godzinnej)

Moduł używa biblioteki pandas_ta do obliczania wskaźników technicznych.

Uwaga: ten moduł nie jest aktualnie podpięty do głównego bota (main.py).
Przeznaczony do integracji z fusion_engine.py jako źródło analizy wykresowej.
Aby go użyć, przekaż DataFrames z danymi D1 i H1 do ChartAnalyzer.analyze_full().
"""

import pandas_ta as ta


class ChartAnalyzer:
    """
    Analizator techniczny operujący na dwóch interwałach jednocześnie:
      - df_daily  (D1) — do wyznaczania trendu długoterminowego
      - df_hourly (H1) — do wyznaczania momentu wejścia (RSI, wolumen)
    """

    def analyze_full(self, df_daily, df_hourly) -> dict | None:
        """
        Wykonuje pełną analizę techniczną na danych dziennych i godzinnych.

        Parametry:
            df_daily  — DataFrame z danymi OHLCV dla interwału D1
                        (musi zawierać kolumny: Close, SMA_50 zostanie dodane)
            df_hourly — DataFrame z danymi OHLCV dla interwału H1
                        (musi zawierać kolumny: Close, Volume)

        Zwraca:
            Słownik z wynikami analizy:
              - trend      : "Wzrostowy" jeśli cena > SMA(50), inaczej "Spadkowy"
              - rsi        : wartość RSI(14) dla ostatniej świecy H1
              - vol_status : "WYSOKI (Potwierdzenie)" lub "NISKI (Ostrzeżenie)"
              - price      : ostatnia cena zamknięcia D1

            None — jeśli którykolwiek DataFrame jest pusty.

        Logika wolumenu:
            Wysoki wolumen przy ruchu = potwierdzenie trendu (instytucje uczestniczą)
            Niski wolumen przy ruchu = ostrzeżenie (ruch może być fałszywy)
        """
        if df_daily.empty or df_hourly.empty:
            return None

        # --- TREND D1 (na podstawie SMA 50) ---
        # SMA(50) to klasyczny filtr trendu — cena powyżej = bull, poniżej = bear
        df_daily.ta.sma(length=50, append=True)  # Dodaje kolumnę SMA_50 do DataFrame
        current_price = df_daily['Close'].iloc[-1]
        sma50 = df_daily['SMA_50'].iloc[-1]
        trend = "Wzrostowy" if current_price > sma50 else "Spadkowy"

        # --- RSI H1 (momentum na godzinowym) ---
        # RSI < 30 = wyprzedany (możliwe odbicie w górę)
        # RSI > 70 = wykupiony (możliwa korekta w dół)
        df_hourly.ta.rsi(length=14, append=True)  # Dodaje kolumnę RSI_14
        rsi = df_hourly['RSI_14'].iloc[-1]

        # --- ANALIZA WOLUMENU H1 ---
        # Porównujemy bieżący wolumen do 20-godzinnej średniej kroczącej wolumenu
        df_hourly.ta.sma(
            close=df_hourly['Volume'], length=20,
            append=True, col_names="SMA_VOL"
        )
        avg_vol = df_hourly['SMA_VOL'].iloc[-1]
        curr_vol = df_hourly['Volume'].iloc[-1]
        vol_confirm = (
            "WYSOKI (Potwierdzenie)" if curr_vol > avg_vol
            else "NISKI (Ostrzeżenie)"
        )

        return {
            "trend": trend,
            "rsi": round(float(rsi), 2),
            "vol_status": vol_confirm,
            "price": round(current_price, 2)
        }

