# ============================================================================
# scanner.py - 4-Stage Spot Pipeline Scanner
# ============================================================================
import sys
import time
import signal
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from pymongo import MongoClient
import pandas as pd

from config import (
    SCAN_INTERVAL,
    KLINE_INTERVAL,
    DAILY_SUMMARY_HOUR,
    LOG_FILE, LOG_LEVEL,
    SEND_CHART_IMAGE,
    ONLY_USDT,
    STABLECOIN_BLACKLIST,
    SPOT_PIPELINE,
    QUOTE_ASSET
)
from market_data import MarketData
from analyzer import SpotPipelineAnalyzer
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

setup_logging()
logger = logging.getLogger("Scanner")


class Scanner:
    """4-Aşamalı Spot Pipeline Tarayıcı ve Sinyal Jeneratörü."""

    def __init__(self):
        self.market = MarketData()
        self.analyzer = SpotPipelineAnalyzer()
        self.telegram = TelegramNotifier()

        # ---- MONGODB BAĞLANTISI ----
        try:
            self.db_client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=3000)
            self.db_client.server_info()
            self.db = self.db_client["trade_bot"]
            self.signals_collection = self.db["signals"]
            
            # MongoDB İndeksleri
            self.signals_collection.create_index([("status", 1)])
            self.signals_collection.create_index([("symbol", 1), ("status", 1)])
            self.signals_collection.create_index([("timestamp", -1)])
            
            logger.info("✅ MongoDB bağlantısı başarıyla kuruldu ve indeksler doğrulandı.")
        except Exception as e:
            logger.critical(f"❌ MongoDB bağlantı hatası: {e}")
            sys.exit(1)

        # Cooldown takibi: {symbol: last_alert_time}
        self.alert_cooldowns = {}
        self.daily_signals = []
        self.last_summary_date = None
        self.pairs = []
        self.last_pair_refresh = 0
        self.btc_adx = 25.0

        # Graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Scanner kapatılıyor...")
        self.running = False
        try:
            self.db_client.close()
            logger.info("MongoDB bağlantısı kapatıldı.")
        except Exception:
            pass

    def refresh_pairs(self, force: bool = False) -> list:
        now = time.time()
        if not force and (now - self.last_pair_refresh) < 1800 and self.pairs:
            return self.pairs

        logger.info("Parite listesi güncelleniyor...")
        all_pairs = self.market.get_all_pairs()
        combined = all_pairs.get(QUOTE_ASSET, all_pairs.get("TRY", []))
        
        # Filtreleri kaldırıp en güncel pariteleri alalım
        self.pairs = [p for p in combined if p not in STABLECOIN_BLACKLIST]
        self.last_pair_refresh = now
        logger.info(f"Aktif taranacak {QUOTE_ASSET} Spot çifti sayısı: {len(self.pairs)}")
        return self.pairs

    def _is_on_cooldown(self, symbol: str) -> bool:
        last_alert = self.alert_cooldowns.get(symbol)
        if not last_alert:
            return False
        elapsed = (datetime.now() - last_alert).total_seconds() / 60
        return elapsed < 30  # Sinyaller için 30 dakika cooldown

    def _set_cooldown(self, symbol: str):
        self.alert_cooldowns[symbol] = datetime.now()

    def _cleanup_cooldowns(self):
        now = datetime.now()
        expired = [k for k, t in self.alert_cooldowns.items() if (now - t).total_seconds() / 60 >= 30]
        for k in expired:
            del self.alert_cooldowns[k]

    # ==================== PIPELINE AŞAMALARI ====================

    def _determine_market_regime(self) -> str:
        """
        AŞAMA 1: Market Regime Filtresi
        BTC 1 Saatlik verisi üzerinden piyasanın genel yönünü belirler.
        """
        logger.info("Stage 1: Market Regime analizi yapılıyor (BTC 1h)...")
        btc_symbol = f"BTC{QUOTE_ASSET}"
        
        # BTC 1h klines çek
        df_btc = self.market.get_klines(btc_symbol, "1h", 250)
        if df_btc is None or len(df_btc) < 200:
            # Fallback to BTCUSDT if BTCTRY fails or has insufficient data
            logger.warning("BTC/TRY verisi yetersiz, BTC/USDT üzerinden regime analizi yapılıyor...")
            df_btc = self.market.get_klines("BTCUSDT", "1h", 250)

        if df_btc is None or len(df_btc) < 200:
            logger.error("Bitcoin 1h klines alınamadı! Varsayılan olarak WEAK (Tepki) modu seçiliyor.")
            return "WEAK"

        # Göstergeleri hesapla
        closes = df_btc["close"]
        ema50 = closes.ewm(span=50, adjust=False).mean()
        ema200 = closes.ewm(span=200, adjust=False).mean()
        adx = self.analyzer.calculate_adx(df_btc, 14)

        # Son tamamlanmış 1h mum (-2)
        ema50_val = ema50.iloc[-2]
        ema200_val = ema200.iloc[-2]
        adx_val = adx.iloc[-2]
        
        self.btc_adx = float(adx_val)
        
        logger.info(f"BTC 1h Göstergeleri: EMA50={ema50_val:.1f} | EMA200={ema200_val:.1f} | ADX={adx_val:.1f}")

        # Koşul: EMA50 > EMA200 ise Yönü belirler (Boğa/Trend)
        if ema50_val > ema200_val:
            logger.info("🔥 piyasa REJİMİ: BOĞA / TREND MODU AKTİF (Rotayı GÜÇLÜ 30'a çevir).")
            return "STRONG"
        else:
            logger.info("❄️ piyasa REJİMİ: AŞIRI SATIM / TEPKİ MODU AKTİF (Rotayı GÜÇLÜSÜZ 30'a çevir).")
            return "WEAK"

    def _fetch_daily_data(self, symbol: str) -> tuple:
        """
        Her parite için paralel veri çekim yardımcısı.
        """
        try:
            df = self.market.get_klines(symbol, "1d", 35)
            if df is not None and len(df) >= 31:
                return symbol, df
        except Exception as e:
            logger.warning(f"{symbol} Daily mum verisi çekilemedi: {e}")
        return symbol, None

    def _scan_relative_strength(self, pairs: list) -> tuple:
        """
        AŞAMA 2: Relative Strength (Çift Yönlü Tarama)
        311 coini tarayarak en güçlü ve en güçsüz 30 pariteyi belirler.
        """
        logger.info(f"Stage 2: Relative Strength hesaplanıyor ({len(pairs)} parite)...")
        
        daily_dfs = {}
        rs_scores = []

        # Paralel olarak tüm paritelerin Günlük verilerini çek
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(self._fetch_daily_data, sym): sym for sym in pairs}
            for future in as_completed(futures):
                sym, df = future.result()
                if df is not None:
                    daily_dfs[sym] = df
                    
                    # Get returns (Non-repaint: iloc[-2] vs historical)
                    # 30d return: (Close[-2] - Close[-32]) / Close[-32]
                    # 7d return: (Close[-2] - Close[-9]) / Close[-9]
                    # 24h return: (Close[-2] - Close[-3]) / Close[-3]
                    try:
                        c_now = float(df["close"].iloc[-2])
                        c_30d = float(df["close"].iloc[-32])
                        c_7d  = float(df["close"].iloc[-9])
                        c_24h = float(df["close"].iloc[-3])
                        
                        r_30d = (c_now - c_30d) / c_30d if c_30d > 0 else 0
                        r_7d  = (c_now - c_7d) / c_7d if c_7d > 0 else 0
                        r_24h = (c_now - c_24h) / c_24h if c_24h > 0 else 0
                        
                        # RS_SCORE formülü
                        rs_score = (r_30d * 0.4) + (r_7d * 0.3) + (r_24h * 0.3)
                        rs_scores.append((sym, rs_score))
                    except Exception as calc_err:
                        pass

        if not rs_scores:
            return [], [], {}, {}

        # Skora göre büyükten küçüğe sırala
        rs_scores.sort(key=lambda x: x[1], reverse=True)

        # Yeşil Liste (Top 30) - En yüksek güce sahip trend takipçileri
        green_list = [item[0] for item in rs_scores[:30]]
        # Kırmızı Liste (Bottom 30) - En zayıf dipten dönüş adayları
        red_list = [item[0] for item in rs_scores[-30:]]

        logger.info(f"✅ Çift Yönlü Tarama Tamamlandı:")
        logger.info(f"   • Yeşil Liste (Güçlü 30) Lideri: {green_list[0]} (Skor: {rs_scores[0][1]:+.2%})")
        logger.info(f"   • Kırmızı Liste (Güçsüz 30) Lideri: {red_list[-1]} (Skor: {rs_scores[-1][1]:+.2%})")

        rs_scores_map = {sym: score for sym, score in rs_scores}
        return green_list, red_list, daily_dfs, rs_scores_map


    def _fetch_lower_tf_data(self, symbol: str, segment: str) -> tuple:
        """
        Adaylar için Macro, Setup ve Trigger zaman dilimlerini paralel çeker.
        """
        tfs = ["1h", "15m", "3m", "1m"]
        lower_data = {}
        try:
            for tf in tfs:
                if tf == "1h":
                    limit = 250
                elif tf == "15m":
                    limit = 100
                else:
                    limit = 60
                
                df = self.market.get_klines(symbol, tf, limit)
                if df is not None:
                    lower_data[tf] = df
            return symbol, lower_data
        except Exception as e:
            logger.warning(f"{symbol} alt zaman dilimi kline çekilemedi: {e}")
        return symbol, {}

    def scan_once(self) -> list:
        """4 Aşamalı Spot Pipeline Tarama Akışı"""
        pairs = self.refresh_pairs()
        if not pairs:
            logger.error("Hiç parite bulunamadı!")
            return []

        signals_found = []

        # AŞAMA 1: Market Regime Belirle
        regime = self._determine_market_regime()

        # AŞAMA 2: Çift Yönlü Taramayı Gerçekleştir
        green_list, red_list, daily_dfs, rs_scores_map = self._scan_relative_strength(pairs)
        if not green_list or not red_list:
            logger.error("Relative strength taraması başarısız oldu!")
            return []

        # Rejime göre taranacak aday listeyi belirle
        target_list = green_list if regime == "STRONG" else red_list
        logger.info(f"AŞAMA 3 & 4: {regime} Segmentindeki {len(target_list)} Aday Puanlanıyor ve Tetik Kontrolü Yapılıyor...")

        # Adayların alt zaman dilimi (Stage 4) kline verilerini paralel olarak çekelim
        lower_tfs_cache = {}
        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = {executor.submit(self._fetch_lower_tf_data, sym, regime): sym for sym in target_list}
            for future in as_completed(futures):
                sym, lower_data = future.result()
                if lower_data:
                    lower_tfs_cache[sym] = lower_data

        # Adayları Teker Teker Analiz Et ve Skorla (Stage 3 & 4)
        for symbol in target_list:
            if not self.running:
                break

            lower_data = lower_tfs_cache.get(symbol)

            if lower_data is None:
                continue

            # Analizi gerçekleştir
            signal_obj = self.analyzer.analyze_candidate(symbol, regime, lower_data)
            if signal_obj is None:
                continue

            # AŞAMA 4: Tetik Onaylandı ve Cooldown Uygun
            if signal_obj.is_valid_entry:
                if not self._is_on_cooldown(symbol):
                    logger.info(f"🔔 SİNYAL TETİKLENDİ: {symbol} | Segment: {regime} | Skor: {signal_obj.total_score}")
                    
                    signal_obj.adx_value = self.btc_adx

                    # Pipeline filtrelerini çek (dashboard'da rozet olarak göstereceğiz)
                    pipeline_filters = {
                        "ema_ok": False,
                        "rsi_ok": False,
                        "vol_ok": False
                    }
                    for s in signal_obj.tf_statuses:
                        if s.timeframe == "1h_ema":
                            pipeline_filters["ema_ok"] = s.is_green
                        elif s.timeframe == "15m_rsi":
                            pipeline_filters["rsi_ok"] = s.is_green
                        elif s.timeframe == "15m_vol":
                            pipeline_filters["vol_ok"] = s.is_green

                    # Kullanıcının görsel olarak takip etmek istediği OCC zaman dilimi durumlarını hesapla (Giriş kriteri değil, sadece görsel bilgi!)
                    logger.info(f"📊 {symbol} için görsel OCC Heatmap verileri hesaplanıyor...")
                    occ_statuses = []
                    for occ_tf in ["1w", "1d", "4h", "1h", "15m"]:
                        try:
                            occ_df = self.market.get_klines(symbol, occ_tf, 50)
                            if occ_df is not None and len(occ_df) >= 15:
                                occ_status = self.analyzer.calculate_occ_status(occ_df, occ_tf)
                                occ_statuses.append(occ_status)
                        except Exception as occ_err:
                            logger.warning(f"{symbol} {occ_tf} OCC kline çekilemedi: {occ_err}")

                    if occ_statuses:
                        signal_obj.tf_statuses = occ_statuses

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
                            "adx_value": float(self.btc_adx),
                            "adx_regime": signal_obj.adx_regime,
                            "stop_loss_pct": float(signal_obj.stop_loss_pct),
                            "take_profit_pct": float(signal_obj.take_profit_pct),
                            "position_size_pct": float(signal_obj.position_size_pct),
                            "position_tier": signal_obj.position_tier,
                            "matched_pattern": signal_obj.matched_pattern_name,
                            "star_label": star_info.get("label", ""),
                            "stars": star_info.get("stars", ""),
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
                            "pipeline_filters": pipeline_filters,
                            "segment_type": signal_obj.segment_type,
                            "candlestick_pattern": signal_obj.candlestick_pattern,
                            "trigger_tf": signal_obj.trigger_tf,
                            "rs_score": float(rs_scores_map.get(symbol, 0.0)) if "rs_scores_map" in locals() else 0.0,
                            "timestamp": datetime.now(),
                            "status": "PENDING",
                        }
                        
                        # Mükerrer alım önleme
                        self.signals_collection.update_one(
                            {"symbol": symbol, "status": "PENDING"},
                            {"$setOnInsert": signal_doc},
                            upsert=True,
                        )
                        logger.info(f"💾 {symbol} sinyali MongoDB'ye PENDING olarak kaydedildi.")
                    except Exception as db_err:
                        logger.error(f"Sinyal DB'ye kaydedilemedi ({symbol}): {db_err}")

                    # 2. Premium Matplotlib Grafiği Oluştur
                    chart_bytes = b""
                    if SEND_CHART_IMAGE:
                        trigger_tf = signal_obj.trigger_tf
                        tr_df = lower_data.get(trigger_tf)
                        if tr_df is not None:
                            chart_bytes = generate_signal_chart(symbol, tr_df, signal_obj.indicators)

                    # 3. Telegram Bildirimi Gönder
                    success = self.telegram.send_multi_tf_signal(signal_obj, chart_bytes=chart_bytes)
                    if success:
                        self._set_cooldown(symbol)
                        signals_found.append(signal_obj)
                        self.daily_signals.append(signal_obj)

        logger.info(f"Tarama tamamlandı: {len(target_list)} adaydan {len(signals_found)} adet alım sinyali üretildi.")
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
        logger.info("🎯 Spot 4-Stage Pipeline Scanner Başlatıldı...")
        logger.info(f"   Tarama aralığı: {SCAN_INTERVAL}s")
        logger.info(f"   Quote Para Birimi: {QUOTE_ASSET}")
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
            start_time = time.time()

            try:
                self.scan_once()
                self.check_daily_summary()
                self._cleanup_cooldowns()
            except Exception as e:
                logger.error(f"Döngü hatası: {e}", exc_info=True)
                self.telegram.send_error(f"Tarama hatası: {str(e)[:200]}")

            elapsed = time.time() - start_time
            sleep_time = max(1.0, float(SCAN_INTERVAL) - elapsed)

            if self.running:
                logger.info(f"Tarama {elapsed:.1f}s sürdü. Sonraki döngü: {sleep_time:.1f}s sonra...")
                for _ in range(int(sleep_time)):
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
        self.scan_once()


# ==================== CLI ====================
def main():
    scanner = Scanner()

    if "--test" in sys.argv:
        print("Telegram bağlantı testi...")
        if scanner.telegram.test_connection():
            print("✅ Telegram bağlantısı başarılı!")
            scanner.telegram.send_message("🧪 <b>Test mesajı</b>\nSpot Pipeline Scanner bağlantısı çalışıyor!")
        else:
            print("❌ Telegram bağlantısı başarısız!")
    elif "--once" in sys.argv:
        scanner.run_once()
    else:
        scanner.run()


if __name__ == "__main__":
    main()
