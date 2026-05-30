# ============================================================================
# order_worker.py - Binance Futures Long Pozisyon İşlem Motoru
# ============================================================================
# scanner.py'nin MongoDB'ye yazdığı PENDING sinyalleri okur, LONG pozisyon açar,
# SL/TP takibini yapar ve pozisyonu kapatır.
# ============================================================================

import logging
import sys
import time
from datetime import datetime

from pymongo import MongoClient

from market_data import MarketData

# ==================== LOGLAMA ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("order_worker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("OrderWorker")

# ==================== İŞLEM AYARLARI ====================
TRADE_CONFIG = {
    # True → gerçek emir gönderir | False → simülasyon (kuru çalışma)
    "enabled": True,

    # Her işlem için maksimum USDT bütçesi
    "max_budget_per_trade_usdt": 50.0,

    # Kaldıraç (Binance Futures arayüzünden önceden ayarlanmış olmalı)
    "leverage": 5,

    # Minimum kontrat miktarı (sembol bazlı stepSize'a göre değişebilir)
    "min_quantity": 0.001,

    # Sinyal işleme döngü aralığı (saniye)
    "poll_interval": 30,

    # Açık pozisyon takip aralığı (saniye)
    "track_interval": 60,
}

# ==================== MONGODB ====================
MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB  = "trade_bot"


class OrderWorker:
    """
    PENDING sinyalleri işleyip Futures Long pozisyon açan ve yöneten worker.
    """

    def __init__(self):
        self.market = MarketData()
        self.running = True

        # MongoDB bağlantısı
        try:
            self.db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self.db_client.admin.command("ping")
            self.db = self.db_client[MONGO_DB]
            self.signals_col   = self.db["signals"]
            self.positions_col = self.db["positions"]
            logger.info("MongoDB bağlantısı kuruldu.")
        except Exception as e:
            logger.critical(f"MongoDB bağlantı hatası: {e}")
            sys.exit(1)

    # ==================== SİNYAL İŞLEME ====================

    def process_pending_signals(self):
        """PENDING sinyalleri sırayla işler ve LONG pozisyon açar."""
        signals = list(
            self.signals_col.find({"status": "PENDING"}).sort("timestamp", 1)
        )
        if not signals:
            return

        logger.info(f"{len(signals)} adet PENDING sinyal bulundu.")

        for sig in signals:
            symbol = sig["symbol"]
            logger.info(f"İşleniyor: {symbol}")

            # ── Bakiye kontrolü ──
            available = self.market.get_available_balance("USDT")
            budget    = TRADE_CONFIG["max_budget_per_trade_usdt"]
            position_pct = sig.get("position_size_pct", 100) / 100.0
            allocated = budget * position_pct

            if available < allocated:
                logger.warning(
                    f"{symbol}: Yetersiz bakiye. "
                    f"Gerekli: {allocated:.2f} USDT, Mevcut: {available:.2f} USDT"
                )
                self._mark_signal(sig["_id"], "SKIPPED", "Yetersiz bakiye")
                continue

            # ── Güncel fiyatı al ──
            current_price = self.market.get_price(symbol)
            if not current_price:
                logger.error(f"{symbol}: Fiyat alınamadı, atlanıyor.")
                self._mark_signal(sig["_id"], "SKIPPED", "Fiyat alınamadı")
                continue

            # ── Kontrat miktarını hesapla ──
            # Miktar = Bütçe * Kaldıraç / Fiyat
            raw_qty = (allocated * TRADE_CONFIG["leverage"]) / current_price
            quantity = max(round(raw_qty, 3), TRADE_CONFIG["min_quantity"])

            logger.info(
                f"{symbol} | Fiyat: {current_price} | "
                f"Bütçe: {allocated:.2f} USDT | Miktar: {quantity}"
            )

            # ── Emir gönder (LONG açma: BUY LONG MARKET) ──
            if TRADE_CONFIG["enabled"]:
                order = self.market.create_futures_order(
                    symbol, "BUY", "LONG", "MARKET", quantity
                )
                if not order or "orderId" not in order:
                    logger.error(f"❌ {symbol} Futures Long emri başarısız!")
                    self._mark_signal(sig["_id"], "SKIPPED", "Emir başarısız")
                    continue
                order_id = order["orderId"]
                fill_price = float(order.get("avgPrice") or current_price)
                logger.info(f"✅ {symbol} Long açıldı. OrderId: {order_id}")
            else:
                # Simülasyon modu
                order_id = -1
                fill_price = current_price
                logger.info(f"[SIM] {symbol} Long açıldı (simülasyon). Fiyat: {fill_price}")

            # ── Pozisyonu MongoDB'ye kaydet ──
            sl_pct = sig.get("stop_loss_pct",  3.0)
            tp_pct = sig.get("take_profit_pct", 6.0)
            position_doc = {
                "symbol":          symbol,
                "side":            "LONG",
                "entry_price":     fill_price,
                "stop_loss_price": round(fill_price * (1 - sl_pct / 100), 6),
                "take_profit_price": round(fill_price * (1 + tp_pct / 100), 6),
                "quantity":        quantity,
                "order_id":        order_id,
                "signal_id":       sig["_id"],
                "matched_pattern": sig.get("matched_pattern", ""),
                "total_score":     sig.get("total_score", 0),
                "status":          "OPEN",
                "open_time":       datetime.now(),
                "close_time":      None,
                "close_reason":    None,
                "exit_price":      None,
                "final_pnl_pct":   None,
            }
            self.positions_col.insert_one(position_doc)
            self._mark_signal(sig["_id"], "EXECUTED", "Pozisyon açıldı")
            logger.info(
                f"💾 {symbol} pozisyonu kaydedildi. "
                f"SL: {position_doc['stop_loss_price']} | TP: {position_doc['take_profit_price']}"
            )

    # ==================== AÇIK POZİSYON TAKİBİ ====================

    def track_active_positions(self):
        """OPEN pozisyonları SL/TP kontrolüyle takip eder, gerekirse kapatır."""
        positions = list(self.positions_col.find({"status": "OPEN"}))
        if not positions:
            return

        for pos in positions:
            symbol = pos["symbol"]
            current_price = self.market.get_price(symbol)
            if not current_price:
                continue

            should_close  = False
            close_reason  = ""

            if current_price <= pos["stop_loss_price"]:
                should_close = True
                close_reason = "STOP_LOSS"
            elif current_price >= pos["take_profit_price"]:
                should_close = True
                close_reason = "TAKE_PROFIT"

            if not should_close:
                pnl = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
                logger.debug(f"{symbol} | {current_price:.6f} | PnL: {pnl:+.2f}%")
                continue

            # ── Pozisyonu kapat (LONG kapatma: SELL LONG MARKET) ──
            logger.info(f"🚪 {symbol} kapatılıyor. Neden: {close_reason}")
            if TRADE_CONFIG["enabled"]:
                result = self.market.create_futures_order(
                    symbol, "SELL", "LONG", "MARKET", pos["quantity"]
                )
                if not result or "orderId" not in result:
                    logger.error(f"❌ {symbol} pozisyonu kapatılamadı!")
                    continue
                exit_price = float(result.get("avgPrice") or current_price)
                logger.info(f"✅ {symbol} Long kapatıldı. OrderId: {result['orderId']}")
            else:
                exit_price = current_price
                logger.info(f"[SIM] {symbol} Long kapatıldı (simülasyon). Fiyat: {exit_price}")

            pnl_pct = ((exit_price - pos["entry_price"]) / pos["entry_price"]) * 100
            self.positions_col.update_one(
                {"_id": pos["_id"]},
                {"$set": {
                    "status":        "CLOSED",
                    "close_time":    datetime.now(),
                    "close_reason":  close_reason,
                    "exit_price":    exit_price,
                    "final_pnl_pct": round(pnl_pct, 4),
                }},
            )
            logger.info(f"📊 {symbol} kapatıldı | PnL: {pnl_pct:+.2f}% | Neden: {close_reason}")

    # ==================== YARDIMCI ====================

    def _mark_signal(self, signal_id, status: str, note: str = ""):
        self.signals_col.update_one(
            {"_id": signal_id},
            {"$set": {"status": status, "processed_at": datetime.now(), "note": note}},
        )

    # ==================== ANA DÖNGÜ ====================

    def run(self):
        logger.info(
            f"OrderWorker başlatıldı. "
            f"Mod: {'CANLI' if TRADE_CONFIG['enabled'] else 'SİMÜLASYON'} | "
            f"Kaldıraç: {TRADE_CONFIG['leverage']}x | "
            f"Bütçe/İşlem: {TRADE_CONFIG['max_budget_per_trade_usdt']} USDT"
        )

        tick = 0
        while self.running:
            try:
                self.process_pending_signals()

                # Pozisyon takibini her 2 döngüde bir çalıştır
                if tick % 2 == 0:
                    self.track_active_positions()

                tick += 1
                time.sleep(TRADE_CONFIG["poll_interval"])

            except KeyboardInterrupt:
                logger.info("OrderWorker durduruluyor...")
                self.running = False
            except Exception as e:
                logger.error(f"OrderWorker döngü hatası: {e}", exc_info=True)
                time.sleep(10)

        self.db_client.close()
        logger.info("OrderWorker kapatıldı.")


if __name__ == "__main__":
    worker = OrderWorker()
    worker.run()
