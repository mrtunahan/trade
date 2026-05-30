# Jarvis — Binance Futures Trading Bot & Dashboard

Binance **USDT-M Perpetual Futures** piyasasını gerçek zamanlı tarayan, çok zaman dilimli OCC (Oluşum-Kesişim-Onay) sinyalleri üreten, otomatik emir açan ve tüm verileri web tabanlı bir dashboard'da sunan tam kapsamlı trading sistemi.

---

## Mimari

```
Binance fapi.binance.com
        │
        ▼
  scanner.py  ──────────────────► MongoDB (signals)
  (Multi-TF OCC)                       │
                                        ▼
  order_worker.py ◄──── MongoDB ──► Futures Emir Aç/Kapat
  (Otomatik İşlem)                     │
                                        ▼
  dashboard_backend/server.js       MongoDB (positions)
  (Express + Socket.io)                 │
        │                               │
        ├─ /api/binance/*  ─────────────► fapi.binance.com (proxy)
        ├─ /api/signals/*  ─────────────► MongoDB
        └─ /api/positions/* ────────────► MongoDB
                │
                ▼
  dashboard_frontend/   (React + Vite + Tailwind)
  http://localhost:5001
```

---

## Özellikler

### Scanner (`scanner.py`)
- Tüm USDT-M Perpetual futures paritelerini tarar (587+ coin)
- 5 zaman diliminde (1w, 1d, 4h, 1h, 15m) OCC analizi
- EMA, RSI, ADX, MACD, Bollinger, Hacim kriterleri
- Sinyaller MongoDB'ye kaydedilir, Telegram'a gönderilir

### Order Worker (`order_worker.py`)
- MongoDB'deki PENDING sinyalleri işler
- Binance Futures LONG pozisyon açar (MARKET emri)
- Stop-Loss / Take-Profit takibi
- PM2 ile sürekli çalışır

### Dashboard (`http://localhost:5001`)

| Sekme | İçerik |
|-------|--------|
| **Genel Bakış** | Bakiye, kullanılabilir marjin, gerçekleşmemiş PnL, 7 günlük PnL sparkline, açık pozisyonlar, açık emirler, bot işlem geçmişi |
| **Piyasa** | 587 USDT-P coin, 3s güncellemeli anlık fiyat/değişim/hacim tablosu, arama, gainers/losers filtresi, sütun sıralaması |
| **Chart & Emir** | Candlestick grafik (lightweight-charts) + hacim overlay, order book (10 bid/ask), sembol ve interval seçici |
| **Sinyal Kartları** | OCC sinyal kartları (SL/TP, R:R, TF heatmap, RSI/ADX) |
| **Canlı Log** | Socket.io üzerinden gerçek zamanlı scanner log akışı |

---

## Kurulum

### Gereksinimler
- Python 3.9+
- Node.js 18+
- MongoDB (yerel)
- PM2 (`npm install -g pm2`)
- Binance hesabı + **Futures** API anahtarı (okuma + işlem izni)
- Telegram bot (opsiyonel)

### 1. Python bağımlılıkları

```bash
pip install -r requirements.txt
```

### 2. Ortam değişkenleri

```bash
cp .env.example .env
nano .env
```

```env
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
BINANCE_API_KEY=your_futures_api_key
BINANCE_API_SECRET=your_futures_api_secret
```

> **Not:** API anahtarının Binance Futures izinleri etkin olmalıdır.

### 3. Backend bağımlılıkları

```bash
cd dashboard_backend && npm install
```

### 4. Frontend build

```bash
cd dashboard_frontend && npm install && npm run build
```

### 5. PM2 ile başlat

```bash
pm2 start ecosystem.config.js
pm2 save
```

---

## PM2 Süreçleri

```
┌──────────────────────┬────────┬──────────┐
│ name                 │ mode   │ status   │
├──────────────────────┼────────┼──────────┤
│ trade-scanner        │ fork   │ online   │
│ jarvis-backend-api   │ fork   │ online   │
│ order-worker         │ fork   │ online   │
└──────────────────────┴────────┴──────────┘
```

```bash
pm2 list                        # Durum
pm2 logs trade-scanner          # Scanner logları
pm2 logs jarvis-backend-api     # API logları
pm2 restart all                 # Tümünü yeniden başlat
```

---

## Yapılandırma (`config.py`)

| Parametre | Açıklama | Varsayılan |
|-----------|----------|------------|
| `BINANCE_BASE_URL` | Futures API endpoint | `https://fapi.binance.com` |
| `ONLY_USDT` | Sadece USDT-M perpetual tara | `True` |
| `MIN_VOLUME_USDT` | Minimum 24s hacim | `1,000,000 USDT` |
| `SCAN_INTERVAL` | Tarama aralığı | `900s` |
| `KLINE_TIMEFRAMES` | Analiz zaman dilimleri | `1w, 1d, 4h, 1h, 15m` |
| `MIN_SCORE` | Minimum OCC puan eşiği | `5` |
| `ALERT_COOLDOWN_MINUTES` | Tekrar sinyal süresi | `30 dk` |

### Order Worker yapılandırması (`order_worker.py`)

```python
TRADE_CONFIG = {
    "enabled": True,                    # Canlı işlem modu
    "max_budget_per_trade_usdt": 50.0,  # İşlem başına bütçe
    "leverage": 5,                      # Kaldıraç
    "min_quantity": 0.001,
    "poll_interval": 30,                # Sinyal kontrol sıklığı (s)
    "track_interval": 60,               # Pozisyon takip sıklığı (s)
}
```

---

## API Endpoint'leri

```
GET /api/binance/balance          Hesap bakiyesi (USDT)
GET /api/binance/positions        Açık futures pozisyonlar
GET /api/binance/open-orders      Açık emirler
GET /api/binance/income           Son 7 günlük gerçekleşen PnL
GET /api/binance/all-tickers      Tüm USDT-P ticker'ları (587 coin)
GET /api/binance/klines           Mum verisi
GET /api/binance/orderbook        Order book (20 seviye)
GET /api/binance/ticker           Tek coin 24s ticker
GET /api/binance/trade-history    İşlem geçmişi

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
├── market_data.py            # Binance Futures API istemcisi
├── order_worker.py           # Otomatik emir motoru
├── analyzer.py               # Teknik analiz (EMA, RSI, ADX...)
├── config.py                 # Tüm yapılandırma sabitleri
├── telegram_notifier.py      # Telegram bildirim modülü
├── chart_gen.py              # Grafik oluşturucu
├── ecosystem.config.js       # PM2 çoklu süreç yapılandırması
├── requirements.txt
├── .env.example
│
├── dashboard_backend/
│   ├── server.js             # Express API + Socket.io
│   └── package.json
│
└── dashboard_frontend/
    ├── src/
    │   ├── App.jsx           # Ana dashboard bileşeni
    │   ├── main.jsx
    │   └── index.css
    ├── vite.config.js
    └── package.json
```

---

## Önemli Uyarılar

- Bu sistem **finansal tavsiye vermez**, teknik analiz sinyalleri üretir.
- Kaldıraçlı işlemler yüksek risk içerir. Tüm yatırım kararları **sizin sorumluluğunuzdadır**.
- `order_worker.py` içindeki `"enabled": True` ile **canlı emir açılır**. Test için `False` yapın.
- API anahtarınızı `.env` dışında **asla paylaşmayın**.
