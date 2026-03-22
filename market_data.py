# ============================================================================
# market_data.py - Piyasa Verisi Çekici
# ============================================================================
# BinanceTR'den parite listesi ve mum verisi (OHLCV) çeker.
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
    MANUAL_TRY_PAIRS,
    MANUAL_USDT_PAIRS,
    MIN_VOLUME_USDT,
    KLINE_INTERVAL,
    KLINE_LIMIT,
)

logger = logging.getLogger("MarketData")


class MarketData:
    """BinanceTR piyasa verisi istemcisi."""

    def __init__(self):
        self.base_url = BINANCE_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": BINANCE_API_KEY})

        # Connection pool boyutunu paralel taramaya uygun ayarla
        # 5 pair × 5 TF = 25 eşzamanlı bağlantı olabilir
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=30,
            pool_maxsize=30,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._symbol_cache = {}
        self._usdt_try_rate = None
        self._rate_ts = 0

    # ==================== PARİTE KEŞF ====================

    def get_all_pairs(self) -> dict:
        """
        TRY ve USDT paritelerini getirir.
        Returns: {"TRY": ["BTCTRY", ...], "USDT": ["BTCUSDT", ...]}
        """
        if PAIR_MODE == "manual":
            return {"TRY": MANUAL_TRY_PAIRS, "USDT": MANUAL_USDT_PAIRS}

        try:
            url = f"{self.base_url}/api/v3/exchangeInfo"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            try_pairs = []
            usdt_pairs = []

            for s in data.get("symbols", []):
                if s.get("status") != "TRADING":
                    continue
                symbol = s["symbol"]
                if symbol.endswith("TRY"):
                    try_pairs.append(symbol)
                elif symbol.endswith("USDT"):
                    usdt_pairs.append(symbol)

            logger.info(f"Keşfedilen pariteler: {len(try_pairs)} TRY, {len(usdt_pairs)} USDT")
            return {"TRY": sorted(try_pairs), "USDT": sorted(usdt_pairs)}

        except Exception as e:
            logger.error(f"Parite keşfetme hatası: {e}")
            return {"TRY": MANUAL_TRY_PAIRS, "USDT": MANUAL_USDT_PAIRS}

    def filter_by_volume(self, pairs: list) -> list:
        """Minimum hacim filtresini uygular."""
        if MIN_VOLUME_USDT <= 0:
            return pairs

        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            tickers = {t["symbol"]: t for t in resp.json()}

            usdt_try = self._get_usdt_try_rate()
            filtered = []

            for symbol in pairs:
                ticker = tickers.get(symbol)
                if not ticker:
                    continue

                vol_quote = float(ticker.get("quoteVolume", 0))

                # TRY çiftleri için USDT'ye çevir
                if symbol.endswith("TRY") and usdt_try > 0:
                    vol_usdt = vol_quote / usdt_try
                else:
                    vol_usdt = vol_quote

                if vol_usdt >= MIN_VOLUME_USDT:
                    filtered.append(symbol)

            logger.info(f"Hacim filtresi sonrası: {len(filtered)}/{len(pairs)} parite")
            return filtered

        except Exception as e:
            logger.error(f"Hacim filtresi hatası: {e}")
            return pairs

    def _get_usdt_try_rate(self) -> float:
        """USDT/TRY kurunu getirir (cache'li)."""
        now = time.time()
        if self._usdt_try_rate and (now - self._rate_ts) < 300:
            return self._usdt_try_rate
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            resp = self.session.get(url, params={"symbol": "USDTTRY"}, timeout=10)
            resp.raise_for_status()
            self._usdt_try_rate = float(resp.json()["price"])
            self._rate_ts = now
            return self._usdt_try_rate
        except Exception:
            return self._usdt_try_rate or 35.0

    # ==================== MUM VERİSİ ====================

    def get_klines(self, symbol: str, interval: str = None, limit: int = None) -> Optional[pd.DataFrame]:
        """
        Mum (candlestick) verisini DataFrame olarak döndürür.

        Kolonlar: open, high, low, close, volume, close_time,
                  quote_volume, trades, taker_buy_vol, taker_buy_quote_vol
        """
        interval = interval or KLINE_INTERVAL
        limit = limit or KLINE_LIMIT

        try:
            url = f"{self.base_url}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return None

            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_vol", "taker_buy_quote_vol", "ignore",
            ])

            # Tip dönüşümleri
            for col in ["open", "high", "low", "close", "volume", "quote_volume",
                        "taker_buy_vol", "taker_buy_quote_vol"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df["trades"] = df["trades"].astype(int)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
            df.drop(columns=["ignore"], inplace=True)
            df.set_index("open_time", inplace=True)

            return df

        except Exception as e:
            logger.warning(f"{symbol} mum verisi hatası: {e}")
            return None

    # ==================== ANLlK FİYAT ====================

    def get_price(self, symbol: str) -> Optional[float]:
        """Anlık fiyat."""
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            resp = self.session.get(url, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception:
            return None

    def get_ticker_24h(self, symbol: str) -> Optional[dict]:
        """24 saatlik ticker bilgisi."""
        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            resp = self.session.get(url, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def get_all_tickers(self) -> dict:
        """Tüm fiyatları tek seferde çeker."""
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return {t["symbol"]: float(t["price"]) for t in resp.json()}
        except Exception as e:
            logger.error(f"Tüm fiyatlar çekilemedi: {e}")
            return {}
