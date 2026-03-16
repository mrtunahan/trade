# ============================================================================
# scanner.py - Ana Tarayıcı (Geliştirilmiş v2)
# ============================================================================
# Tüm TRY ve USDT paritelerini periyodik olarak tarar,
# kriterlere uyan sinyalleri Telegram'a bildirir.
#
# v2: Multi-timeframe doğrulama, BTC filtresi, çıkış sinyalleri,
#     gelişmiş market rejimi algılama
#
# Kullanım:
#   python scanner.py
#   python scanner.py --once       (tek sefer tara)
#   python scanner.py --test       (Telegram bağlantı testi)
# ============================================================================

import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from config import (
    SCAN_INTERVAL,
    KLINE_INTERVAL,
    ALERT_COOLDOWN_MINUTES,
    DAILY_SUMMARY_HOUR,
    LOG_FILE, LOG_LEVEL,
    SEND_CHART_IMAGE,
    MIN_SIGNAL_STRENGTH_PCT,
    CRITERIA,
)
from market_data import MarketData
from analyzer import TechnicalAnalyzer
from telegram_notifier import TelegramNotifier
from chart_gen import generate_signal_chart

# ==================== LOGLAMA ====================
def setup_logging():
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL))

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    root.addHandler(ch)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

setup_logging()
logger = logging.getLogger("Scanner")


# Üst zaman dilimi eşlemeleri
HIGHER_TF_MAP = {
    "1m": "5m",
    "5m": "15m",
    "15m": "1h",
    "30m": "4h",
    "1h": "4h",
    "4h": "1d",
    "1d": "1w",
}


class Scanner:
    """Ana tarayıcı sınıfı."""

    def __init__(self):
        self.market = MarketData()
        self.analyzer = TechnicalAnalyzer()
        self.telegram = TelegramNotifier()

        # Cooldown takibi: {symbol: last_alert_time}
        self.alert_cooldowns = {}

        # Günlük sinyal kaydı
        self.daily_signals = []
        self.last_summary_date = None

        # Parite listesi (periyodik yenilenir)
        self.pairs = []
        self.last_pair_refresh = 0

        # BTC verisi cache
        self._btc_df_cache = None
        self._btc_cache_ts = 0

        # Üst TF cache: {symbol: (df, timestamp)}
        self._htf_cache = {}

        # Aktif pozisyonlar (çıkış sinyali takibi)
        self.active_positions = {}  # {symbol: Signal}

        # Graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Kapatılıyor...")
        self.running = False

    # ==================== PARİTE YÖNETİMİ ====================

    def refresh_pairs(self, force: bool = False) -> list:
        """Parite listesini günceller (her 30 dakikada bir)."""
        now = time.time()
        if not force and (now - self.last_pair_refresh) < 1800 and self.pairs:
            return self.pairs

        logger.info("Parite listesi güncelleniyor...")
        all_pairs = self.market.get_all_pairs()
        combined = all_pairs["TRY"] + all_pairs["USDT"]

        # Hacim filtresi
        self.pairs = self.market.filter_by_volume(combined)
        self.last_pair_refresh = now

        logger.info(f"Aktif parite sayısı: {len(self.pairs)} "
                    f"(TRY: {sum(1 for p in self.pairs if p.endswith('TRY'))}, "
                    f"USDT: {sum(1 for p in self.pairs if p.endswith('USDT'))})")

        return self.pairs

    # ==================== COOLDOWN ====================

    def _is_on_cooldown(self, symbol: str) -> bool:
        """Sembol için bildirim cooldown kontrolü."""
        last_alert = self.alert_cooldowns.get(symbol)
        if not last_alert:
            return False
        elapsed = (datetime.now() - last_alert).total_seconds() / 60
        return elapsed < ALERT_COOLDOWN_MINUTES

    def _set_cooldown(self, symbol: str):
        self.alert_cooldowns[symbol] = datetime.now()

    def _cleanup_cooldowns(self):
        """Süresi dolmuş cooldown kayıtlarını temizler."""
        now = datetime.now()
        expired = [sym for sym, t in self.alert_cooldowns.items()
                   if (now - t).total_seconds() / 60 >= ALERT_COOLDOWN_MINUTES]
        for sym in expired:
            del self.alert_cooldowns[sym]

    # ==================== BTC VERİSİ ====================

    def _get_btc_data(self) -> "pd.DataFrame | None":
        """BTC mum verisini çeker (cache'li, 5 dk)."""
        now = time.time()
        if self._btc_df_cache is not None and (now - self._btc_cache_ts) < 300:
            return self._btc_df_cache

        # BTC verisini çek - önce USDT, yoksa TRY
        btc_df = self.market.get_klines("BTCUSDT")
        if btc_df is None or len(btc_df) < 50:
            btc_df = self.market.get_klines("BTCTRY")

        if btc_df is not None and len(btc_df) >= 50:
            self._btc_df_cache = btc_df
            self._btc_cache_ts = now

        return self._btc_df_cache

    def _get_htf_data(self, symbol: str) -> "pd.DataFrame | None":
        """Üst zaman dilimi verisini çeker (cache'li, 10 dk)."""
        now = time.time()
        cached = self._htf_cache.get(symbol)
        if cached and (now - cached[1]) < 600:
            return cached[0]

        mtf_cfg = CRITERIA.get("multi_timeframe", {})
        if not mtf_cfg.get("enabled", False):
            return None

        higher_tf = mtf_cfg.get("higher_tf") or HIGHER_TF_MAP.get(KLINE_INTERVAL, "4h")
        htf_df = self.market.get_klines(symbol, interval=higher_tf)

        if htf_df is not None and len(htf_df) >= 50:
            self._htf_cache[symbol] = (htf_df, now)
            return htf_df

        return None

    # ==================== TARAMA DÖNGÜSÜ ====================

    def scan_once(self) -> list:
        """Tüm pariteleri bir kez tarar. Bulunan sinyalleri döndürür."""
        pairs = self.refresh_pairs()
        signals_found = []
        scanned = 0
        errors = 0

        logger.info(f"Tarama başlıyor: {len(pairs)} parite...")

        # BTC verisini önceden çek (tüm altcoin filtrelemesi için)
        btc_df = None
        btc_cfg = CRITERIA.get("btc_filter", {})
        if btc_cfg.get("enabled", False):
            btc_df = self._get_btc_data()

        for i, symbol in enumerate(pairs):
            if not self.running:
                break

            try:
                # Mum verisi çek
                df = self.market.get_klines(symbol)
                if df is None or len(df) < 50:
                    continue

                scanned += 1

                # Üst zaman dilimi verisi (multi-timeframe doğrulama)
                htf_df = None
                mtf_cfg = CRITERIA.get("multi_timeframe", {})
                if mtf_cfg.get("enabled", False):
                    htf_df = self._get_htf_data(symbol)

                # Analiz et (geliştirilmiş v2)
                sig = self.analyzer.analyze(
                    symbol, df,
                    htf_df=htf_df,
                    btc_df=btc_df,
                )

                # Çıkış sinyali kontrolü (aktif pozisyonlar için)
                exit_cfg = CRITERIA.get("exit_strategy", {})
                if exit_cfg.get("enabled", False) and symbol in self.active_positions:
                    exit_sig = self.analyzer.check_exit_signal(symbol, df)
                    if exit_sig:
                        self._handle_exit_signal(exit_sig)

                if sig:
                    # Güç eşiği kontrolü — sadece %90+ sinyal gönder
                    if sig.strength_pct < MIN_SIGNAL_STRENGTH_PCT:
                        logger.debug(
                            f"{symbol}: Sinyal var ama güç yetersiz "
                            f"(%{sig.strength_pct*100:.0f} < %{MIN_SIGNAL_STRENGTH_PCT*100:.0f})"
                        )
                        continue

                    # Cooldown kontrolü
                    if self._is_on_cooldown(symbol):
                        logger.debug(f"{symbol}: Sinyal var ama cooldown'da")
                        continue

                    regime_info = f" | Rejim: {sig.market_regime}" if sig.market_regime != "unknown" else ""
                    logger.info(
                        f"🔔 SİNYAL: {symbol} | Güç: {sig.strength}/{sig.total_criteria} "
                        f"(%{sig.strength_pct*100:.0f}) | "
                        f"Fiyat: {sig.price:,.4f} | Kriterler: {', '.join(sig.criteria_met)}"
                        f"{regime_info}"
                    )

                    # Grafik oluştur
                    chart_bytes = None
                    if SEND_CHART_IMAGE:
                        chart_bytes = generate_signal_chart(symbol, df, sig.indicators)

                    # Telegram'a gönder
                    success = self.telegram.send_signal(sig, chart_bytes=chart_bytes if chart_bytes else None)

                    if success:
                        self._set_cooldown(symbol)
                        signals_found.append(sig)
                        self.daily_signals.append(sig)
                        # Aktif pozisyon olarak kaydet (çıkış takibi için)
                        self.active_positions[symbol] = sig
                        logger.info(f"✅ Telegram bildirim gönderildi: {symbol}")
                    else:
                        logger.error(f"❌ Telegram bildirim başarısız: {symbol}")

                # Rate limit koruma
                if (i + 1) % 10 == 0:
                    time.sleep(1)

            except Exception as e:
                errors += 1
                logger.error(f"{symbol} tarama hatası: {e}")
                if errors > 10:
                    logger.error("Çok fazla hata, tarama durduruluyor")
                    break

        logger.info(f"Tarama tamamlandı: {scanned} tarandı, {len(signals_found)} sinyal bulundu")
        return signals_found

    def _handle_exit_signal(self, exit_sig):
        """Çıkış sinyalini işler ve Telegram'a gönderir."""
        symbol = exit_sig.symbol
        logger.info(
            f"🔔 ÇIKIŞ SİNYALİ: {symbol} | Puan: {exit_sig.exit_score}/5 | "
            f"Fiyat: {exit_sig.price:,.4f}"
        )

        success = self.telegram.send_exit_signal(exit_sig)
        if success:
            # Pozisyonu kapat
            del self.active_positions[symbol]
            logger.info(f"✅ Çıkış bildirimi gönderildi: {symbol}")

    def check_daily_summary(self):
        """Günlük özet zamanı geldiyse gönderir."""
        now = datetime.now()
        today = now.date()

        if self.last_summary_date == today:
            return

        if now.hour == DAILY_SUMMARY_HOUR:
            logger.info("Günlük özet gönderiliyor...")
            self.telegram.send_daily_summary(self.daily_signals, len(self.pairs))
            self.last_summary_date = today
            self.daily_signals = []  # Sıfırla

        # Güvenlik: günlük sinyal listesini sınırla (bellek koruması)
        if len(self.daily_signals) > 500:
            logger.warning(f"Günlük sinyal listesi çok büyüdü ({len(self.daily_signals)}), kırpılıyor")
            self.daily_signals = self.daily_signals[-500:]

    # ==================== ANA DÖNGÜ ====================

    def run(self):
        """Sürekli tarama döngüsü."""
        logger.info("=" * 60)
        logger.info("🤖 BinanceTR Scanner Bot v2.0 başlatılıyor...")
        logger.info(f"   Tarama aralığı: {SCAN_INTERVAL}s")
        logger.info(f"   Zaman dilimi: {KLINE_INTERVAL}")
        logger.info(f"   Cooldown: {ALERT_COOLDOWN_MINUTES}dk")
        logger.info(f"   Min sinyal gücü: %{MIN_SIGNAL_STRENGTH_PCT*100:.0f}")

        # Aktif modüller
        active_modules = []
        if CRITERIA.get("market_regime", {}).get("enabled"):
            active_modules.append("ADX Rejim")
        if CRITERIA.get("multi_timeframe", {}).get("enabled"):
            htf = CRITERIA["multi_timeframe"].get("higher_tf", "4h")
            active_modules.append(f"Multi-TF ({htf})")
        if CRITERIA.get("time_filter", {}).get("enabled"):
            active_modules.append("Seans Filtresi")
        if CRITERIA.get("btc_filter", {}).get("enabled"):
            active_modules.append("BTC Filtresi")
        if CRITERIA.get("confluence_window", {}).get("enabled"):
            active_modules.append("Confluence Window")
        if CRITERIA.get("candle_cooldown", {}).get("enabled"):
            cd = CRITERIA["candle_cooldown"].get("cooldown_candles", 5)
            active_modules.append(f"Mum Cooldown ({cd})")
        if CRITERIA.get("exit_strategy", {}).get("enabled"):
            active_modules.append("Çıkış Stratejisi")

        if active_modules:
            logger.info(f"   Gelişmiş modüller: {', '.join(active_modules)}")
        logger.info("=" * 60)

        # Bağlantı testleri
        if not self.telegram.test_connection():
            logger.error("❌ Telegram bağlantısı başarısız! Bot durduruluyor.")
            logger.error("   TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID'yi kontrol edin.")
            return

        # Pariteleri yükle
        self.refresh_pairs(force=True)

        if not self.pairs:
            logger.error("❌ Hiç parite bulunamadı! Ayarları kontrol edin.")
            return

        # Başlangıç bildirimi
        self.telegram.send_startup(len(self.pairs), active_modules)

        # Ana döngü
        cycle = 0
        while self.running:
            cycle += 1
            logger.info(f"\n{'─' * 40} Döngü #{cycle} {'─' * 40}")

            try:
                self.scan_once()
                self.check_daily_summary()
                self._cleanup_cooldowns()
            except Exception as e:
                logger.error(f"Döngü hatası: {e}", exc_info=True)
                self.telegram.send_error(f"Tarama hatası: {str(e)[:200]}")

            # Bir sonraki taramaya kadar bekle
            if self.running:
                logger.info(f"Sonraki tarama: {SCAN_INTERVAL}s sonra...")
                for _ in range(SCAN_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)

        logger.info("Bot durduruldu.")

    def run_once(self):
        """Tek seferlik tarama (test için)."""
        logger.info("Tek seferlik tarama başlatılıyor...")

        self.refresh_pairs(force=True)
        if not self.pairs:
            logger.error("Hiç parite bulunamadı!")
            return

        logger.info(f"Toplam {len(self.pairs)} parite taranacak")
        signals = self.scan_once()

        if signals:
            print(f"\n{'=' * 60}")
            print(f"BULUNAN SİNYALLER: {len(signals)}")
            print(f"{'=' * 60}")
            for s in signals:
                print(f"\n  {s.symbol}")
                print(f"  Fiyat: {s.price:,.4f}")
                print(f"  Güç: {s.strength}/{s.total_criteria}")
                print(f"  Market Rejimi: {s.market_regime}")
                print(f"  Kriterler: {', '.join(s.criteria_met)}")
                for name in s.criteria_met:
                    detail = s.criteria_details[name]
                    print(f"    - {name}: {detail.get('detail', '')}")
                if s.exit_score > 0:
                    print(f"  Çıkış Puanı: {s.exit_score}/5")
        else:
            print("\nHiç sinyal bulunamadı.")


# ==================== CLI ====================
def main():
    scanner = Scanner()

    if "--test" in sys.argv:
        print("Telegram bağlantı testi...")
        if scanner.telegram.test_connection():
            print("✅ Telegram bağlantısı başarılı!")
            scanner.telegram.send_message("🧪 <b>Test mesajı</b>\nBot bağlantısı çalışıyor!")
            print("Test mesajı gönderildi.")
        else:
            print("❌ Telegram bağlantısı başarısız! .env dosyasını kontrol edin.")

    elif "--once" in sys.argv:
        scanner.run_once()

    else:
        scanner.run()


if __name__ == "__main__":
    main()
