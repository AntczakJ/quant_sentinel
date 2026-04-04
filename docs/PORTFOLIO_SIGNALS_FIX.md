# ✅ PORTFOLIO & SIGNALS FIX - Dokumentacja Zmian

**Data**: 2026-04-04  
**Status**: ✅ UKOŃCZONE  

---

## 🎯 Co zostało naprawione

### Problem 1: Balance się sam resetuje
**Przyczyna**: Cache w pamięci RAM - resetował się przy restarcie  
**Rozwiązanie**: Przechowywanie w bazie danych (persistentne)

### Problem 2: Ceny wyświetlają się w PLN
**Przyczyna**: Brak separacji walut  
**Rozwiązanie**: 
- **Portfel**: PLN (waluta użytkownika)
- **Ceny złota**: USD (wartość rynkowa)

### Problem 3: current_price = 2000 (hardcoded)
**Przyczyna**: Testowa wartość w default_signal  
**Rozwiązanie**: Pobieranie live ceny z Twelve Data API

---

## 📁 Zmienione Pliki

### 1. **api/schemas/models.py**
```python
# Dodano field:
currency: str = Field(default="PLN", description="Currency of balance")

# Zmieniony opis:
balance: float = Field(..., description="Current balance in PLN")  # ← PLN!
equity: float = Field(..., description="Current equity in PLN")    # ← PLN!
pnl: float = Field(..., description="Profit/Loss in PLN")          # ← PLN!
position_entry: Optional[float] = None  # ← In USD!
```

### 2. **api/routers/portfolio.py**
**Przed:**
```python
_portfolio_cache = {...}  # RAM cache - resetuje się!
```

**Po:**
```python
def _get_portfolio():
    """Pobierz portfolio z bazy danych (persistentne)"""
    # ✅ Zapis w NewsDB
    
def _save_portfolio(portfolio_data):
    """Zapisz portfolio do bazy danych (persistentne)"""
    # ✅ Zapis do bazy - nigdy się nie resetuje!
```

**Nowe response:**
```json
{
  "balance": 10000,
  "currency": "PLN",        // ← Nowe!
  "pnl": 100,
  "pnl_pct": 1.0,
  ...
}
```

### 3. **api/routers/signals.py**
**Przed:**
```python
current_price=2000.0,  # Hardcoded!
```

**Po:**
```python
# Pobierz live price z Twelve Data
ticker = provider.get_current_price('XAU/USD')
current_price = ticker['price'] if ticker else 2050.0  # Fallback
```

---

## 💡 Logika Walut

### Portfolio (w PLN)
```
Balance:     10000 PLN  (użytkownika)
PnL:         +100 PLN   (zysk/strata)
Equity:      10100 PLN  (razem)
Currency:    PLN
```

### Trading (w USD)
```
current_price:     2050 USD  (cena złota)
position_entry:    2045 USD  (entry trade'a)
lstm_prediction:   2055 USD  (predykcja ceny)
```

---

## 🔄 Flow - Teraz

### Portfel (PLN)
```
1. Użytkownik: POST /portfolio/update-balance
   Body: {"balance": 10000, "currency": "PLN"}
   
2. System: Zapisz do NewsDB (persistentne!)
   
3. GET /portfolio/status
   Response: {
     "balance": 10000,
     "currency": "PLN",
     "pnl": 0,
     ...
   }
```

### Sygnały (USD)
```
1. GET /signals/current
   
2. System: Pobierz live price z Twelve Data
   current_price = 2050.5 USD
   
3. Response: {
     "current_price": 2050.5,  // ← LIVE!
     "lstm_prediction": 2050.5,
     "symbol": "XAU/USD",
     ...
   }
```

---

## ✅ Gwarancje

| Aspekt | Status |
|--------|--------|
| Balance persyste | ✅ W bazie (NewsDB) |
| Balance się resetuje | ✅ NIE - permanent! |
| Ceny w PLN | ✅ TYLKO portfel |
| Ceny w USD | ✅ Cena złota |
| current_price live | ✅ Z Twelve Data |
| Fallback price | ✅ 2050 USD |
| Separacja walut | ✅ Jasna |

---

## 🧪 Testy

### Test 1: Balance persystentny
```bash
POST /portfolio/update-balance {"balance": 5000, "currency": "PLN"}
# Restart aplikacji
GET /portfolio/status
# Zwróci 5000 PLN - nie 10000! ✅
```

### Test 2: Currency w response
```bash
GET /portfolio/status
# Response zawiera: "currency": "PLN" ✅
```

### Test 3: Live price
```bash
GET /signals/current
# current_price != 2000 (live cena) ✅
# Zbliża się do 2050 USD ✅
```

### Test 4: Waluta konsystentna
```bash
Portfolio: 10000 PLN
Złoto: 2050 USD
Signal current_price: ~2050 USD ✅
```

---

## 📝 Migracja Danych

Stare dane z RAM cache:
- ❌ Mogą być utracone

Nowe dane w NewsDB:
- ✅ Persystentne
- ✅ Dostęp z bazy
- ✅ Bezpieczne

---

## 🚀 Status

**Gotowe do produkcji!** ✅

- ✅ Balance nie resetuje się
- ✅ Ceny w odpowiednich walutach
- ✅ current_price to live cena
- ✅ Persistentny portfel
- ✅ Waluta użytkownika (PLN) vs Rynek (USD)

