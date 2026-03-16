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
        "weight": 1,              # Ağırlık puanı
    },

    # --- RSI ---
    "rsi": {
        "enabled": True,
        "period": 14,
        "oversold": 30,           # Aşırı satım (güçlü sinyal)
        "oversold_zone": 40,      # Potansiyel alım bölgesi (30-40 arası)
        "overbought": 70,
        "weight": 1,
    },

    # --- MACD ---
    "macd": {
        "enabled": True,
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "weight": 1,
    },

    # --- Bollinger Bands ---
    "bollinger": {
        "enabled": True,
        "period": 20,
        "std_dev": 2.0,
        "weight": 1,
    },

    # --- Volume Spike ---
    "volume_spike": {
        "enabled": True,
        "ma_period": 20,
        "multiplier": 1.5,        # 2.0'dan 1.5'e düşürüldü (daha hassas)
        "weight": 1,
    },

    # --- Trend Filtresi (200 EMA) ---
    "trend_filter": {
        "enabled": True,
        "ema_period": 200,
        "mode": "above",
        "weight": 2,              # Trend yönü çok önemli → 2 puan
    },

    # --- Destek/Direnç Yakınlığı ---
    "support_resistance": {
        "enabled": False,
        "lookback": 50,
        "proximity_pct": 1.0,
        "weight": 1,
    },

    # --- Stochastic RSI ---
    "stoch_rsi": {
        "enabled": True,
        "period": 14,
        "k_period": 3,
        "d_period": 3,
        "oversold": 20,
        "overbought": 80,
        "weight": 1,
    },

    # --- OCC (Open Close Cross) Non-Repaint ---
    # Close MA ve Open MA kesişimine dayalı sinyal.
    # JustUncleL'ın OCC Alert R6.2 indikatöründen esinlenilmiştir.
    # Non-repaint: Sadece kapanmış mumlara bakılır.
    # ZORUNLU KRİTER: OCC sağlanmadan sinyal üretilmez.
    "occ": {
        "enabled": True,
        "period": 5,
        "ma_type": "EMA",
        "min_strength": 0.01,
        "weight": 2,              # Ana sinyal üreticisi → 2 puan
        "required": True,         # ZORUNLU: OCC olmadan sinyal üretilmez
    },
}

# ==================== AĞIRLIKLI PUANLAMA ====================
# Toplam ağırlık: OCC(2) + Trend(2) + EMA(1) + RSI(1) + MACD(1) + Bollinger(1) + Hacim(1) + StochRSI(1) = 10
# %90 eşik = minimum 9 puan gerekli
# Bu, neredeyse tüm kriterlerin sağlanmasını gerektirir.

# Minimum ağırlıklı puan yüzdesi (0.0 - 1.0)
# Sadece bu eşiğin üstündeki sinyaller Telegram'a gönderilir
MIN_SIGNAL_STRENGTH_PCT = 0.90  # %90 — sadece çok güçlü sinyaller

# Eski MIN_CRITERIA_MET artık ağırlıklı sistemde kullanılmıyor ama
# analyzer.py'de geriye uyumluluk için tutuluyor (3 olarak).
MIN_CRITERIA_MET = 3

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
    total_weight = sum(c.get("weight", 1) for c in CRITERIA.values() if c.get("enabled", False))
    required_count = sum(1 for c in CRITERIA.values() if c.get("enabled", False) and c.get("required", False))

    if enabled_count == 0:
        _logger.warning("Hiçbir kriter aktif değil! Sinyal üretilemez.")

    _logger.info(f"Aktif kriterler: {enabled_count}, Toplam ağırlık: {total_weight}, "
                 f"Zorunlu kriterler: {required_count}, Min sinyal gücü: %{MIN_SIGNAL_STRENGTH_PCT*100:.0f}")

    if not TELEGRAM_BOT_TOKEN:
        _logger.warning("TELEGRAM_BOT_TOKEN ayarlanmamış!")
    if not TELEGRAM_CHAT_ID:
        _logger.warning("TELEGRAM_CHAT_ID ayarlanmamış!")


validate_config()
