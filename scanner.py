# ============================================================================
# scanner.py - Ana Tarayıcı
# ============================================================================
# Tüm TRY ve USDT paritelerini periyodik olarak tarar,
# kriterlere uyan sinyalleri Telegram'a bildirir.
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

    # ==================== TARAMA DÖNGÜSÜ ====================

    def scan_once(self) -> list:
        """Tüm pariteleri bir kez tarar. Bulunan sinyalleri döndürür."""
        pairs = self.refresh_pairs()
        signals_found = []
        scanned = 0
        errors = 0

        logger.info(f"Tarama başlıyor: {len(pairs)} parite...")

        for i, symbol in enumerate(pairs):
            if not self.running:
                break

            try:
                # Mum verisi çek
                df = self.market.get_klines(symbol)
                if df is None or len(df) < 50:
                    continue

                scanned += 1

                # Analiz et
                signal = self.analyzer.analyze(symbol, df)

                if signal:
                    # Cooldown kontrolü
                    if self._is_on_cooldown(symbol):
                        logger.debug(f"{symbol}: Sinyal var ama cooldown'da")
                        continue

                    logger.info(
                        f"🔔 SİNYAL: {symbol} | Güç: {signal.strength}/{signal.total_criteria} | "
                        f"Fiyat: {signal.price:,.4f} | Kriterler: {', '.join(signal.criteria_met)}"
                    )

                    # Grafik oluştur
                    chart_bytes = None
                    if SEND_CHART_IMAGE:
                        chart_bytes = generate_signal_chart(symbol, df, signal.indicators)

                    # Telegram'a gönder
                    success = self.telegram.send_signal(signal, chart_bytes=chart_bytes if chart_bytes else None)

                    if success:
                        self._set_cooldown(symbol)
                        signals_found.append(signal)
                        self.daily_signals.append(signal)
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

    # ==================== ANA DÖNGÜ ====================

    def run(self):
        """Sürekli tarama döngüsü."""
        logger.info("=" * 60)
        logger.info("🤖 BinanceTR Scanner Bot başlatılıyor...")
        logger.info(f"   Tarama aralığı: {SCAN_INTERVAL}s")
        logger.info(f"   Zaman dilimi: {KLINE_INTERVAL}")
        logger.info(f"   Cooldown: {ALERT_COOLDOWN_MINUTES}dk")
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
        self.telegram.send_startup(len(self.pairs))

        # Ana döngü
        cycle = 0
        while self.running:
            cycle += 1
            logger.info(f"\n{'─' * 40} Döngü #{cycle} {'─' * 40}")

            try:
                self.scan_once()
                self.check_daily_summary()
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
                print(f"  Kriterler: {', '.join(s.criteria_met)}")
                for name in s.criteria_met:
                    detail = s.criteria_details[name]
                    print(f"    - {name}: {detail.get('detail', '')}")
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
