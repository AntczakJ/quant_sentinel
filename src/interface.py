"""
interface.py — definicje klawiatur inline dla bota Telegram.

Odpowiada za:
  - Budowanie obiektów InlineKeyboardMarkup używanych w wiadomościach
  - main_menu() — główne menu dashboardu
  - tf_menu()   — podmenu wyboru interwału czasowego

Każdy przycisk ma przypisany callback_data, który jest obsługiwany
przez handle_buttons() w main.py.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    """
    Buduje i zwraca główne menu bota.

    Układ przycisków:
      Rząd 1: Analiza Quant PRO (główna funkcja)
      Rząd 2: Status systemu | Newsy
      Rząd 3: Sentyment AI | Interwał
      Rząd 4: Wykres | Portfel
      Rząd 5: Pomoc
    """
    keyboard = [
        [
            InlineKeyboardButton("🎯 ANALIZA QUANT PRO", callback_data='smc_pro'),
        ],
        [
            InlineKeyboardButton("📊 STATUS SYSTEMU", callback_data='status_check'),
            InlineKeyboardButton("📰 NEWSY (XTB)", callback_data='news'),
        ],
        [
            InlineKeyboardButton("🎭 SENTYMENT AI", callback_data='sentiment'),
            InlineKeyboardButton("⏱ INTERWAŁ", callback_data='menu_tf'),
        ],
        [
            InlineKeyboardButton("📈 WYKRES", callback_data='chart_action'),
            InlineKeyboardButton("⚙️ PORTFEL", callback_data='change_cap'),
        ],
        [InlineKeyboardButton("📖 POMOC", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)


def tf_menu() -> InlineKeyboardMarkup:
    """
    Buduje i zwraca podmenu wyboru interwału czasowego.

    Dostępne interwały: 15m, 1h, 4h.
    Wybrany interwał jest zapisywany w USER_PREFS['tf'] przez handle_buttons().
    Przycisk Powrót wraca do głównego menu.
    """
    keyboard = [
        [
            InlineKeyboardButton("15m", callback_data='set_15m'),
            InlineKeyboardButton("1h", callback_data='set_1h'),
            InlineKeyboardButton("4h", callback_data='set_4h')
        ],
        [InlineKeyboardButton("⬅️ Powrót", callback_data='back')]
    ]
    return InlineKeyboardMarkup(keyboard)
