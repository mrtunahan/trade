# ============================================================================
# config.py - Hiyerarşik Multi-TF OCC Scanner Yapılandırması
# ============================================================================
# Strateji: 5 timeframe'de OCC durumu kontrol edilir, ağırlıklı puanlama
# yapılır. 15dk OCC tetikleyici, üst TF'ler yön belirler.
#
# Haftalık(3p) + Günlük(2p) + 4H(2p) + 1H(1p) = 8p maks
# 15dk = tetikleyici (puan değil, giriş kapısı)
# Eşik: ≥5 puan + 15dk yeşil → ALIM sinyali
#
# Filtreler: RSI (giriş kalitesi), ADX (trend gücü)
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
SCAN_INTERVAL = 60       # Her 60 saniyede bir tara
KLINE_INTERVAL = "15m"   # Tetikleyici timeframe (15dk)
KLINE_LIMIT = 250

# ==================== PARİTE AYARLARI ====================
PAIR_MODE = "auto"  # "auto" veya "manual"
ONLY_TRY = False    # Tüm pariteleri tara (TRY + USDT)

MANUAL_TRY_PAIRS = [
    "BTCTRY", "ETHTRY", "BNBTRY", "XRPTRY", "SOLTRY",
    "AVXTRY", "DOGETRY", "ADATRY", "DOTTRY", "MATICTRY",
    "LINKTRY", "SHIBTRY", "LTCTRY", "BIOTRY", "USDTTRY",
]
MANUAL_USDT_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
]

# Minimum 24s işlem hacmi filtresi (USDT cinsinden)
MIN_VOLUME_USDT = 100_000

# ==================== HİYERARŞİK OCC PUANLAMA ====================
# Her timeframe'de OCC durumu (yeşil/kırmızı) kontrol edilir.
# Yeşil = Close MA > Open MA (yükseliş)
# Kırmızı = Close MA < Open MA (düşüş)
#
# Üst TF her zaman alt TF'yi yönetir:
#   Haftalık → yön belirler
#   Günlük  → giriş penceresi açar
#   4H      → zamanlama
#   1H      → zamanlama
#   15dk    → tetikleyici (yeşil yakınca giriş)

OCC_TIMEFRAMES = {
    # timeframe: (ağırlık, kline_limit, açıklama)
    "1w":  (3, 52,  "Haftalık"),    # 3 puan — yön belirler
    "1d":  (2, 100, "Günlük"),      # 2 puan — giriş penceresi
    "4h":  (2, 200, "4 Saatlik"),   # 2 puan — zamanlama
    "1h":  (1, 250, "1 Saatlik"),   # 1 puan — zamanlama
    "15m": (0, 250, "15 Dakika"),   # 0 puan — sadece tetikleyici
}

# Toplam maks puan: 3+2+2+1 = 8
# Minimum eşik: 5 puan (üst TF'lerin çoğunluğu yeşil olmalı)
OCC_MIN_SCORE = 5

# OCC hesaplama parametreleri (tüm TF'ler için aynı)
OCC_PERIOD = 5
OCC_MA_TYPE = "EMA"
OCC_MIN_STRENGTH = 0.01  # Minimum cross strength

# ==================== RSI FİLTRESİ ====================
# RSI giriş kalitesini artırmak için kullanılır.
# OCC yeşil yaktığında RSI 30-50 arası → iyi giriş (momentum başlıyor)
# RSI 70+ → dikkat (hareket zaten olmuş)
RSI_CONFIG = {
    "enabled": True,
    "period": 14,
    "ideal_entry_min": 30,     # RSI bu aralıktaysa giriş kalitesi yüksek
    "ideal_entry_max": 50,
    "caution_level": 70,       # RSI bunun üstündeyse dikkat uyarısı
    "block_level": 80,         # RSI bunun üstündeyse sinyal engelle
}

# ==================== ADX FİLTRESİ ====================
# Trend gücünü ölçer, OCC sinyallerini filtreler.
# ADX > 25 → trend var, OCC sinyali daha güvenilir
# ADX < 20 → yatay piyasa, sahte sinyal riski yüksek
ADX_CONFIG = {
    "enabled": True,
    "period": 14,
    "strong_trend": 25,    # ADX bunun üstünde → trend güçlü
    "weak_market": 15,     # ADX bunun altında → uyarı (isteğe bağlı blok)
    "block_below": 0,      # 0 = engelleme yok, >0 ise bu ADX altında sinyal engelle
}

# ==================== DİNAMİK STOP-LOSS ====================
DYNAMIC_STOP_LOSS = {
    "enabled": True,
    "base_sl_pct": 3.0,
    "base_tp_pct": 6.0,
    "strong_trend_adx": 40,
    "ranging_adx": 20,
    "trend_sl_pct": 4.0,
    "trend_tp_pct": 10.0,
    "range_sl_pct": 2.0,
    "range_tp_pct": 4.0,
    "trailing_stop": {
        "enabled": True,
        "atr_multiplier": 2.5,
        "activation_pct": 2.0,
    },
}

# ==================== BİLDİRİM AYARLARI ====================
# Her OCC renk değişiminde bildirim gönderilir
ALERT_COOLDOWN_MINUTES = 30   # Aynı sembol+TF için cooldown
SEND_CHART_IMAGE = True
DAILY_SUMMARY_HOUR = 21
NOTIFY_ALL_TF_CHANGES = True  # Her TF'deki renk değişimini bildir

# ==================== LOGLAMA ====================
LOG_FILE  = "scanner.log"
LOG_LEVEL = "INFO"

# ==================== ESKİ SİSTEM UYUMLULUĞU ====================
# analyzer.py'nin ihtiyaç duyduğu eski değişkenler
MAX_HOLD_BARS = 168
MIN_SIGNAL_STRENGTH_PCT = 0.60
MIN_CRITERIA_MET = 3
POSITION_SIZING = {"enabled": False, "tiers": []}
CRITERIA = {
    "occ": {"enabled": True, "period": OCC_PERIOD, "ma_type": OCC_MA_TYPE,
            "min_strength": OCC_MIN_STRENGTH, "weight": 2, "required": False},
    "market_regime": {"enabled": True, "adx_period": ADX_CONFIG["period"],
                      "trend_threshold": ADX_CONFIG["strong_trend"],
                      "range_threshold": ADX_CONFIG["weak_market"], "weight": 0},
    "exit_strategy": {"enabled": True, "occ_reverse_weight": 2,
                      "rsi_overbought_weight": 1, "volume_drop_weight": 1,
                      "stoch_overbought_weight": 1, "min_exit_score": 3},
    "ema_cross": {"enabled": False},
    "rsi": {"enabled": False},
    "macd": {"enabled": False},
    "bollinger": {"enabled": False},
    "volume_spike": {"enabled": False},
    "trend_filter": {"enabled": False},
    "stoch_rsi": {"enabled": False},
    "support_resistance": {"enabled": False},
    "multi_timeframe": {"enabled": False},
    "time_filter": {"enabled": False},
    "btc_filter": {"enabled": False},
    "confluence_window": {"enabled": False},
    "candle_cooldown": {"enabled": False},
}

# ==================== DOĞRULAMA ====================
def validate_config():
    import logging as _log
    _logger = _log.getLogger("Config")

    total_weight = sum(w for tf, (w, _, _) in OCC_TIMEFRAMES.items() if tf != "15m")
    _logger.info(f"Hiyerarşik OCC: {len(OCC_TIMEFRAMES)} TF, "
                 f"Maks puan: {total_weight}, Eşik: {OCC_MIN_SCORE}")
    _logger.info(f"RSI filtre: {'Aktif' if RSI_CONFIG['enabled'] else 'Kapalı'}, "
                 f"ADX filtre: {'Aktif' if ADX_CONFIG['enabled'] else 'Kapalı'}")
    _logger.info(f"Pariteler: {'Sadece TRY' if ONLY_TRY else 'TRY + USDT'}")

    if not TELEGRAM_BOT_TOKEN:
        _logger.warning("TELEGRAM_BOT_TOKEN ayarlanmamış!")
    if not TELEGRAM_CHAT_ID:
        _logger.warning("TELEGRAM_CHAT_ID ayarlanmamış!")


validate_config()
