# ============================================================================
# market_data.py - Binance Global Futures (USDT-M Perpetual) Veri Çekici
# ============================================================================
import time
import hmac
import hashlib
import logging
from typing import Optional
from urllib.parse import urlencode

import requests
import pandas as pd

from config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_BASE_URL,
    PAIR_MODE,
    MANUAL_USDT_PAIRS,
    MIN_VOLUME_USDT,
    KLINE_INTERVAL,
    KLINE_LIMIT,
)

logger = logging.getLogger("MarketData")


class MarketData:
    """Binance Global Vadeli İşlemler (USDT-M Perpetual Futures) istemcisi."""

    def __init__(self):
        self.base_url = BINANCE_BASE_URL
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
        """Binance Futures API imzalı istekleri için HMAC-SHA256 üretir."""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _send_signed_request(
        self, method: str, endpoint: str, params: dict = None
    ) -> Optional[dict]:
        """İmzalı özel API isteklerini Binance Futures'a iletir."""
        if params is None:
            params = {}

        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = self._generate_signature(query_string)

        url = f"{self.base_url}{endpoint}?{query_string}&signature={signature}"

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, timeout=15)
            elif method.upper() == "POST":
                resp = self.session.post(url, timeout=15)
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, timeout=15)
            else:
                return None

            if resp.status_code != 200:
                logger.error(
                    f"Futures İmzalı İstek Hatası ({endpoint}): {resp.text}"
                )
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"Futures Bağlantı Hatası ({endpoint}): {e}")
            return None

    # ==================== PERPETUAL PARİTE KEŞFİ ====================

    def get_all_pairs(self) -> dict:
        """
        Aktif USDT Perpetual sözleşmelerini getirir.
        Returns: {"USDT": ["BTCUSDT", ...], "TRY": []}
        """
        if PAIR_MODE == "manual":
            return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

        try:
            data = self._send_public_request("/fapi/v1/exchangeInfo", timeout=15)
            if not data:
                return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

            usdt_pairs = []
            for s in data.get("symbols", []):
                if (
                    s.get("status") == "TRADING"
                    and s.get("quoteAsset") == "USDT"
                    and s.get("contractType") == "PERPETUAL"
                ):
                    usdt_pairs.append(s["symbol"])

            logger.info(
                f"Keşfedilen Aktif USDT Perpetual sözleşme sayısı: {len(usdt_pairs)}"
            )
            return {"USDT": sorted(usdt_pairs), "TRY": []}

        except Exception as e:
            logger.error(f"Futures parite keşif hatası: {e}")
            return {"USDT": MANUAL_USDT_PAIRS, "TRY": []}

    def filter_by_volume(self, pairs: list) -> list:
        """Minimum 24s hacim filtresini uygular (Futures quoteVolume USDT cinsindendir)."""
        if MIN_VOLUME_USDT <= 0:
            return pairs

        try:
            tickers_list = self._send_public_request("/fapi/v1/ticker/24hr", timeout=15)
            if not tickers_list:
                return pairs
            tickers = {t["symbol"]: t for t in tickers_list}

            filtered = []
            for symbol in pairs:
                ticker = tickers.get(symbol)
                if not ticker:
                    continue
                # Futures quoteVolume doğrudan USDT cinsindendir
                vol_usdt = float(ticker.get("quoteVolume", 0))
                if vol_usdt >= MIN_VOLUME_USDT:
                    filtered.append(symbol)

            logger.info(
                f"Hacim filtresi sonrası: {len(filtered)}/{len(pairs)} parite "
                f"(Eşik: {MIN_VOLUME_USDT:,} USDT)"
            )
            return filtered

        except Exception as e:
            logger.error(f"Futures hacim filtresi hatası: {e}")
            return pairs

    # ==================== FUTURES MUM VERİSİ (OHLCV) ====================

    def get_klines(
        self, symbol: str, interval: str = None, limit: int = None
    ) -> Optional[pd.DataFrame]:
        """
        Futures mum (OHLCV) verisini DataFrame olarak döndürür.
        Kolonlar: open, high, low, close, volume, quote_volume
        """
        interval = interval or KLINE_INTERVAL
        limit = limit or KLINE_LIMIT

        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            data = self._send_public_request("/fapi/v1/klines", params=params, timeout=15)

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
            logger.warning(f"Futures {symbol} mum verisi hatası: {e}")
            return None

    # ==================== ANLIK FİYAT ====================

    def get_price(self, symbol: str) -> Optional[float]:
        """Futures anlık fiyatı döner."""
        try:
            data = self._send_public_request("/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=10)
            if not data:
                return None
            return float(data["price"])
        except Exception:
            return None

    def get_ticker_24h(self, symbol: str) -> Optional[dict]:
        """24 saatlik Futures ticker bilgisi."""
        try:
            data = self._send_public_request("/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=10)
            return data
        except Exception:
            return None

    # ==================== VADELİ HESAP BAKİYESİ ====================

    def get_available_balance(self, asset: str = "USDT") -> float:
        """
        Futures cüzdanındaki kullanılabilir bakiyeyi döner.
        /fapi/v2/account endpoint'i kullanır.
        """
        data = self._send_signed_request("GET", "/fapi/v2/account")
        if data and "assets" in data:
            for a in data["assets"]:
                if a["asset"] == asset:
                    return float(a["availableBalance"])
        return 0.0

    def get_all_positions(self) -> list:
        """Açık Futures pozisyonlarını döner (positionAmt != 0 olanlar)."""
        data = self._send_signed_request("GET", "/fapi/v2/positionRisk")
        if not data:
            return []
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    # ==================== FUTURES EMİR MOTORU ====================

    def create_futures_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: float,
    ) -> Optional[dict]:
        """
        Binance Futures üzerinde Long veya Short yönlü emir açar.

        Args:
            symbol:        Parite (örn: "BTCUSDT")
            side:          "BUY" (Long aç / Short kapat) | "SELL" (Short aç / Long kapat)
            position_side: "LONG" veya "SHORT"
            order_type:    "MARKET" veya "LIMIT"
            quantity:      İşlem miktarı (kontrat bazı)
        """
        endpoint = "/fapi/v1/order"
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": position_side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.3f}",
        }
        logger.info(
            f"Futures Emir -> {symbol} | {side} {position_side} | "
            f"{order_type} | Miktar: {quantity}"
        )
        return self._send_signed_request("POST", endpoint, params)

    def cancel_futures_order(self, symbol: str, order_id: int) -> Optional[dict]:
        """Açık bir Futures emrini iptal eder."""
        params = {"symbol": symbol, "orderId": order_id}
        return self._send_signed_request("DELETE", "/fapi/v1/order", params)

    def get_futures_order_status(self, symbol: str, order_id: int) -> Optional[dict]:
        """Bir Futures emrinin durumunu (FILLED, NEW vb.) sorgular."""
        params = {"symbol": symbol, "orderId": order_id}
        return self._send_signed_request("GET", "/fapi/v1/order", params)
