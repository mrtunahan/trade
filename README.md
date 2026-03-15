# BinanceTR Piyasa Tarayıcı + Telegram Bildirici

BinanceTR üzerindeki tüm **TRY** ve **USDT** paritelerini otomatik tarayan, belirlediğiniz kriterlere uyan alım noktalarını **Telegram** üzerinden bildiren bot.

---

## Nasıl Çalışır?

```
BinanceTR API → Tüm TRY + USDT pariteleri taranır
    → Teknik analiz (EMA, RSI, MACD, Hacim, vs.)
    → Kriterler sağlandı mı?
        → Evet: Telegram bildirimi + mini grafik
        → Hayır: Sonraki parite
    → Döngü tekrarla (varsayılan: 60 sn)
```

---

## Kurulum

### 1. Gereksinimler
- Python 3.9+
- BinanceTR hesabı + API anahtarı (sadece okuma yetkisi yeterli)
- Telegram hesabı + bot

### 2. Telegram Bot Oluşturma

**Bot Token:**
1. Telegram'da [@BotFather](https://t.me/BotFather) ile konuşun
2. `/newbot` yazın ve adımları takip edin
3. Size verilen token'ı kaydedin

**Chat ID:**
1. Telegram'da [@userinfobot](https://t.me/userinfobot) ile konuşun
2. `/start` yazın
3. Size verilen ID numarasını kaydedin

**Grup için kullanmak isterseniz:**
1. Botu gruba ekleyin
2. Grupta bir mesaj gönderin
3. `https://api.telegram.org/bot<TOKEN>/getUpdates` adresinden chat ID'yi bulun (negatif sayı olur)

### 3. Kurulum

```bash
git clone <repo> trading-bot
cd trading-bot
pip install -r requirements.txt
cp .env.example .env
nano .env   # Token ve anahtarları girin
```

### 4. Test

```bash
# Telegram bağlantı testi
python scanner.py --test

# Tek seferlik tarama (Telegram'a da gönderir)
python scanner.py --once

# Sürekli tarama başlat
python scanner.py
```

---

## Kriter Ayarlama

`config.py` dosyasındaki `CRITERIA` sözlüğünü düzenleyerek hangi teknik indikatörlerin kullanılacağını belirleyin:

```python
CRITERIA = {
    "ema_cross": {
        "enabled": True,       # Aç / kapat
        "fast": 9,             # Hızlı EMA periyodu
        "slow": 21,            # Yavaş EMA periyodu
    },
    "rsi": {
        "enabled": True,
        "period": 14,
        "oversold": 30,        # Aşırı satım eşiği
        "overbought": 70,
    },
    "macd": {
        "enabled": True,
        "fast": 12,
        "slow": 26,
        "signal": 9,
    },
    # ... diğer kriterler
}

# Kaç kriter aynı anda sağlanmalı
MIN_CRITERIA_MET = 2
```

### Mevcut Kriterler

| Kriter | Açıklama | Varsayılan |
|--------|----------|-----------|
| `ema_cross` | EMA kesişim (hızlı yavaşı yukarı kesiyor) | Açık |
| `rsi` | RSI aşırı satım bölgesinde | Açık |
| `macd` | MACD sinyal kesişimi veya histogram dönüşü | Açık |
| `bollinger` | Fiyat alt Bollinger bandına temas | Kapalı |
| `volume_spike` | Hacim ortalamanın X katına çıkmış | Açık |
| `trend_filter` | Fiyat 200 EMA'nın üstünde | Açık |
| `support_resistance` | Destek seviyesine yakınlık | Kapalı |
| `stoch_rsi` | Stochastic RSI aşırı satımda kesişim | Kapalı |

### Örnek Stratejiler

**Agresif (daha çok sinyal):**
```python
MIN_CRITERIA_MET = 2
# EMA cross + Volume spike yeterli
```

**Konservatif (daha az ama güçlü sinyal):**
```python
MIN_CRITERIA_MET = 4
# EMA + RSI + MACD + Trend hepsi sağlanmalı
```

---

## Bildirim Formatı

Telegram'a gelen örnek bildirim:

```
🔥🔥 ALIM SİNYALİ - BTC/TRY
━━━━━━━━━━━━━━━━━━━━━

💰 Fiyat: 2,150,000.0000 TRY
📊 Güç: Güçlü (3/5)
📉 RSI: 28.4
📈 24s Değişim: +2.35%

Kriterler:
  ✅ EMA Kesişim: EMA yukarı kesişim
  ✅ RSI: RSI Aşırı satım
  ✅ Hacim Artışı: Hacim patlaması (2.4x)
  ❌ MACD: Sinyal yok
  ❌ Trend Filtresi: Trend düşüş

━━━━━━━━━━━━━━━━━━━━━
🕐 2026-03-15 14:30:00
🔗 TradingView
```

+ Mini grafik görseli (fiyat + EMA + RSI + hacim)

---

## Yapılandırma Referansı

| Ayar | Açıklama | Varsayılan |
|------|----------|-----------|
| `SCAN_INTERVAL` | Tarama aralığı (saniye) | 60 |
| `KLINE_INTERVAL` | Mum zaman dilimi | 1h |
| `PAIR_MODE` | "auto" veya "manual" | auto |
| `MIN_VOLUME_USDT` | Minimum 24s hacim (USDT) | 100,000 |
| `ALERT_COOLDOWN_MINUTES` | Tekrar bildirim süresi | 60 |
| `SEND_CHART_IMAGE` | Grafik görseli gönder | True |
| `DAILY_SUMMARY_HOUR` | Günlük özet saati | 21 |
| `MIN_CRITERIA_MET` | Minimum kriter sayısı | 2 |

---

## Dosya Yapısı

```
trading-bot/
├── scanner.py             # Ana tarayıcı (çalıştırılan dosya)
├── market_data.py         # BinanceTR veri çekici
├── analyzer.py            # Teknik analiz motoru
├── telegram_notifier.py   # Telegram bildirim modülü
├── chart_gen.py           # Mini grafik oluşturucu
├── config.py              # Tüm ayarlar
├── requirements.txt       # Python bağımlılıkları
├── .env.example           # Gizli anahtar şablonu
└── README.md              # Bu dosya
```

---

## Arka Planda Çalıştırma

```bash
# systemd servisi olarak (önerilen)
sudo nano /etc/systemd/system/scanner-bot.service
```

```ini
[Unit]
Description=BinanceTR Scanner Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/trading-bot
ExecStart=/usr/bin/python3 scanner.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable scanner-bot
sudo systemctl start scanner-bot
sudo journalctl -u scanner-bot -f   # Logları takip et
```

---

## Önemli Uyarılar

- Bu bot **finansal tavsiye vermez**, sadece teknik analiz sinyallerini bildirir.
- Tüm yatırım kararları **sizin sorumluluğunuzdadır**.
- API anahtarınıza **sadece okuma yetkisi** verin, işlem yetkisi vermeyin.
- Bot sinyalleri **garanti değildir**, her zaman kendi araştırmanızı yapın.
