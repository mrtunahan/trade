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

    # --- OCC (Open Close Cross) Non-Repaint ---
    # Close MA ve Open MA kesişimine dayalı sinyal.
    # JustUncleL'ın OCC Alert R6.2 indikatöründen esinlenilmiştir.
    # Non-repaint: Sadece kapanmış mumlara bakılır.
    "occ": {
        "enabled": True,
        "period": 5,              # MA periyodu
        "ma_type": "EMA",         # "SMA", "EMA", "DEMA", "TEMA", "WMA", "HMA"
        "min_strength": 0.01,     # Minimum cross strength % (zayıf sinyalleri filtrele)
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

# ==================== DOĞRULAMA ====================
def validate_config():
    """Başlangıçta konfigürasyon tutarlılığını kontrol eder."""
    import logging as _log
    _logger = _log.getLogger("Config")

    enabled_count = sum(1 for c in CRITERIA.values() if c.get("enabled", False))
    if enabled_count == 0:
        _logger.warning("Hiçbir kriter aktif değil! Sinyal üretilemez.")
    elif MIN_CRITERIA_MET > enabled_count:
        _logger.warning(
            f"MIN_CRITERIA_MET ({MIN_CRITERIA_MET}) aktif kriter sayısından ({enabled_count}) büyük! "
            f"Sinyal üretilemez. MIN_CRITERIA_MET değerini düşürün veya daha fazla kriter aktif edin."
        )

    if not TELEGRAM_BOT_TOKEN:
        _logger.warning("TELEGRAM_BOT_TOKEN ayarlanmamış!")
    if not TELEGRAM_CHAT_ID:
        _logger.warning("TELEGRAM_CHAT_ID ayarlanmamış!")


validate_config()
