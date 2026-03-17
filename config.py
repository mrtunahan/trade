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

    # --- Market Rejimi (ADX Bazlı) ---
    # ADX > 25 → Trend piyasa (trend kriterlerine daha fazla ağırlık)
    # ADX < 20 → Yatay piyasa (Bollinger/StochRSI'a daha fazla ağırlık)
    "market_regime": {
        "enabled": True,
        "adx_period": 14,
        "trend_threshold": 25,     # ADX > 25 → Güçlü trend
        "range_threshold": 20,     # ADX < 20 → Yatay piyasa
        "weight": 0,               # Kendi puanı yok, diğer ağırlıkları dinamik ayarlar
    },

    # --- Multi-Timeframe Doğrulama ---
    # Bir üst zaman diliminde trend yönü doğrulaması
    # Bonus puan olarak çalışır, yokluğu sinyal iptali yapmaz
    "multi_timeframe": {
        "enabled": True,
        "higher_tf": "4h",         # Üst zaman dilimi (1h → 4h, 15m → 1h)
        "weight": 1,               # Bonus puan (2'den 1'e düşürüldü)
    },

    # --- Zaman Filtresi (Seans Bazlı) ---
    # Yumuşak filtre: düşük hacimli saatlerde eşik yükseltme yerine
    # bonus puan olarak çalışır (seans içi = +1 puan)
    "time_filter": {
        "enabled": True,
        "high_volume_hours_utc": [(13, 21)],   # Avrupa+Amerika örtüşmesi (UTC)
        "low_volume_penalty": False,            # Sert eşik cezası KAPALI
        "weight": 1,                            # Yüksek hacim saati = +1 bonus puan
    },

    # --- BTC Filtresi ---
    # Yumuşak filtre: BTC yükselişte ise +1 bonus puan
    # BTC düşüşte ise puan vermez ama sinyal iptal etmez
    "btc_filter": {
        "enabled": True,
        "weight": 1,               # BTC yükselişte = +1 bonus puan
    },

    # --- Confluence Window (Sinyal Çakışma Penceresi) ---
    # OCC tetiklendikten sonra 3 mum içinde diğer kriterlerin tamamlanmasını bekle
    "confluence_window": {
        "enabled": True,
        "window_candles": 3,       # OCC'den sonra kaç mum içinde tamamlanmalı
    },

    # --- Cooldown (Mum Bazlı) ---
    # Sinyal sonrası belirli mum sayısı kadar yeni sinyal üretme
    "candle_cooldown": {
        "enabled": True,
        "cooldown_candles": 5,     # Sinyal sonrası 5 mum sessizlik
    },

    # --- Çıkış Stratejisi Puanlaması ---
    # Giriş gibi puanlama sistemiyle kademeli çıkış sinyali
    "exit_strategy": {
        "enabled": True,
        "occ_reverse_weight": 2,    # OCC ters kesişim
        "rsi_overbought_weight": 1, # RSI aşırı alım
        "volume_drop_weight": 1,    # Hacim düşüşü
        "stoch_overbought_weight": 1,  # StochRSI aşırı alım
        "min_exit_score": 3,        # Minimum çıkış puanı
    },
}

# ==================== AĞIRLIKLI PUANLAMA ====================
# Toplam ağırlık: OCC(2) + Trend(2) + EMA(1) + RSI(1) + MACD(1) + Bollinger(1)
#                + Hacim(1) + StochRSI(1) + MTF(1) + Zaman(1) + BTC(1) = 13
# %70 eşik = minimum ~9/13 puan gerekli
# Çekirdek kriterler (ADX+EMA+Hacim) + birkaç doğrulama yeterli.
# Backtest sonucu: %90 eşik pratikte sinyal üretmiyor, %70 sürdürülebilir.

# Minimum ağırlıklı puan yüzdesi (0.0 - 1.0)
# Sadece bu eşiğin üstündeki sinyaller Telegram'a gönderilir
MIN_SIGNAL_STRENGTH_PCT = 0.70  # %70 — ADX+EMA+Hacim bazlı, filtreler bonus

# Eski MIN_CRITERIA_MET artık ağırlıklı sistemde kullanılmıyor ama
# analyzer.py'de geriye uyumluluk için tutuluyor (3 olarak).
MIN_CRITERIA_MET = 3

# ==================== DİNAMİK POZİSYON BOYUTLANDIRMA ====================
# Sinyal gücüne göre pozisyon büyüklüğü belirlenir.
# Backtest sonucu: Adım 2 (%46.6 WR, PF 1.60) en iyi kârlılık.
# Güçlü sinyallere daha büyük, zayıf sinyallere daha küçük pozisyon.
POSITION_SIZING = {
    "enabled": True,
    "tiers": [
        # (min_puan_yüzde, max_puan_yüzde, pozisyon_yüzde, etiket)
        (0.85, 1.00, 1.00, "Full Sniper"),       # 11-13/13 puan → %100 pozisyon
        (0.70, 0.85, 0.60, "High Probability"),   # 9-11/13 puan → %60 pozisyon
    ],
    # %70 altı = sinyal yok (MIN_SIGNAL_STRENGTH_PCT tarafından filtrelenir)
}

# ==================== DİNAMİK STOP-LOSS ====================
# ADX bazlı adaptif stop-loss.
# Trend piyasada: geniş SL (trend devamı için alan ver)
# Yatay piyasada: dar SL (hızlı kes, kayıpları sınırla)
DYNAMIC_STOP_LOSS = {
    "enabled": True,
    "base_sl_pct": 2.0,           # Varsayılan stop-loss %2
    "base_tp_pct": 4.0,           # Varsayılan take-profit %4
    "strong_trend_adx": 40,       # ADX > 40 → güçlü trend
    "ranging_adx": 20,            # ADX < 20 → yatay piyasa
    "trend_sl_pct": 3.0,          # Güçlü trend → SL %3 (geniş, alan ver)
    "trend_tp_pct": 6.0,          # Güçlü trend → TP %6 (trendi kov)
    "range_sl_pct": 1.5,          # Yatay piyasa → SL %1.5 (dar, hızlı kes)
    "range_tp_pct": 3.0,          # Yatay piyasa → TP %3 (mütevazı hedef)
}

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
