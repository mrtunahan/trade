# ============================================================================
# config.py - Tarayıcı Yapılandırma Dosyası
# ============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ==================== TELEGRAM ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ==================== BinanceTR API ====================
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL   = "https://api.binance.me"

# ==================== TARAMA AYARLARI ====================
# Tarama aralığı (saniye)
SCAN_INTERVAL = 60  # Her 60 saniyede bir tara

# Mum zaman dilimi
KLINE_INTERVAL = "1h"  # 1m, 5m, 15m, 30m, 1h, 4h, 1d

# Kaç mum getirilsin (indikatör hesabı için yeterli olmalı)
KLINE_LIMIT = 250

# ==================== TAKİP EDİLECEK PARİTELER ====================
# "auto" = BinanceTR'deki tüm TRY ve USDT çiftlerini otomatik bul
# veya elle liste verin
PAIR_MODE = "auto"  # "auto" veya "manual"

# Manuel mod için listeler
MANUAL_TRY_PAIRS = [
    "BTCTRY", "ETHTRY", "BNBTRY", "XRPTRY", "SOLTRY",
    "AVXTRY", "DOGETRY", "ADATRY", "DOTTRY", "MATICTRY",
    "LINKTRY", "SHIBTRY", "LTCTRY", "USDTTRY",
]

MANUAL_USDT_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "AVAXUSDT", "DOGEUSDT", "ADAUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "SHIBUSDT", "LTCUSDT", "AAVEUSDT", "UNIUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FETUSDT",
]

# Minimum 24s işlem hacmi filtresi (USDT cinsinden)
MIN_VOLUME_USDT = 100_000  # 100K USD altı çiftleri atla

# ==================== SİNYAL KRİTERLERİ ====================
# Bu bölümü istediğiniz kriterlere göre güncelleyin.
# Her kriter açılıp kapatılabilir.

CRITERIA = {
    # --- EMA Crossover ---
    "ema_cross": {
        "enabled": True,
        "fast": 9,
        "slow": 21,
    },

    # --- RSI ---
    "rsi": {
        "enabled": True,
        "period": 14,
        "oversold": 30,       # Bu değerin altına düşünce sinyal
        "overbought": 70,     # Bu değerin üstüne çıkınca uyarı
    },

    # --- MACD ---
    "macd": {
        "enabled": True,
        "fast": 12,
        "slow": 26,
        "signal": 9,
    },

    # --- Bollinger Bands ---
    "bollinger": {
        "enabled": False,
        "period": 20,
        "std_dev": 2.0,
    },

    # --- Volume Spike ---
    "volume_spike": {
        "enabled": True,
        "ma_period": 20,
        "multiplier": 2.0,    # Ortalama hacmin kaç katı
    },

    # --- Trend Filtresi (200 EMA) ---
    "trend_filter": {
        "enabled": True,
        "ema_period": 200,
        "mode": "above",      # "above" = fiyat EMA üstünde, "below", "both"
    },

    # --- Destek/Direnç Yakınlığı ---
    "support_resistance": {
        "enabled": False,
        "lookback": 50,       # Kaç mum geriye bak
        "proximity_pct": 1.0, # Destek/dirence yakınlık %
    },

    # --- Stochastic RSI ---
    "stoch_rsi": {
        "enabled": False,
        "period": 14,
        "k_period": 3,
        "d_period": 3,
        "oversold": 20,
        "overbought": 80,
    },
}

# Kaç kriter aynı anda sağlanmalı (minimum)
MIN_CRITERIA_MET = 2

# ==================== BİLDİRİM AYARLARI ====================
# Aynı parite için tekrar bildirim gönderme süresi (dakika)
ALERT_COOLDOWN_MINUTES = 60

# Bildirimde grafik görseli gönder
SEND_CHART_IMAGE = True

# Günlük özet rapor saati (24 saat formatı)
DAILY_SUMMARY_HOUR = 21  # 21:00'de günlük özet

# ==================== LOGLAMA ====================
LOG_FILE  = "scanner.log"
LOG_LEVEL = "INFO"
