# ============================================================================
# order_worker.py - Binance.TR Spot Alım/Satım Pozisyon İşlem Motoru
# ============================================================================
# scanner.py'nin MongoDB'ye yazdığı PENDING sinyalleri okur, Spot alım yapar,
# SL/TP takibini yapar ve spot satış ile pozisyonu kapatır.
# ============================================================================

import os
import logging
import sys
import time
from datetime import datetime

from pymongo import MongoClient

from market_data import MarketData
from config import QUOTE_ASSET

# ==================== LOGLAMA ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("OrderWorker")

# ==================== İŞLEM AYARLARI ====================
TRADE_CONFIG = {
    # True → gerçek emir gönderir | False → simülasyon (kuru çalışma)
    "enabled": True,

    # Her işlem için maksimum bütçe (Quote asset cinsinden)
    "max_budget_per_trade": float(os.getenv("MAX_BUDGET_PER_TRADE", "500" if QUOTE_ASSET == "TRY" else "50")),

    # Kaldıraç (Spot trading için 1 olmalıdır)
    "leverage": 1,

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
        self.last_balance_warning_time = 0.0

        # MongoDB bağlantısı
        try:
            self.db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self.db_client.admin.command("ping")
            self.db = self.db_client[MONGO_DB]
            self.signals_col   = self.db["signals"]
            self.positions_col = self.db["positions"]
            
            # Performans için MongoDB indekslerini oluşturalım
            self.signals_col.create_index([("status", 1)])
            self.signals_col.create_index([("symbol", 1), ("status", 1)])
            self.signals_col.create_index([("timestamp", -1)])
            self.positions_col.create_index([("status", 1)])
            self.positions_col.create_index([("symbol", 1), ("status", 1)])
            
            logger.info("MongoDB bağlantısı kuruldu ve indeksler doğrulandı.")
            
            # Geriye dönük uyumluluk: Açık pozisyonlardaki eksik yıldız alanlarını sinyallerinden tamamla
            try:
                open_positions = list(self.positions_col.find({"status": "OPEN", "star_label": {"$exists": False}}))
                for pos in open_positions:
                    sig_id = pos.get("signal_id")
                    if sig_id:
                        sig_doc = self.signals_col.find_one({"_id": sig_id})
                        if sig_doc:
                            self.positions_col.update_one(
                                {"_id": pos["_id"]},
                                {"$set": {
                                    "star_label": sig_doc.get("stars", "⭐"),
                                    "position_tier": sig_doc.get("star_label", "Fırsat")
                                }}
                            )
                            logger.info(f"💾 {pos['symbol']} açık pozisyonunun yıldız bilgileri sinyalden güncellendi.")
            except Exception as mig_err:
                logger.warning(f"Açık pozisyon yıldız güncelleme hatası: {mig_err}")
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

        # ── Sinyal Zaman Aşımı Kontrolü (Maksimum 3 Saniye) ──
        active_signals = []
        for sig in signals:
            signal_age = (datetime.now() - sig["timestamp"]).total_seconds()
            if signal_age > 3.0:
                logger.warning(
                    f"⏰ {sig['symbol']} sinyali zaman aşımına uğradı ({signal_age:.1f}s > 3s). İptal ediliyor."
                )
                self._mark_signal(sig["_id"], "EXPIRED", f"Zaman aşımı: {signal_age:.1f}s")
            else:
                active_signals.append(sig)

        if not active_signals:
            return

        logger.info(f"{len(active_signals)} adet taze PENDING sinyal bulundu.")

        # ── Bakiye koruma kontrolü ──
        # Kullanılabilir TRY < cüzdan değerinin %20'si → alımları beklet
        available_try = self.market.get_available_balance(QUOTE_ASSET)
        wallet_value = self._calculate_wallet_value(available_try)

        if wallet_value > 0:
            balance_ratio = available_try / wallet_value
            if balance_ratio < 0.20:
                now_ts = time.time()
                if now_ts - self.last_balance_warning_time >= 15.0:
                    logger.info(
                        f"💰 Bakiye durumu: Serbest={available_try:.2f} TRY | "
                        f"Cüzdan={wallet_value:.2f} TRY | Oran=%{balance_ratio*100:.1f}"
                    )
                    logger.warning(
                        f"🛑 BAKİYE KORUMA MODU AKTİF! Serbest TRY ({available_try:.2f}) "
                        f"cüzdan değerinin %{balance_ratio*100:.1f}'i — %20 eşiğinin altında. "
                        f"Alımlar bekletiliyor."
                    )
                    self.last_balance_warning_time = now_ts
                for sig in active_signals:
                    self._mark_signal(
                        sig["_id"], "PENDING",
                        f"Bakiye koruma: %{balance_ratio*100:.1f} < %20 eşiği"
                    )
                return
            else:
                logger.info(
                    f"💰 Bakiye durumu: Serbest={available_try:.2f} TRY | "
                    f"Cüzdan={wallet_value:.2f} TRY | Oran=%{balance_ratio*100:.1f}"
                )

        for sig in active_signals:
            symbol = sig["symbol"]
            logger.info(f"İşleniyor: {symbol}")

            # ── Bakiye kontrolü ──
            available = self.market.get_available_balance(QUOTE_ASSET)
            # position_size_pct: yıldız sistemine göre kullanılabilir bakiyenin %'si
            # 3 yıldız → %24, 2 yıldız → %35, 1 yıldız → %44
            position_pct = sig.get("position_size_pct", 0.44)
            if position_pct > 1:
                position_pct = position_pct / 100.0  # eski format uyumluluğu
            # Yüzde kullanılabilir bakiyeden hesapla
            allocated = available * position_pct

            if available < allocated:
                logger.warning(
                    f"{symbol}: Yetersiz bakiye. "
                    f"Gerekli: {allocated:.2f} {QUOTE_ASSET}, Mevcut: {available:.2f} {QUOTE_ASSET}"
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
                f"Bütçe: {allocated:.2f} {QUOTE_ASSET} | Miktar: {quantity}"
            )

            # ── Emir gönder (Spot alım: BUY LIMIT) ──
            if TRADE_CONFIG["enabled"]:
                order_resp = self.market.create_futures_order(
                    symbol, "BUY", "LONG", "LIMIT", quantity, price=current_price
                )
                
                # Binance.TR yanıtı: {"code":0, "msg":"Success", "data":{"orderId":..., "executedPrice":..., "executedQty":...}}
                logger.info(f"📦 {symbol} API Yanıtı: {order_resp}")
                
                if not order_resp:
                    logger.error(f"❌ {symbol} Spot alım emri başarısız! (API yanıtı None)")
                    self._mark_signal(sig["_id"], "SKIPPED", "Emir başarısız - API yanıtsız")
                    continue
                
                # API hata kontrolü
                resp_code = order_resp.get("code", -1)
                if resp_code != 0:
                    logger.error(f"❌ {symbol} Spot alım emri başarısız! Hata: {order_resp.get('msg', 'Bilinmeyen')}")
                    self._mark_signal(sig["_id"], "SKIPPED", f"API Hata: {order_resp.get('msg', '')}")
                    continue
                
                # Yanıt verisini çıkar
                order = order_resp.get("data", order_resp)
                
                if not order or "orderId" not in order:
                    logger.error(f"❌ {symbol} Spot alım yanıtında orderId bulunamadı! Data: {order}")
                    self._mark_signal(sig["_id"], "SKIPPED", "orderId bulunamadı")
                    continue
                
                order_id = order["orderId"]
                fill_price = float(order.get("executedPrice") or order.get("avgPrice") or order.get("price") or current_price)
                if fill_price == 0:
                    fill_price = current_price
                # Gerçek dolum miktarını kullan (komisyon düşülmüş miktar)
                executed_qty = float(order.get("executedQty", 0))
                if executed_qty > 0:
                    quantity = executed_qty
                    logger.info(f"✅ {symbol} Spot alındı. OrderId: {order_id} | Dolum Fiyatı: {fill_price} | Gerçek Miktar: {executed_qty}")
                else:
                    logger.info(f"✅ {symbol} Spot alındı. OrderId: {order_id} | Dolum Fiyatı: {fill_price} | Miktar: {quantity} (executedQty yok)")
            else:
                # Simülasyon modu
                order_id = -1
                fill_price = current_price
                logger.info(f"[SIM] {symbol} Spot alındı (simülasyon). Fiyat: {fill_price}")

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
                "star_label":      sig.get("stars", "⭐"),
                "position_tier":   sig.get("star_label", "Fırsat"),
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

            # ── Pozisyonu kapat (Spot satış: SELL LIMIT) ──
            logger.info(f"🚪 {symbol} kapatılıyor. Neden: {close_reason}")
            if TRADE_CONFIG["enabled"]:
                sell_qty = pos["quantity"]
                sell_resp = self.market.create_futures_order(
                    symbol, "SELL", "LONG", "LIMIT", sell_qty, price=current_price
                )
                logger.info(f"📦 {symbol} Satış API Yanıtı: {sell_resp}")
                
                # Insufficient balance hatası → gerçek bakiyeyi çekip tekrar dene
                if sell_resp and sell_resp.get("code") == 2202:
                    logger.warning(f"⚠️ {symbol} yetersiz bakiye, gerçek bakiye sorgulanıyor...")
                    # Sembolden base asset'i çıkar (MEMETRY → MEME, 1MBABYDOGETRY → 1MBABYDOGE)
                    base_asset = symbol.replace("TRY", "").replace("USDT", "")
                    actual_balance = self.market.get_asset_balance(base_asset)
                    if actual_balance > 0:
                        logger.info(f"📊 {symbol} gerçek bakiye: {actual_balance} | Kayıtlı: {sell_qty}")
                        sell_qty = actual_balance
                        # Pozisyondaki miktarı güncelle
                        self.positions_col.update_one(
                            {"_id": pos["_id"]},
                            {"$set": {"quantity": actual_balance}}
                        )
                        sell_resp = self.market.create_futures_order(
                            symbol, "SELL", "LONG", "LIMIT", sell_qty, price=current_price
                        )
                        logger.info(f"📦 {symbol} 2. Satış Denemesi Yanıtı: {sell_resp}")
                    else:
                        logger.error(f"❌ {symbol} gerçek bakiye 0, pozisyon kapatılamıyor!")
                        # Bakiye yoksa pozisyonu otomatik kapat (coin zaten elden çıkmış olabilir)
                        self.positions_col.update_one(
                            {"_id": pos["_id"]},
                            {"$set": {
                                "status": "CLOSED",
                                "close_time": datetime.now(),
                                "close_reason": f"{close_reason}_BALANCE_SIFIR",
                                "exit_price": current_price,
                                "final_pnl_pct": round(((current_price - pos['entry_price']) / pos['entry_price']) * 100, 4),
                            }}
                        )
                        logger.info(f"📊 {symbol} bakiye sıfır, pozisyon kapatıldı olarak işaretlendi.")
                        continue
                
                if not sell_resp or sell_resp.get("code", -1) != 0:
                    logger.error(f"❌ {symbol} spot pozisyonu satılamadı! Yanıt: {sell_resp}")
                    continue
                
                result = sell_resp.get("data", sell_resp)
                if not result or "orderId" not in result:
                    logger.error(f"❌ {symbol} satış yanıtında orderId bulunamadı! Data: {result}")
                    continue
                
                exit_price = float(result.get("executedPrice") or result.get("avgPrice") or result.get("price") or current_price)
                if exit_price == 0:
                    exit_price = current_price
                logger.info(f"✅ {symbol} Spot satıldı. OrderId: {result['orderId']} | Fiyat: {exit_price}")
            else:
                exit_price = current_price
                logger.info(f"[SIM] {symbol} Spot satıldı (simülasyon). Fiyat: {exit_price}")

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

    def _calculate_wallet_value(self, available_try: float) -> float:
        """
        Toplam cüzdan değerini TRY cinsinden hesaplar.
        Cüzdan değeri = Serbest TRY + Açık pozisyonların güncel piyasa değeri
        """
        total = available_try

        open_positions = list(self.positions_col.find({"status": "OPEN"}))
        for pos in open_positions:
            symbol = pos["symbol"]
            qty = pos.get("quantity", 0)
            current_price = self.market.get_price(symbol)
            if current_price and qty > 0:
                total += qty * current_price

        return total

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
            f"Bütçe/İşlem: {TRADE_CONFIG['max_budget_per_trade']} {QUOTE_ASSET}"
        )

        last_track_time = 0.0
        fast_poll_interval = 0.5

        while self.running:
            try:
                # 1. PENDING sinyalleri milisaniyeler bazında kontrol et
                self.process_pending_signals()

                # 2. Açık pozisyonları daha seyrek kontrol et (örn. her 30-60 saniyede bir)
                now = time.time()
                if now - last_track_time >= TRADE_CONFIG["track_interval"]:
                    self.track_active_positions()
                    last_track_time = now

                # 0.5 saniye uyu
                time.sleep(fast_poll_interval)

            except KeyboardInterrupt:
                logger.info("OrderWorker durduruluyor...")
                self.running = False
            except Exception as e:
                logger.error(f"OrderWorker döngü hatası: {e}", exc_info=True)
                time.sleep(5)

        self.db_client.close()
        logger.info("OrderWorker kapatıldı.")


if __name__ == "__main__":
    worker = OrderWorker()
    worker.run()
