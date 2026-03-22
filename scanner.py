# ============================================================================
# scanner.py - Hiyerarşik Multi-TF OCC Scanner
# ============================================================================
# Tüm pariteleri 5 timeframe'de OCC durumu ile tarar.
# Her OCC renk değişiminde bildirim gönderir.
# Toplam puan ≥5 ve 15dk tetikleyince ALIM sinyali üretir.
# ============================================================================

import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    SCAN_INTERVAL,
    KLINE_INTERVAL,
    ALERT_COOLDOWN_MINUTES,
    DAILY_SUMMARY_HOUR,
    LOG_FILE, LOG_LEVEL,
    SEND_CHART_IMAGE,
    OCC_TIMEFRAMES,
    OCC_MIN_SCORE,
    ONLY_TRY,
    NOTIFY_ALL_TF_CHANGES,
    VOLUME_SPIKE,
    STABLECOIN_BLACKLIST,
)
from market_data import MarketData
from analyzer import MultiTfOccAnalyzer
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
    """Hiyerarşik multi-TF OCC tarayıcı."""

    def __init__(self):
        self.market = MarketData()
        self.analyzer = MultiTfOccAnalyzer()
        self.telegram = TelegramNotifier()

        # Cooldown takibi: {(symbol, timeframe): last_alert_time}
        self.alert_cooldowns = {}

        # Günlük sinyal kaydı
        self.daily_signals = []
        self.last_summary_date = None

        # Parite listesi
        self.pairs = []
        self.last_pair_refresh = 0

        # TF veri cache: {(symbol, tf): (df, timestamp)}
        self._tf_cache = {}

        # Graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Kapatılıyor...")
        self.running = False

    # ==================== PARİTE YÖNETİMİ ====================

    def refresh_pairs(self, force: bool = False) -> list:
        now = time.time()
        if not force and (now - self.last_pair_refresh) < 1800 and self.pairs:
            return self.pairs

        logger.info("Parite listesi güncelleniyor...")
        all_pairs = self.market.get_all_pairs()

        if ONLY_TRY:
            combined = all_pairs["TRY"]
        else:
            combined = all_pairs["TRY"] + all_pairs["USDT"]

        # Stablecoin blacklist filtresi
        combined = [p for p in combined
                    if not any(p.startswith(s) for s in STABLECOIN_BLACKLIST)]

        self.pairs = self.market.filter_by_volume(combined)
        self.last_pair_refresh = now

        logger.info(f"Aktif parite sayısı: {len(self.pairs)} "
                    f"(TRY: {sum(1 for p in self.pairs if p.endswith('TRY'))}, "
                    f"USDT: {sum(1 for p in self.pairs if p.endswith('USDT'))})")

        return self.pairs

    # ==================== COOLDOWN ====================

    def _is_on_cooldown(self, symbol: str, tf: str = "") -> bool:
        key = (symbol, tf)
        last_alert = self.alert_cooldowns.get(key)
        if not last_alert:
            return False
        elapsed = (datetime.now() - last_alert).total_seconds() / 60
        return elapsed < ALERT_COOLDOWN_MINUTES

    def _set_cooldown(self, symbol: str, tf: str = ""):
        self.alert_cooldowns[(symbol, tf)] = datetime.now()

    def _cleanup_cooldowns(self):
        now = datetime.now()
        expired = [k for k, t in self.alert_cooldowns.items()
                   if (now - t).total_seconds() / 60 >= ALERT_COOLDOWN_MINUTES]
        for k in expired:
            del self.alert_cooldowns[k]

    # ==================== TF VERİ ÇEKME ====================

    # Cache süreleri (saniye): üst TF'ler daha uzun cache
    CACHE_TTL = {
        "1w": 3600,   # 1 saat
        "1d": 1800,   # 30 dk
        "4h": 600,    # 10 dk
        "1h": 300,    # 5 dk
        "15m": 60,    # 1 dk
    }

    def _get_tf_data(self, symbol: str) -> dict:
        """
        Bir sembol için tüm 5 timeframe'in mum verisini çeker.
        Cache kullanır (TF'ye göre farklı cache süreleri).
        Cache hit'lerde sleep atlanır, cache miss'ler paralel çekilir.
        Returns: {timeframe: DataFrame}
        """
        now = time.time()
        tf_data = {}
        to_fetch = []  # Cache'de olmayan TF'ler

        for tf, (weight, limit, label) in OCC_TIMEFRAMES.items():
            cache_key = (symbol, tf)
            cached = self._tf_cache.get(cache_key)
            ttl = self.CACHE_TTL.get(tf, 300)

            if cached and (now - cached[1]) < ttl:
                tf_data[tf] = cached[0]
            else:
                to_fetch.append((tf, limit))

        if not to_fetch:
            return tf_data

        # Cache miss olan TF'leri paralel çek (ThreadPoolExecutor)
        def fetch_one(tf_limit):
            tf, limit = tf_limit
            df = self.market.get_klines(symbol, interval=tf, limit=limit)
            return tf, df

        with ThreadPoolExecutor(max_workers=min(len(to_fetch), 5)) as executor:
            futures = {executor.submit(fetch_one, tl): tl for tl in to_fetch}
            for future in as_completed(futures):
                try:
                    tf, df = future.result()
                    if df is not None and len(df) >= 30:
                        self._tf_cache[(symbol, tf)] = (df, now)
                        tf_data[tf] = df
                except Exception as e:
                    tf, _ = futures[future]
                    logger.warning(f"{symbol} {tf} paralel çekim hatası: {e}")

        # Tek bir rate limit bekleme (paralel çekim sonrası)
        time.sleep(0.2)

        return tf_data

    # ==================== HACİM SPIKE TESPİTİ ====================

    def _check_volume_spike(self, symbol: str, tf_data: dict) -> bool:
        """
        15dk hacmi, 24s ortalamanın X katını aşarsa spike tespit eder.
        Spike varsa Telegram'a anında bildirim gönderir.
        """
        if not VOLUME_SPIKE.get("enabled", False):
            return False

        df_15m = tf_data.get("15m")
        if df_15m is None or len(df_15m) < 100:
            return False

        # Cooldown kontrolü
        if self._is_on_cooldown(symbol, "volume_spike"):
            return False

        # Son 15dk mum hacmi (quote volume — USDT/TRY cinsinden)
        current_vol = float(df_15m["quote_volume"].iloc[-2])  # Son kapanmış mum

        # 24 saatlik ortalama 15dk hacim (96 mum = 24 saat)
        lookback = min(96, len(df_15m) - 1)
        avg_vol = float(df_15m["quote_volume"].iloc[-lookback-1:-1].mean())

        if avg_vol <= 0:
            return False

        multiplier = VOLUME_SPIKE.get("multiplier", 5.0)
        min_vol = VOLUME_SPIKE.get("min_volume_usdt", 50_000)
        ratio = current_vol / avg_vol

        if ratio >= multiplier and current_vol >= min_vol:
            # Spike tespit edildi!
            price = float(df_15m["close"].iloc[-1])
            logger.info(
                f"🚨 HACİM SPIKE: {symbol} | "
                f"Hacim: {current_vol:,.0f} ({ratio:.1f}x ortalama)"
            )

            self._send_volume_spike_alert(symbol, price, current_vol, avg_vol, ratio)
            cooldown_min = VOLUME_SPIKE.get("cooldown_minutes", 60)
            self.alert_cooldowns[(symbol, "volume_spike")] = datetime.now()
            return True

        return False

    def _send_volume_spike_alert(self, symbol: str, price: float,
                                  current_vol: float, avg_vol: float, ratio: float):
        """Volume spike Telegram bildirimi gönderir."""
        quote = "TRY" if symbol.endswith("TRY") else "USDT"
        base = symbol.replace("TRY", "").replace("USDT", "")

        message = (
            f"🚨 <b>ANORMAL HACİM — {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📊 <b>15dk Hacim:</b> {current_vol:,.0f} {quote}\n"
            f"📈 <b>24s Ortalama:</b> {avg_vol:,.0f} {quote}\n"
            f"⚡ <b>Oran:</b> {ratio:.1f}x (>{VOLUME_SPIKE.get('multiplier', 5)}x eşik)\n"
            f"\n"
            f"💰 <b>Fiyat:</b> {price:,.4f} {quote}\n"
            f"\n"
            f"⚠️ <i>Muhtemel haber/gelişme habercisi.</i>\n"
            f"<i>Teknik analiz ile doğrulayın.</i>\n"
            f"\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}'>TradingView</a>"
        )
        self.telegram.send_message(message)

    # ==================== TARAMA DÖNGÜSÜ ====================

    def scan_once(self) -> list:
        """Tüm pariteleri bir kez tarar."""
        pairs = self.refresh_pairs()
        signals_found = []
        scanned = 0
        errors = 0

        logger.info(f"Tarama başlıyor: {len(pairs)} parite, {len(OCC_TIMEFRAMES)} TF...")

        for i, symbol in enumerate(pairs):
            if not self.running:
                break

            try:
                # 5 TF verisi çek
                tf_data = self._get_tf_data(symbol)
                if not tf_data:
                    continue

                scanned += 1

                # 0. Hacim spike kontrolü (haber/gelişme habercisi)
                self._check_volume_spike(symbol, tf_data)

                # 1. Her TF'deki renk değişimlerini kontrol et
                if NOTIFY_ALL_TF_CHANGES:
                    changes = self.analyzer.check_tf_changes(symbol, tf_data)
                    for change in changes:
                        tf_status = change.tf_statuses[0]
                        cooldown_key = f"{tf_status.timeframe}_change"
                        if not self._is_on_cooldown(symbol, cooldown_key):
                            logger.info(
                                f"🔔 RENK DEĞİŞİMİ: {symbol} | "
                                f"{tf_status.label} ({tf_status.timeframe}) → "
                                f"{'🟢 YEŞİL' if tf_status.is_green else '🔴 KIRMIZI'}"
                            )
                            success = self.telegram.send_tf_change(symbol, tf_status, change.price)
                            if success:
                                self._set_cooldown(symbol, cooldown_key)

                # 2. Multi-TF analiz (ALIM sinyali kontrolü)
                signal = self.analyzer.analyze_multi_tf(symbol, tf_data)
                if signal and signal.is_valid_entry:
                    if not self._is_on_cooldown(symbol, "entry"):
                        logger.info(
                            f"🔔 ALIM SİNYALİ: {symbol} | "
                            f"Puan: {signal.total_score}/{signal.max_score} | "
                            f"RSI: {signal.rsi_value:.1f} ({signal.rsi_quality}) | "
                            f"ADX: {signal.adx_value:.1f} ({signal.adx_regime})"
                        )

                        chart_bytes = None
                        if SEND_CHART_IMAGE:
                            df_15m = tf_data.get("15m")
                            if df_15m is not None:
                                chart_bytes = generate_signal_chart(
                                    symbol, df_15m, signal.indicators
                                )

                        success = self.telegram.send_multi_tf_signal(
                            signal, chart_bytes=chart_bytes
                        )
                        if success:
                            self._set_cooldown(symbol, "entry")
                            signals_found.append(signal)
                            self.daily_signals.append(signal)
                            logger.info(f"✅ Sinyal gönderildi: {symbol}")

                # Rate limit (her 10 paritede 1s — Binance rate limit'e uygun)
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
        now = datetime.now()
        today = now.date()

        if self.last_summary_date == today:
            return

        if now.hour == DAILY_SUMMARY_HOUR:
            logger.info("Günlük özet gönderiliyor...")
            self.telegram.send_daily_summary(self.daily_signals, len(self.pairs))
            self.last_summary_date = today
            self.daily_signals = []

        if len(self.daily_signals) > 500:
            self.daily_signals = self.daily_signals[-500:]

    # ==================== ANA DÖNGÜ ====================

    def run(self):
        logger.info("=" * 60)
        logger.info("🎯 Multi-TF OCC Scanner başlatılıyor...")
        logger.info(f"   Tarama aralığı: {SCAN_INTERVAL}s")
        logger.info(f"   Timeframe'ler: {', '.join(OCC_TIMEFRAMES.keys())}")
        logger.info(f"   Min puan eşiği: {OCC_MIN_SCORE}")
        logger.info(f"   Parite modu: {'Sadece TRY' if ONLY_TRY else 'TRY + USDT'}")
        logger.info(f"   Cooldown: {ALERT_COOLDOWN_MINUTES}dk")
        logger.info("=" * 60)

        if not self.telegram.test_connection():
            logger.error("❌ Telegram bağlantısı başarısız!")
            return

        self.refresh_pairs(force=True)
        if not self.pairs:
            logger.error("❌ Hiç parite bulunamadı!")
            return

        self.telegram.send_startup(len(self.pairs))

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

            if self.running:
                logger.info(f"Sonraki tarama: {SCAN_INTERVAL}s sonra...")
                for _ in range(SCAN_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)

        logger.info("Bot durduruldu.")

    def run_once(self):
        logger.info("Tek seferlik tarama başlatılıyor...")
        self.refresh_pairs(force=True)
        if not self.pairs:
            logger.error("Hiç parite bulunamadı!")
            return

        logger.info(f"Toplam {len(self.pairs)} parite, {len(OCC_TIMEFRAMES)} TF taranacak")
        signals = self.scan_once()

        if signals:
            print(f"\n{'=' * 60}")
            print(f"BULUNAN ALIM SİNYALLERİ: {len(signals)}")
            print(f"{'=' * 60}")
            for s in signals:
                print(f"\n  {s.symbol} | Puan: {s.total_score}/{s.max_score}")
                print(f"  Fiyat: {s.price:,.4f}")
                print(f"  RSI: {s.rsi_value:.1f} ({s.rsi_quality})")
                print(f"  ADX: {s.adx_value:.1f} ({s.adx_regime})")
                for ts in s.tf_statuses:
                    status = "🟢" if ts.is_green else "🔴"
                    cross = " ← YENİ" if ts.just_crossed else ""
                    print(f"    {status} {ts.label} ({ts.timeframe}): "
                          f"{'Yeşil' if ts.is_green else 'Kırmızı'} "
                          f"[{ts.weight}p]{cross}")
        else:
            print("\nHiç alım sinyali bulunamadı.")


# ==================== CLI ====================
def main():
    scanner = Scanner()

    if "--test" in sys.argv:
        print("Telegram bağlantı testi...")
        if scanner.telegram.test_connection():
            print("✅ Telegram bağlantısı başarılı!")
            scanner.telegram.send_message("🧪 <b>Test mesajı</b>\nMulti-TF OCC Scanner bağlantısı çalışıyor!")
        else:
            print("❌ Telegram bağlantısı başarısız!")

    elif "--once" in sys.argv:
        scanner.run_once()

    else:
        scanner.run()


if __name__ == "__main__":
    main()
