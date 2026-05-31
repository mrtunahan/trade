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

from pymongo import MongoClient

from config import (
    SCAN_INTERVAL,
    KLINE_INTERVAL,
    ALERT_COOLDOWN_MINUTES,
    DAILY_SUMMARY_HOUR,
    LOG_FILE, LOG_LEVEL,
    SEND_CHART_IMAGE,
    OCC_TIMEFRAMES,
    OCC_MIN_SCORE,
    ONLY_USDT,
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
    """Hiyerarşik multi-TF OCC tarayıcı ve veri kaydedici."""

    def __init__(self):
        self.market = MarketData()
        self.analyzer = MultiTfOccAnalyzer()
        self.telegram = TelegramNotifier()

        # ---- LOKAL MONGODB BAĞLANTISI ----
        try:
            self.db_client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=3000)
            self.db_client.server_info()
            self.db = self.db_client["trade_bot"]
            self.signals_collection = self.db["signals"]
            logger.info("✅ Lokal MongoDB bağlantısı başarıyla kuruldu (Database: trade_bot).")
        except Exception as e:
            logger.critical(f"❌ Lokal MongoDB'ye bağlanılamadı! MongoDB servisinin çalıştığından emin olun: {e}")
            sys.exit(1)

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
        try:
            self.db_client.close()
            logger.info("MongoDB bağlantısı kapatıldı.")
        except Exception:
            pass

    # ==================== PARİTE YÖNETİMİ ====================

    def refresh_pairs(self, force: bool = False) -> list:
        now = time.time()
        if not force and (now - self.last_pair_refresh) < 1800 and self.pairs:
            return self.pairs

        logger.info("Parite listesi güncelleniyor...")
        all_pairs = self.market.get_all_pairs()

        if ONLY_USDT:
            combined = all_pairs["USDT"]
        else:
            combined = all_pairs["TRY"] + all_pairs["USDT"]

        self.pairs = self.market.filter_by_volume(combined)
        self.last_pair_refresh = now

        logger.info(f"Aktif parite sayısı: {len(self.pairs)} "
                    f"(USDT Perpetual Futures)")

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
        "1w": 3600, "1d": 1800, "4h": 600, "1h": 300, "15m": 60,
    }

    def _get_tf_data(self, symbol: str) -> dict:
        """
        Bir sembol için tüm 5 timeframe'in mum verisini paralel olarak çeker.
        Cache kullanır (TF'ye göre farklı cache süreleri).
        Returns: {timeframe: DataFrame}
        """
        now = time.time()
        tf_data = {}
        to_fetch = []

        for tf, (weight, limit, label) in OCC_TIMEFRAMES.items():
            cache_key = (symbol, tf)
            cached = self._tf_cache.get(cache_key)
            ttl = self.CACHE_TTL.get(tf, 300)

            if cached and (now - cached[1]) < ttl:
                tf_data[tf] = cached[0]
                continue

            to_fetch.append((tf, limit))

        if to_fetch:
            with ThreadPoolExecutor(max_workers=len(to_fetch)) as ex:
                futures = {
                    ex.submit(self.market.get_klines, symbol, tf, limit): (tf, limit)
                    for tf, limit in to_fetch
                }
                for future in as_completed(futures):
                    try:
                        df = future.result()
                        tf, _ = futures[future]
                        if df is not None and len(df) >= 30:
                            self._tf_cache[(symbol, tf)] = (df, now)
                            tf_data[tf] = df
                    except Exception as e:
                        tf, _ = futures[future]
                        logger.warning(f"{symbol} {tf} paralel çekim hatası: {e}")

        return tf_data

    # ==================== HACİM SPIKE TESPİTİ ====================

    def _check_volume_spike(self, symbol: str, tf_data: dict) -> bool:
        if not VOLUME_SPIKE.get("enabled", False):
            return False

        df_15m = tf_data.get("15m")
        lookback = VOLUME_SPIKE.get("lookback_bars", 20)
        if df_15m is None or len(df_15m) < lookback + 1:
            return False

        if self._is_on_cooldown(symbol, "volume_spike"):
            return False

        multiplier = VOLUME_SPIKE.get("multiplier", 5.0)
        min_vol = VOLUME_SPIKE.get("min_volume_usdt", 50_000)
        current_vol = float(df_15m["quote_volume"].iloc[-1])
        avg_vol = float(df_15m["quote_volume"].iloc[-lookback - 1:-1].mean())

        if avg_vol <= 0:
            return False

        ratio = current_vol / avg_vol
        if ratio >= multiplier and current_vol >= min_vol:
            price = float(df_15m["close"].iloc[-1])
            logger.info(f"🚨 HACİM SPIKE: {symbol} | Hacim: {current_vol:,.0f} ({ratio:.1f}x ortalama)")
            self._send_volume_spike_alert(symbol, price, current_vol, avg_vol, ratio)
            self.alert_cooldowns[(symbol, "volume_spike")] = datetime.now()
            return True

        return False

    def _send_volume_spike_alert(self, symbol: str, price: float, current_vol: float, avg_vol: float, ratio: float):
        quote = "TRY" if symbol.endswith("TRY") else "USDT"
        base = symbol.replace("TRY", "").replace("USDT", "")
        message = (
            f"🚨 <b>ANORMAL HACİM — {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>15dk Hacim:</b> {current_vol:,.0f} {quote}\n"
            f"📈 <b>24s Ortalama:</b> {avg_vol:,.0f} {quote}\n"
            f"⚡ <b>Oran:</b> {ratio:.1f}x (>{VOLUME_SPIKE.get('multiplier', 5)}x eşik)\n\n"
            f"💰 <b>Fiyat:</b> {price:,.4f} {quote}\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.telegram.send_message(message)

    # ==================== TEKİL PARİTE TARAMA ====================

    PAIR_BATCH_SIZE = 3
    BATCH_SLEEP = 1.2

    def _scan_single_pair(self, symbol: str) -> dict:
        result = {"symbol": symbol, "signal": None, "changes": [], "spike": False, "ok": False}
        try:
            tf_data = self._get_tf_data(symbol)
            if not tf_data:
                return result

            result["ok"] = True
            result["spike"] = self._check_volume_spike(symbol, tf_data)

            if NOTIFY_ALL_TF_CHANGES:
                result["changes"] = self.analyzer.check_tf_changes(symbol, tf_data)

            signal = self.analyzer.analyze_multi_tf(symbol, tf_data)
            if signal and signal.is_valid_entry:
                if SEND_CHART_IMAGE:
                    df_15m = tf_data.get("15m")
                    if df_15m is not None:
                        signal._chart_bytes = generate_signal_chart(symbol, df_15m, signal.indicators)
                result["signal"] = signal

        except Exception as e:
            logger.error(f"{symbol} tarama hatası: {e}")

        return result

    # ==================== TARAMA DÖNGÜSÜ ====================

    def scan_once(self) -> list:
        """Tüm pariteleri batch halinde paralel tarar; sinyalleri MongoDB'ye kaydeder."""
        pairs = self.refresh_pairs()
        # Stablecoin filtresi
        pairs = [p for p in pairs if p not in STABLECOIN_BLACKLIST]
        signals_found = []
        scanned = 0

        logger.info(f"Tarama başlıyor: {len(pairs)} parite, {len(OCC_TIMEFRAMES)} TF...")

        for batch_start in range(0, len(pairs), self.PAIR_BATCH_SIZE):
            if not self.running:
                break

            batch = pairs[batch_start:batch_start + self.PAIR_BATCH_SIZE]

            with ThreadPoolExecutor(max_workers=self.PAIR_BATCH_SIZE) as executor:
                futures = {executor.submit(self._scan_single_pair, sym): sym for sym in batch}
                for future in as_completed(futures):
                    result = future.result()
                    symbol = result["symbol"]

                    if not result["ok"]:
                        continue

                    scanned += 1

                    # Renk değişimi bildirimleri
                    for change in result["changes"]:
                        tf_status = change.tf_statuses[0]
                        cooldown_key = f"{tf_status.timeframe}_change"
                        if not self._is_on_cooldown(symbol, cooldown_key):
                            success = self.telegram.send_tf_change(symbol, tf_status, change.price)
                            if success:
                                self._set_cooldown(symbol, cooldown_key)

                    # ---- ALIM SİNYALİ VE MONGODB ENTEGRASYONU ----
                    signal_obj = result["signal"]
                    if signal_obj and not self._is_on_cooldown(symbol, "entry"):
                        logger.info(f"🔔 ALIM SİNYALİ: {symbol} | Puan: {signal_obj.total_score}/{signal_obj.max_score}")

                        # 1. MongoDB'ye kaydet (Order Worker için)
                        try:
                            star_info = signal_obj.signal_star_rating
                            signal_doc = {
                                "symbol": signal_obj.symbol,
                                "price": float(signal_obj.price),
                                "total_score": int(signal_obj.total_score),
                                "max_score": int(signal_obj.max_score),
                                "rsi_value": float(signal_obj.rsi_value) if signal_obj.rsi_value == signal_obj.rsi_value else None,
                                "rsi_quality": signal_obj.rsi_quality,
                                "adx_value": float(signal_obj.adx_value) if signal_obj.adx_value == signal_obj.adx_value else None,
                                "adx_regime": signal_obj.adx_regime,
                                "stop_loss_pct": float(signal_obj.stop_loss_pct),
                                "take_profit_pct": float(signal_obj.take_profit_pct),
                                "position_size_pct": float(signal_obj.position_size_pct),
                                "position_tier": signal_obj.position_tier,
                                "matched_pattern": signal_obj.matched_pattern_name,
                                "star_label": star_info.get("label", ""),
                                "stars": star_info.get("stars", ""),
                                # TF heatmap: dashboard'da görselleştirmek için
                                "tf_statuses": [
                                    {
                                        "timeframe": s.timeframe,
                                        "label": s.label,
                                        "is_green": s.is_green,
                                        "weight": s.weight,
                                        "just_crossed": s.just_crossed,
                                    }
                                    for s in signal_obj.tf_statuses
                                ],
                                "timestamp": datetime.now(),
                                "status": "PENDING",
                            }
                            # Aynı parite için bekleyen emir varsa mükerrer kayıt önle
                            self.signals_collection.update_one(
                                {"symbol": symbol, "status": "PENDING"},
                                {"$setOnInsert": signal_doc},
                                upsert=True,
                            )
                            logger.info(f"💾 {symbol} sinyali MongoDB'ye kaydedildi.")
                        except Exception as db_err:
                            logger.error(f"Sinyal DB'ye kaydedilemedi ({symbol}): {db_err}")

                        # 2. Telegram bildirimi
                        chart_bytes = getattr(signal_obj, "_chart_bytes", None)
                        success = self.telegram.send_multi_tf_signal(signal_obj, chart_bytes=chart_bytes)
                        if success:
                            self._set_cooldown(symbol, "entry")
                            signals_found.append(signal_obj)
                            self.daily_signals.append(signal_obj)

            time.sleep(self.BATCH_SLEEP)

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
        logger.info("🎯 Multi-TF OCC Scanner + DB Modu aktif...")
        logger.info(f"   Tarama aralığı: {SCAN_INTERVAL}s")
        logger.info(f"   Timeframe'ler: {', '.join(OCC_TIMEFRAMES.keys())}")
        logger.info(f"   Min puan eşiği: {OCC_MIN_SCORE}")
        logger.info(f"   Parite modu: Binance Futures USDT-M Perpetual")
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
