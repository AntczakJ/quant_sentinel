# Docker Guide — Quant Sentinel

## Co to jest Docker i po co nam to?

Docker pakuje cały projekt (Python, Node.js, modele ML, baza danych) w jeden "kontener" który działa identycznie na każdym komputerze. Zamiast instalować Python, pip, Node.js, npm osobno — uruchamiasz jedną komendę i wszystko działa.

**Kiedy Docker jest przydatny:**
- Chcesz uruchomić projekt na serwerze (VPS, cloud)
- Chcesz dać komuś dostęp bez tłumaczenia jak zainstalować 50 pakietów
- Chcesz mieć identyczne środowisko dev i produkcja
- Chcesz automatyczny restart po crashu

**Kiedy Docker NIE jest potrzebny:**
- Pracujesz lokalnie na swoim komputerze (tak jak teraz)
- Trenujesz modele (GPU passthrough w Docker jest skomplikowany)

---

## Instalacja Docker (jednorazowo)

### Windows 11

1. Pobierz **Docker Desktop** z https://www.docker.com/products/docker-desktop/
2. Zainstaluj (wymaga restart komputera)
3. Po restarcie Docker Desktop powinien uruchomić się automatycznie (ikonka wieloryba w zasobniku)
4. Otwórz terminal i sprawdź:

```bash
docker --version
# Docker version 27.x.x

docker compose version
# Docker Compose version v2.x.x
```

Jeśli oba polecenia działają — Docker jest gotowy.

---

## Pierwszy build (jednorazowo)

Otwórz terminal w folderze projektu (`C:\quant_sentinel`):

```bash
cd C:\quant_sentinel

# Buduje obraz — trwa 3-5 minut za pierwszym razem
docker compose build
```

**Co się dzieje:**
- Instaluje Node.js i buduje frontend (React → statyczne pliki)
- Instaluje Python i wszystkie pakiety z requirements.txt
- Kopiuje kod, modele, bazę danych do obrazu
- Następne buildy są szybsze (cache warstw)

---

## Uruchamianie

### Opcja 1: Tylko API + frontend (bez Telegram bota)

```bash
docker compose up -d
```

- `-d` = w tle (nie blokuje terminala)
- API dostępne na **http://localhost:8000**
- Frontend dostępny na **http://localhost:8000** (ten sam port)
- Scanner, resolver, WebSocket — wszystko działa automatycznie

### Opcja 2: API + Telegram bot

```bash
docker compose --profile with-bot up -d
```

- Uruchamia dodatkowo Telegram bota (czeka aż API będzie zdrowe)

### Sprawdzenie czy działa

```bash
# Status kontenerów
docker compose ps

# Powinieneś zobaczyć:
# NAME                    STATUS          PORTS
# quant-sentinel-api      Up (healthy)    0.0.0.0:8000->8000/tcp
```

Otwórz przeglądarkę: **http://localhost:8000** — powinieneś zobaczyć dashboard.

---

## Codzienne użycie

### Sprawdzenie logów

```bash
# Logi na żywo (Ctrl+C żeby wyjść)
docker compose logs -f backend

# Ostatnie 50 linii
docker compose logs --tail 50 backend
```

### Restart po zmianie kodu

```bash
# Przebuduj i zrestartuj
docker compose up -d --build
```

### Zatrzymanie

```bash
# Zatrzymaj (dane zachowane w data/, models/, logs/)
docker compose down

# Zatrzymaj i USUŃ dane (uwaga!)
docker compose down -v
```

### Sprawdzenie zdrowia

```bash
# Health check
curl http://localhost:8000/api/health

# Metryki
curl http://localhost:8000/api/metrics

# Risk manager status
curl http://localhost:8000/api/risk/status
```

---

## Ważne informacje

### Gdzie są moje dane?

Dane NIE są w kontenerze — są na Twoim dysku:

| Folder na dysku | W kontenerze | Co zawiera |
|-----------------|--------------|------------|
| `C:\quant_sentinel\data\` | `/app/data/` | Baza danych (sentinel.db) |
| `C:\quant_sentinel\models\` | `/app/models/` | Modele ML (xgb.pkl, lstm.keras, ...) |
| `C:\quant_sentinel\logs\` | `/app/logs/` | Logi aplikacji |

Jeśli usuniesz kontener (`docker compose down`) — dane zostają.
Jeśli usuniesz kontener z `-v` (`docker compose down -v`) — dane zostają (bo to bind mounts, nie volumes).

### Zmienne środowiskowe (.env)

Docker czyta `.env` automatycznie. Jeśli zmienisz `.env`, zrestartuj:

```bash
docker compose up -d --force-recreate
```

### Trenowanie modeli

**NIE trenuj modeli wewnątrz Dockera** — GPU nie będzie dostępne (chyba że skonfigurujesz NVIDIA Container Toolkit, co jest skomplikowane na Windows).

Trenuj lokalnie jak dotychczas:

```bash
# Lokalnie (bez Dockera) — GPU działa normalnie
python train_all.py --epochs 100 --rl-episodes 500
```

Modele zapisują się do `models/` → Docker automatycznie je widzi (mounted volume).

### Zmiana portu

Domyślnie API jest na porcie 8000. Żeby zmienić:

```bash
# W .env dodaj:
PORT=3000

# Lub uruchom z innym portem:
PORT=3000 docker compose up -d
```

---

## Rozwiązywanie problemów

### "Cannot connect to the Docker daemon"
→ Docker Desktop nie jest uruchomiony. Uruchom go z menu Start.

### "Port 8000 already in use"
→ Coś innego używa portu. Zmień port w .env (`PORT=8001`) lub zatrzymaj co blokuje port.

### "Build failed: npm ci"
→ Problem z node_modules. Sprawdź czy `frontend/package-lock.json` istnieje.

### "Health check: unhealthy"
→ Sprawdź logi: `docker compose logs backend`
→ Częsta przyczyna: brak API keys w .env

### Kontener restartuje się w pętli
```bash
# Sprawdź dlaczego
docker compose logs --tail 100 backend

# Najczęstsza przyczyna: brak .env lub brak modeli
```

---

## Aktualizacja projektu

Jeśli zmieniłeś kod i chcesz zaktualizować kontener:

```bash
# 1. Przebuduj obraz
docker compose build

# 2. Zrestartuj z nowym obrazem
docker compose up -d
```

Skrót (build + restart w jednym):

```bash
docker compose up -d --build
```

---

## Produkcja (serwer VPS)

Jeśli chcesz uruchomić na zdalnym serwerze:

1. Zainstaluj Docker na serwerze (Ubuntu): `curl -fsSL https://get.docker.com | sh`
2. Skopiuj projekt na serwer: `scp -r C:\quant_sentinel user@server:/home/user/`
3. Skopiuj `.env` na serwer
4. Na serwerze:
   ```bash
   cd /home/user/quant_sentinel
   docker compose up -d --build
   ```
5. API dostępne na `http://server-ip:8000`

Dla HTTPS (SSL) — dodaj reverse proxy (Caddy jest najłatwiejszy):

```bash
# Zainstaluj Caddy
sudo apt install caddy

# /etc/caddy/Caddyfile:
yourdomain.com {
    reverse_proxy localhost:8000
}

# Restart Caddy (automatycznie uzyska SSL certyfikat od Let's Encrypt)
sudo systemctl restart caddy
```
