"""
webhook_reciever.py — standalone serwer Flask dla alertów TradingView.

Alternatywa dla webhooka wbudowanego w main.py. Uruchamia się jako osobny
proces i przekazuje alerty z TradingView na Telegram przez notifier.py.

Kiedy używać tego pliku zamiast webhooka z main.py:
  - Gdy chcesz uruchomić webhook na osobnym porcie lub serwerze
  - Gdy testujesz integrację TradingView bez uruchamiania całego bota

Konfiguracja TradingView:
  - URL webhooka: http://TWOJ_IP:5000/webhook
  - Metoda: POST
  - Typ: JSON
  - Przykładowy payload:
    {
      "action": "BUY",
      "price": "{{close}}",
      "indicator": "RSI",
      "time": "{{time}}"
    }

Uruchomienie:
    python webhook_reciever.py
"""

from flask import Flask, request, jsonify
from src.notifier import send_alert

app = Flask(__name__)


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint przyjmujący alerty z TradingView.

    TradingView wysyła POST z JSON zawierającym dane alertu.
    Handler formatuje wiadomość i przekazuje ją na Telegram przez send_alert().

    Oczekiwane pola JSON:
      - action    : akcja sygnału (np. "BUY", "SELL", "ALERT")
      - price     : cena w momencie alertu
      - indicator : nazwa wskaźnika który wygenerował sygnał
      - time      : czas alertu (string)

    Zwraca:
        JSON {"status": "success"} z kodem 200 jeśli alert został przetworzony.
    """
    data = request.json
    print(f"Otrzymano sygnał z TradingView: {data}")

    msg = (
        f"🔔 *SYGNAŁ Z TRADINGVIEW*\n\n"
        f"📈 Akcja: {data.get('action')}\n"
        f"💰 Cena: {data.get('price')}\n"
        f"📊 Wskaźnik: {data.get('indicator')}\n"
        f"⏰ Czas: {data.get('time')}"
    )

    send_alert(msg)
    return jsonify({"status": "success"}), 200


if __name__ == '__main__':
    # Uruchamiamy na porcie 5000 dostępnym z zewnątrz
    app.run(port=5000)
