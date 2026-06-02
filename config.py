# ============================================================================
# config.py - New Spot Pipeline Configuration (4-Stage Trend/Reversal)
# ============================================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== TELEGRAM ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
SEND_CHART_IMAGE   = True
DAILY_SUMMARY_HOUR = 21

# ==================== Binance TR Spot API ====================
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL   = "https://www.binance.tr"

# ==================== TARAMA AYARLARI ====================
SCAN_INTERVAL  = 300      # 5 dakikada bir tara
KLINE_INTERVAL = "5m"     # Tetikleyici timeframe (5m)
KLINE_LIMIT    = 250

# ==================== PARİTE AYARLARI ====================
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "TRY").upper()
PAIR_MODE = "auto"  # "auto" veya "manual"
ONLY_USDT = QUOTE_ASSET == "USDT"

MANUAL_USDT_PAIRS = [
    f"BTC{QUOTE_ASSET}", f"ETH{QUOTE_ASSET}", f"BNB{QUOTE_ASSET}", f"SOL{QUOTE_ASSET}", f"XRP{QUOTE_ASSET}",
]

MIN_VOLUME_USDT = 0  # Hacim filtresi devre dışı

# ==================== SPOT PIPELINE HIZLI YAPILANDIRMASI ====================
SPOT_PIPELINE = {
    "enabled": True,
    # Relative Strength Puanlama Ağırlıkları
    "rs_weights": {
        "30d": 0.4,
        "7d": 0.3,
        "24h": 0.3
    },
    # Güçlü 30 segment (Trend Takipçiliği)
    "strong": {
        "score_threshold": 6,
        "rsi_min": 55,
        "rsi_max": 70,
        "vol_multiplier": 1.5,
        "base_sl_pct": 3.0,
        "base_tp_pct": 6.0
    },
    # Güçsüz 30 segment (Dipten Dönüş/Tepki)
    "weak": {
        "score_threshold": 5,
        "rsi_max": 45,        # Aşırı satım veya dipten yukarı dönüş sınırı
        "vol_multiplier": 2.0,
        "base_sl_pct": 2.5,
        "base_tp_pct": 5.0
    }
}

# Stablecoin ve yasaklı pariteler
STABLECOIN_BASES = {
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", 
    "USDP", "EUR", "GBP", "TRY", "USDE", "PYUSD", 
    "AEUR", "USTC", "PAXG", "USD"
}

STABLECOIN_BLACKLIST = {
    # USDT-based
    "USDCUSDT", "TUSDUSDT", "DAIUSDT", "BUSDUSDT",
    "USDPUSDT", "EURUSDT", "GBPUSDT", "FDUSDUSDT",
    "USDEUSDT", "USDSUSDT", "PYUSDUSDT", "AEURUSDT",
    # TRY-based
    "USDTTRY", "USDCTRY", "BUSDTRY", "FDUSDTRY", 
    "EURTRY", "GBPTRY", "USDTRY", "AEURTRY"
}

# ==================== LOGLAMA ====================
LOG_FILE  = "scanner.log"
LOG_LEVEL = "INFO"
