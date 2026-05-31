# ============================================================================
# market_data.py - Binance.TR Spot Veri Çekici ve Emir Motoru
# ============================================================================
import time
import math
import hmac
import hashlib
import logging
from typing import Optional
from urllib.parse import urlencode

import requests
import pandas as pd
from pymongo import MongoClient

from config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_BASE_URL,
    PAIR_MODE,
    MANUAL_USDT_PAIRS,
    MIN_VOLUME_USDT,
    KLINE_INTERVAL,
    KLINE_LIMIT,
    QUOTE_ASSET,
    STABLECOIN_BASES,
)

logger = logging.getLogger("MarketData")

class MarketData:
    """Binance.TR Spot (Kaldıraçsız Spot Alım/Satım) istemcisi."""

    def __init__(self):
        self.base_url = "https://api.binance.me"  # Kamu verileri için
        self.signed_base_url = "https://www.binance.tr"  # İmzalı cüzdan/emir işlemleri için
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=30,
            pool_maxsize=30,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Sembol filtreleri cache: {symbol: {stepSize, minQty, tickSize, minNotional}}
        self._symbol_filters: dict = {}
        self._filters_loaded = False

    def _send_public_request(self, endpoint: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
        """Gönderilen genel istekleri rate limit (429/418) korumasıyla iletir."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=timeout)
                if resp.status_code in [429, 418]:
                    logger.warning(
                        f"⚠️ Binance Rate Limit (HTTP {resp.status_code}) on {endpoint}. "
                        f"5 saniye bekleniyor... (Deneme {attempt+1}/3)"
                    )
                    time.sleep(5)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == 2:
                    logger.error(f"Public request error after 3 attempts on {endpoint}: {e}")
                    return None
                time.sleep(1)
        return None

    # ==================== GÜVENLİK VE İMZA ====================

    def _generate_signature(self, query_string: str) -> str:
        """Binance.TR Spot API imzalı istekleri için HMAC-SHA256 üretir."""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _send_signed_request(
        self, method: str, endpoint: str, params: dict = None
    ) -> Optional[dict]:
        """İmzalı özel API isteklerini Binance.TR Spot'a iletir."""
        if params is None:
            params = {}

        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = self._generate_signature(query_string)

        headers = {
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "Mozilla/5.0"
        }

        try:
            if method.upper() == "GET":
                url = f"{self.signed_base_url}{endpoint}?{query_string}&signature={signature}"
                resp = self.session.get(url, headers=headers, timeout=15)
            elif method.upper() == "POST":
                # For POST requests, Binance.TR Open API expects parameters in application/x-www-form-urlencoded body
                url = f"{self.signed_base_url}{endpoint}"
                payload = params.copy()
                payload["signature"] = signature
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                resp = self.session.post(url, data=payload, headers=headers, timeout=15)
            elif method.upper() == "DELETE":
                url = f"{self.signed_base_url}{endpoint}?{query_string}&signature={signature}"
                resp = self.session.delete(url, headers=headers, timeout=15)
            else:
                return None

            if resp.status_code != 200:
                logger.error(
                    f"❌ Binance.TR İmzalı İstek Hatası ({endpoint}) [HTTP {resp.status_code}]: {resp.text}"
                )
                return None
            
            res_json = resp.json()
            if isinstance(res_json, dict) and res_json.get("code", 0) != 0:
                logger.error(
                    f"❌ Binance.TR API Hata Yanıtı ({endpoint}): {res_json}"
                )
            return res_json
        except Exception as e:
            logger.error(f"❌ Binance.TR Bağlantı Hatası ({endpoint}): {e}")
            return None

    # ==================== SPOT PARİTE KEŞFİ ====================

    def get_all_pairs(self) -> dict:
        """
        Aktif Spot çiftlerini getirir.
        """
        if PAIR_MODE == "manual":
            return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

        try:
            data = self._send_public_request("/api/v3/exchangeInfo", timeout=15)
            if not data:
                return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

            discovered_pairs = []
            for s in data.get("symbols", []):
                base_asset = s.get("baseAsset", "").upper()
                if (
                    s.get("status") == "TRADING"
                    and s.get("quoteAsset") == QUOTE_ASSET
                    and base_asset not in STABLECOIN_BASES
                ):
                    discovered_pairs.append(s["symbol"])

            logger.info(
                f"Keşfedilen Aktif {QUOTE_ASSET} Spot çifti sayısı: {len(discovered_pairs)}"
            )
            return {"USDT": sorted(discovered_pairs), QUOTE_ASSET: sorted(discovered_pairs), "TRY": []}

        except Exception as e:
            logger.error(f"Spot parite keşif hatası: {e}")
            return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

    def filter_by_volume(self, pairs: list) -> list:
        """Minimum 24s hacim filtresini uygular."""
        if MIN_VOLUME_USDT <= 0:
            return pairs

        try:
            tickers_list = self._send_public_request("/api/v3/ticker/24hr", timeout=15)
            if not tickers_list:
                return pairs
            tickers = {t["symbol"]: t for t in tickers_list}

            filtered = []
            for symbol in pairs:
                ticker = tickers.get(symbol)
                if not ticker:
                    continue
                vol_usdt = float(ticker.get("quoteVolume", 0))
                if vol_usdt >= MIN_VOLUME_USDT:
                    filtered.append(symbol)

            logger.info(
                f"Hacim filtresi sonrası: {len(filtered)}/{len(pairs)} parite "
                f"(Eşik: {MIN_VOLUME_USDT:,} USDT)"
            )
            return filtered

        except Exception as e:
            logger.error(f"Spot hacim filtresi hatası: {e}")
            return pairs

    # ==================== SPOT MUM VERİSİ (OHLCV) ====================

    def get_klines(
        self, symbol: str, interval: str = None, limit: int = None
    ) -> Optional[pd.DataFrame]:
        """
        Spot mum (OHLCV) verisini DataFrame olarak döndürür.
        Kolonlar: open, high, low, close, volume, quote_volume
        """
        interval = interval or KLINE_INTERVAL
        limit = limit or KLINE_LIMIT

        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            data = self._send_public_request("/api/v3/klines", params=params, timeout=15)

            if not data:
                return None

            df = pd.DataFrame(
                data,
                columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades",
                    "taker_buy_vol", "taker_buy_quote_vol", "ignore",
                ],
            )

            for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df.drop(
                columns=["ignore", "close_time", "trades",
                         "taker_buy_vol", "taker_buy_quote_vol"],
                inplace=True,
            )
            df.set_index("open_time", inplace=True)
            return df

        except Exception as e:
            logger.warning(f"Spot {symbol} mum verisi hatası: {e}")
            return None

    # ==================== ANLIK FİYAT ====================

    def get_price(self, symbol: str) -> Optional[float]:
        """Spot anlık fiyatı döner."""
        try:
            data = self._send_public_request("/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
            if not data:
                return None
            return float(data["price"])
        except Exception:
            return None

    def get_ticker_24h(self, symbol: str) -> Optional[dict]:
        """24 saatlik Spot ticker bilgisi."""
        try:
            data = self._send_public_request("/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=10)
            return data
        except Exception:
            return None

    # ==================== SPOT HESAP BAKİYESİ ====================

    def get_available_balance(self, asset: str = QUOTE_ASSET) -> float:
        """
        Binance.TR Spot cüzdanındaki kullanılabilir bakiyeyi döner.
        """
        data = self._send_signed_request("GET", "/open/v1/account/spot")
        if data:
            # Binance.TR response wrapper parses to {"code": 0, "msg": "Success", "data": {"accountAssets": [...]}}
            inner_data = data.get("data") if isinstance(data.get("data"), dict) else data
            balances = (inner_data.get("accountAssets") or inner_data.get("balances")) if isinstance(inner_data, dict) else None
            if balances:
                for a in balances:
                    if a.get("asset") == asset:
                        return float(a.get("free", 0.0))
        return 0.0


    def get_all_positions(self) -> list:
        """Açık Spot işlemlerini döner (lokal MongoDB'den)."""
        try:
            client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
            db = client["trade_bot"]
            return list(db["positions"].find({"status": "OPEN"}))
        except Exception:
            return []

    def _format_tr_symbol(self, symbol: str) -> str:
        """Sinyal veya genel sembol adını Binance.TR formatına (örn. STRAX_TRY) dönüştürür."""
        sym = symbol.upper()
        if "_" in sym:
            return sym
        if sym.endswith("TRY"):
            return sym[:-3] + "_TRY"
        if sym.endswith("USDT"):
            return sym[:-4] + "_USDT"
        return sym

    # ==================== SEMBOL FİLTRE YÖNETİMİ ====================

    def _load_symbol_filters(self):
        """Tüm Binance.TR sembol filtrelerini yükler (stepSize, tickSize, minNotional)."""
        if self._filters_loaded:
            return
        try:
            resp = self.session.get("https://www.binance.tr/open/v1/common/symbols", timeout=15)
            data = resp.json()
            symbols = data.get("data", {}).get("list", [])
            for s in symbols:
                sym = s.get("symbol", "")
                filters = {}
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        filters["stepSize"] = float(f.get("stepSize", "1"))
                        filters["minQty"] = float(f.get("minQty", "0.001"))
                    elif f.get("filterType") == "PRICE_FILTER":
                        filters["tickSize"] = float(f.get("tickSize", "0.01"))
                    elif f.get("filterType") == "NOTIONAL":
                        filters["minNotional"] = float(f.get("minNotional", "10"))
                if filters:
                    self._symbol_filters[sym] = filters
            self._filters_loaded = True
            logger.info(f"✅ {len(self._symbol_filters)} sembol filtresi yüklendi.")
        except Exception as e:
            logger.warning(f"⚠️ Sembol filtreleri yüklenemedi: {e}")

    def _get_symbol_filters(self, tr_symbol: str) -> dict:
        """Belirli bir sembol için filtre bilgilerini döndürür."""
        if not self._filters_loaded:
            self._load_symbol_filters()
        return self._symbol_filters.get(tr_symbol, {})

    def _format_quantity(self, quantity: float, tr_symbol: str) -> str:
        """Miktar değerini sembolün stepSize'ına göre formatlar."""
        filters = self._get_symbol_filters(tr_symbol)
        step_size = filters.get("stepSize", 0.001)
        min_qty = filters.get("minQty", 0.001)

        # stepSize'a göre aşağı yuvarla
        if step_size >= 1:
            formatted_qty = math.floor(quantity / step_size) * int(step_size)
            return str(int(formatted_qty))
        else:
            precision = max(0, int(round(-math.log10(step_size))))
            formatted_qty = math.floor(quantity / step_size) * step_size
            formatted_qty = max(formatted_qty, min_qty)
            return f"{formatted_qty:.{precision}f}"

    def _format_price(self, price: float, tr_symbol: str) -> str:
        """Fiyat değerini sembolün tickSize'ına göre formatlar."""
        filters = self._get_symbol_filters(tr_symbol)
        tick_size = filters.get("tickSize", 0.01)

        if tick_size >= 1:
            formatted_price = math.floor(price / tick_size) * int(tick_size)
            return str(int(formatted_price))
        else:
            precision = max(0, int(round(-math.log10(tick_size))))
            formatted_price = math.floor(price / tick_size) * tick_size
            return f"{formatted_price:.{precision}f}"

    # ==================== SPOT EMİR MOTORU ====================

    def create_futures_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Binance.TR Spot üzerinde alım veya satım emri açar.
        """
        endpoint = "/open/v1/orders"
        
        tr_symbol = self._format_tr_symbol(symbol)
        side_val = 0 if side.upper() == "BUY" else 1
        type_val = 1 if order_type.upper() == "LIMIT" else 2
        
        # Dinamik miktar ve fiyat formatlama (stepSize/tickSize uyumlu)
        qty_str = self._format_quantity(quantity, tr_symbol)
        
        params = {
            "symbol": tr_symbol,
            "side": str(side_val),
            "type": str(type_val),
            "quantity": qty_str,
        }
        if price is not None:
            params["price"] = self._format_price(price, tr_symbol)
            
        logger.info(
            f"Spot Emir -> {tr_symbol} | Side: {side} ({side_val}) | Type: {order_type} ({type_val}) | Miktar: {qty_str}" + (f" | Fiyat: {params['price']}" if price else "")
        )
        return self._send_signed_request("POST", endpoint, params)

    def cancel_futures_order(self, symbol: str, order_id: int) -> Optional[dict]:
        """Açık bir Spot emrini iptal eder."""
        tr_symbol = self._format_tr_symbol(symbol)
        params = {
            "symbol": tr_symbol,
            "orderId": str(order_id)
        }
        logger.info(f"Spot Emir İptal -> {tr_symbol} | OrderId: {order_id}")
        return self._send_signed_request("POST", "/open/v1/orders/cancel", params)

    def get_futures_order_status(self, symbol: str, order_id: int) -> Optional[dict]:
        """Bir Spot emrinin durumunu sorgular."""
        tr_symbol = self._format_tr_symbol(symbol)
        params = {
            "symbol": tr_symbol,
            "orderId": str(order_id)
        }
        return self._send_signed_request("GET", "/open/v1/orders", params)
