# Jarvis — Otomatik Trading Botu & Dashboard

**Binance.TR Spot** piyasasını gerçek zamanlı tarayan, çok zaman dilimli **OCC (Open Close Cross)** sinyalleri üreten, otomatik alım/satım yapan ve tüm verileri web tabanlı dashboard'da sunan tam kapsamlı trading sistemi.

---

## Mimari

```
Binance.TR API (www.binance.tr)
        │
        ▼
  scanner.py  ──────────────────► MongoDB (signals: PENDING)
  (Multi-TF OCC, 5 zaman dilimi)       │
                                        ▼
  order_worker.py ◄──── MongoDB    Spot Alım Emri Aç
  (Otomatik İşlem Motoru)              │
                                        ▼
                                   MongoDB (positions: OPEN)
                                        │
                                        ▼
                                   SL/TP Takibi → Spot Satış
                                        │
                                        ▼
  dashboard_backend/server.js       MongoDB (positions: CLOSED)
  (Express + Socket.io, port 5001)
        │
        ├─ /api/binance/*  ──► Binance.TR API (proxy)
        ├─ /api/signals/*  ──► MongoDB
        └─ /api/positions/* ─► MongoDB
                │
                ▼
  dashboard_frontend/   (React 18 + Vite + Tailwind CSS v4)
  http://localhost:5001
```

---

## Sinyal Üretme Altyapısı

### OCC (Open Close Cross) İndikatörü
Her zaman diliminde `Close MA > Open MA` durumunu kontrol eder:
- **Yeşil** = yükseliş momentumu
- **Kırmızı** = düşüş momentumu
- MA tipi: **SMMA** (Pine Script OCC ile birebir), periyot: 8

### Ağırlıklı Puanlama

| Zaman Dilimi | Ağırlık | Rol |
|---|---|---|
| 1 Günlük | 3 puan | Yön belirler |
| 4 Saatlik | 2 puan | Giriş penceresi |
| 1 Saatlik | 2 puan | Zamanlama |
| 15 Dakika | 1 puan | Zamanlama |
| 5 Dakika | 0 puan | Tetikleyici |

**Maksimum 8 puan — sinyal için minimum 5 puan gerekli.**

### Yıldız Sistemi & Pozisyon Büyüklüğü

| Puan | Yıldız | Kullanılabilir Bakiyeden |
|---|---|---|
| 7–8 | ⭐⭐⭐ Full Sniper | %24 |
| 6 | ⭐⭐ Güçlü Sinyal | %35 |
| 5 | ⭐ Fırsat | %44 |

### Filtreler
- **RSI** (14): 30–50 ideal giriş, 80+ sinyal engeller
- **ADX** (14): trend gücü filtresi, ayarlanabilir eşik

### Sinyal Akışı
```
Scanner → MongoDB (PENDING) → order_worker → Binance.TR emir → EXECUTED
```

---

## Özellikler

### Scanner (`scanner.py`)
- Tüm TRY/USDT paritelerini 5 zaman diliminde tarar
- OCC yeşil yakıldığında puan hesaplar, eşiği geçince sinyal üretir
- Sinyaller MongoDB'ye kaydedilir, Telegram'a gönderilir
- PM2 ile arka planda sürekli çalışır (her 5 dakika)

### Order Worker (`order_worker.py`)
- MongoDB'deki `PENDING` sinyalleri işler
- Kullanılabilir bakiyenin yıldıza göre %'sini kullanarak spot alım emri açar
- Yazılım tabanlı **SL/TP koruması** (her 60s fiyat kontrolü)
- SL'ye düşünce veya TP'ye çıkınca otomatik satış

### Dashboard (`http://localhost:5001`)

| Sekme | İçerik |
|---|---|
| **Genel Bakış** | Bakiye, açık pozisyonlar (alım fiyatı, güncel fiyat, PnL %, SL/TP), açık emirler, bot işlem geçmişi, istatistikler |
| **Piyasa** | Tüm TRY/USDT pariteleri, 3s güncellemeli fiyat/değişim/hacim, arama, gainers/losers filtresi |
| **Chart & Emir** | TradingView Advanced Chart (çizim araçları, indikatörler), 587 coin aranabilir dropdown, order book |
| **Sinyal Kartları** | OCC sinyal kartları (SL/TP, R:R oranı, TF heatmap, RSI/ADX, yıldız) |
| **Canlı Log** | Socket.io üzerinden gerçek zamanlı scanner log akışı, log seviyesi filtresi |

---

## Kurulum

### Gereksinimler
- Python 3.9+
- Node.js 18+
- MongoDB (yerel, port 27017)
- PM2: `npm install -g pm2`
- Binance.TR hesabı + API anahtarı (okuma + işlem izni)
- Telegram bot (opsiyonel)

### 1. Python bağımlılıkları

```bash
pip install -r requirements.txt
```

### 2. Ortam değişkenleri

```bash
nano .env
```

```env
BINANCE_API_KEY=your_binance_tr_api_key
BINANCE_API_SECRET=your_binance_tr_api_secret
QUOTE_ASSET=TRY
MAX_BUDGET_PER_TRADE=500
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Backend bağımlılıkları

```bash
cd dashboard_backend && npm install
```

### 4. Frontend build

```bash
cd dashboard_frontend && npm install && npm run build
```

### 5. PM2 ile tüm sistemi başlat

```bash
pm2 start ecosystem.config.js
pm2 save
```

---

## PM2 Süreçleri

```
┌────┬────────────────────┬──────────┬──────────┐
│ id │ name               │ mode     │ status   │
├────┼────────────────────┼──────────┼──────────┤
│ 0  │ trade-scanner      │ fork     │ online   │
│ 1  │ jarvis-backend-api │ fork     │ online   │
│ 2  │ order-worker       │ fork     │ online   │
└────┴────────────────────┴──────────┴──────────┘
```

```bash
pm2 list                          # Durum
pm2 logs trade-scanner            # Scanner logları
pm2 logs order-worker             # Order worker logları
pm2 logs jarvis-backend-api       # API logları
pm2 restart all                   # Tümünü yeniden başlat
```

---

## Yapılandırma (`config.py`)

| Parametre | Açıklama | Değer |
|---|---|---|
| `SCAN_INTERVAL` | Tarama aralığı | `300s` |
| `OCC_MIN_SCORE` | Minimum sinyal puanı | `5` |
| `VOLUME_FILTER.enabled` | Hacim filtresi | `False` (kapalı) |
| `MIN_VOLUME_USDT` | Min 24s hacim | `0` (devre dışı) |
| `ALERT_COOLDOWN_MINUTES` | Aynı coin için cooldown | `30 dk` |

### Yıldız / Pozisyon büyüklüğü (`SIGNAL_FILTER.star_rating.tiers`)

```python
{"min_score": 7, "stars": "⭐⭐⭐", "label": "Full Sniper",  "position_pct": 24},
{"min_score": 6, "stars": "⭐⭐",   "label": "Güçlü Sinyal", "position_pct": 35},
{"min_score": 5, "stars": "⭐",     "label": "Fırsat",        "position_pct": 44},
```

`position_pct` → kullanılabilir bakiyenin yüzdesi.

---

## API Endpoint'leri

```
GET /api/binance/balance          Hesap bakiyesi
GET /api/binance/positions        Açık pozisyonlar (SL/TP dahil)
GET /api/binance/open-orders      Açık emirler
GET /api/binance/income           Gerçekleşen PnL geçmişi
GET /api/binance/all-tickers      Tüm parite ticker'ları
GET /api/binance/klines           Mum verisi
GET /api/binance/orderbook        Order book (20 seviye)
GET /api/binance/ticker           Tek coin 24s ticker

GET /api/signals/recent           Son sinyaller (MongoDB)
GET /api/signals/pending          Bekleyen sinyaller
GET /api/positions/open           Açık bot pozisyonları
GET /api/positions/history        Kapalı pozisyon geçmişi
GET /api/stats                    Genel istatistikler
GET /api/health                   Sağlık kontrolü
```

---

## Dosya Yapısı

```
trade/
├── scanner.py                # Multi-TF OCC tarayıcı
├── analyzer.py               # OCC + RSI/ADX analiz motoru
├── market_data.py            # Binance.TR API istemcisi
├── order_worker.py           # Otomatik alım/satım motoru
├── config.py                 # Tüm yapılandırma sabitleri
├── telegram_notifier.py      # Telegram bildirim modülü
├── chart_gen.py              # Grafik oluşturucu
├── backtest.py               # Geriye dönük test
├── ecosystem.config.js       # PM2 süreç yapılandırması
├── requirements.txt
├── .env
│
├── dashboard_backend/
│   ├── server.js             # Express API + Socket.io (port 5001)
│   └── package.json
│
└── dashboard_frontend/
    ├── src/
    │   ├── App.jsx           # Ana dashboard (5 sekme)
    │   └── index.css         # Tailwind CSS v4
    └── package.json
```

---

## Güvenlik Notları

- API anahtarlarını asla kaynak koduna yazmayın, `.env` kullanın
- Binance.TR API key'ini **sadece** çalıştığı IP'ye kısıtlayın
- `.env` dosyası `.gitignore`'a eklenmiştir


## Önemli Uyarılar

- Bu sistem **finansal tavsiye vermez**, teknik analiz sinyalleri üretir.
- Kaldıraçlı işlemler yüksek risk içerir. Tüm yatırım kararları **sizin sorumluluğunuzdadır**.
- `order_worker.py` içindeki `"enabled": True` ile **canlı emir açılır**. Test için `False` yapın.
- API anahtarınızı `.env` dışında **asla paylaşmayın**.
