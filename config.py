# ============================================================================
# config.py - OCC Swing Trader Yapılandırma Dosyası
# ============================================================================
# Tek strateji: OCC-merkezli swing trading (TRY pariteleri, max 1 hafta)
# Manuel trade için sinyal üretici — bot otomatik işlem yapmaz.
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
SCAN_INTERVAL = 60  # Her 60 saniyede bir tara
KLINE_INTERVAL = "1h"  # Ana zaman dilimi
KLINE_LIMIT = 250

# ==================== SADECE TRY PARİTELERİ ====================
PAIR_MODE = "auto"  # "auto" veya "manual"
ONLY_TRY = True     # Sadece TRY paritelerini tara (USDT hariç)

MANUAL_TRY_PAIRS = [
    "BTCTRY", "ETHTRY", "BNBTRY", "XRPTRY", "SOLTRY",
    "AVXTRY", "DOGETRY", "ADATRY", "DOTTRY", "MATICTRY",
    "LINKTRY", "SHIBTRY", "LTCTRY", "USDTTRY",
]

# USDT pariteleri artık kullanılmıyor (sadece BTC filtresi için BTCUSDT çekilir)
MANUAL_USDT_PAIRS = []

# Minimum 24s işlem hacmi filtresi (USDT cinsinden)
MIN_VOLUME_USDT = 100_000

# ==================== MAKSİMUM POZİSYON SÜRESİ ====================
MAX_HOLD_BARS = 168  # 7 gün × 24 saat = 168 bar (1H timeframe)

# ==================== SİNYAL KRİTERLERİ ====================
# TEK STRATEJİ: OCC-merkezli swing trading
#
# Katman 1 — Tetikleyici (Zorunlu):
#   OCC Alert R6.2 = Alım sinyalinin tetikleyicisi. OCC olmadan sinyal yok.
#
# Katman 2 — Doğrulama (Puanlama):
#   Trend(2) + EMA(1) + RSI(1) + MACD(1) + Bollinger(1) + StochRSI(1) + Hacim(1)
#
# Katman 3 — Bonus (Opsiyonel):
#   BTC Trend(1) + 4H MTF(1) + Seans(1)
#
# OCC(2) + Doğrulama(8) + Bonus(3) = 13 puan
# Eşik: %60 = ~8/13 puan (OCC 2 puan zaten sabit)

CRITERIA = {
    # --- OCC (Open Close Cross) Non-Repaint --- ANA TETİKLEYİCİ
    # Close MA ve Open MA kesişimine dayalı sinyal.
    # JustUncleL'ın OCC Alert R6.2 indikatöründen esinlenilmiştir.
    # Non-repaint: Sadece kapanmış mumlara bakılır.
    # ZORUNLU: OCC tetiklenmeden sinyal üretilmez.
    "occ": {
        "enabled": True,
        "period": 5,
        "ma_type": "EMA",
        "min_strength": 0.01,
        "weight": 2,
        "required": True,  # ZORUNLU — OCC olmadan sinyal yok
    },

    # --- EMA Crossover ---
    "ema_cross": {
        "enabled": True,
        "fast": 9,
        "slow": 21,
        "weight": 1,
    },

    # --- RSI ---
    "rsi": {
        "enabled": True,
        "period": 14,
        "oversold": 30,
        "oversold_zone": 40,
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
        "multiplier": 1.5,
        "weight": 1,
    },

    # --- Trend Filtresi (200 EMA) ---
    "trend_filter": {
        "enabled": True,
        "ema_period": 200,
        "mode": "above",
        "weight": 2,
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

    # --- Destek/Direnç Yakınlığı ---
    "support_resistance": {
        "enabled": False,
        "lookback": 50,
        "proximity_pct": 1.0,
        "weight": 1,
    },

    # --- Market Rejimi (ADX Bazlı) ---
    "market_regime": {
        "enabled": True,
        "adx_period": 14,
        "trend_threshold": 25,
        "range_threshold": 20,
        "weight": 0,  # Puanlama yapmaz, SL/TP ve ağırlık dinamiğini yönetir
    },

    # --- Multi-Timeframe Doğrulama (4H) ---
    "multi_timeframe": {
        "enabled": True,
        "higher_tf": "4h",
        "weight": 1,
        "confidence_multiplier": 1.5,
    },

    # --- Zaman Filtresi (Seans Bazlı) ---
    "time_filter": {
        "enabled": True,
        "high_volume_hours_utc": [(13, 21)],
        "low_volume_penalty": False,
        "weight": 1,
    },

    # --- BTC Filtresi ---
    "btc_filter": {
        "enabled": True,
        "weight": 1,
    },

    # --- Confluence Window ---
    # OCC tetiklendikten sonra 3 mum içinde diğer doğrulama kriterlerini bekle
    "confluence_window": {
        "enabled": True,
        "window_candles": 3,
    },

    # --- Cooldown (Mum Bazlı) ---
    "candle_cooldown": {
        "enabled": True,
        "cooldown_candles": 5,
    },

    # --- Çıkış Stratejisi Puanlaması ---
    "exit_strategy": {
        "enabled": True,
        "occ_reverse_weight": 2,
        "rsi_overbought_weight": 1,
        "volume_drop_weight": 1,
        "stoch_overbought_weight": 1,
        "min_exit_score": 3,
    },
}

# ==================== AĞIRLIKLI PUANLAMA ====================
# OCC (2, zorunlu) + Trend(2) + EMA(1) + RSI(1) + MACD(1) + BB(1)
#   + StochRSI(1) + Hacim(1) + MTF(1) + BTC(1) + Seans(1) = 13
# Eşik: %60 = ~8/13 (OCC'nin 2 puanı dahil)
MIN_SIGNAL_STRENGTH_PCT = 0.60

# Geriye uyumluluk
MIN_CRITERIA_MET = 3

# ==================== DİNAMİK POZİSYON BOYUTLANDIRMA ====================
POSITION_SIZING = {
    "enabled": True,
    "tiers": [
        # (min_puan_yüzde, max_puan_yüzde, pozisyon_yüzde, etiket)
        (0.85, 1.00, 1.00, "Full Sniper"),
        (0.70, 0.85, 0.75, "Strong"),
        (0.60, 0.70, 0.50, "Normal"),
    ],
}

# ==================== DİNAMİK STOP-LOSS ====================
# Swing trading için ayarlanmış SL/TP (1 haftalık tutma süresi)
DYNAMIC_STOP_LOSS = {
    "enabled": True,
    "base_sl_pct": 3.0,           # Varsayılan stop-loss %3
    "base_tp_pct": 6.0,           # Varsayılan take-profit %6
    "strong_trend_adx": 40,
    "ranging_adx": 20,
    "trend_sl_pct": 4.0,          # Güçlü trend → SL %4 (geniş, trende alan ver)
    "trend_tp_pct": 10.0,         # Güçlü trend → TP %10 (1 haftada gerçekçi)
    "range_sl_pct": 2.0,          # Yatay piyasa → SL %2
    "range_tp_pct": 4.0,          # Yatay piyasa → TP %4
    # ATR Trailing Stop
    "trailing_stop": {
        "enabled": True,
        "atr_multiplier": 2.5,    # Swing trade için 2.5x ATR
        "activation_pct": 2.0,    # %2 kâra geçince trailing başlar
    },
}

# ==================== BİLDİRİM AYARLARI ====================
ALERT_COOLDOWN_MINUTES = 60
SEND_CHART_IMAGE = True
DAILY_SUMMARY_HOUR = 21

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
    _logger.info(f"Mod: Sadece TRY | Max tutma: {MAX_HOLD_BARS} bar ({MAX_HOLD_BARS//24} gün) | OCC zorunlu")

    if not TELEGRAM_BOT_TOKEN:
        _logger.warning("TELEGRAM_BOT_TOKEN ayarlanmamış!")
    if not TELEGRAM_CHAT_ID:
        _logger.warning("TELEGRAM_CHAT_ID ayarlanmamış!")


validate_config()
