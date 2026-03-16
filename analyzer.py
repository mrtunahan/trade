# ============================================================================
# analyzer.py - Teknik Analiz Motoru
# ============================================================================
# Mum verisinden indikatörler hesaplar ve kriter kontrolü yapar.
# Yeni kriterler eklemek için analyze() ve _check_* fonksiyonlarını
# genişletin.
# ============================================================================

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import CRITERIA, MIN_CRITERIA_MET, MIN_SIGNAL_STRENGTH_PCT

logger = logging.getLogger("Analyzer")


def _safe_float(series, index=-1, default=float("nan")) -> float:
    """Series'den güvenli float çıkarır, NaN ise default döndürür."""
    try:
        val = float(series.iloc[index])
        return val if not math.isnan(val) else default
    except (IndexError, TypeError, ValueError):
        return default


def _calc_ma(series: pd.Series, period: int, ma_type: str = "EMA") -> pd.Series:
    """Farklı hareketli ortalama tiplerini hesaplar."""
    ma_type = ma_type.upper()
    if ma_type == "SMA":
        return series.rolling(period).mean()
    elif ma_type == "EMA":
        return series.ewm(span=period, adjust=False).mean()
    elif ma_type == "DEMA":
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return 2 * ema1 - ema2
    elif ma_type == "TEMA":
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        return 3 * ema1 - 3 * ema2 + ema3
    elif ma_type == "WMA":
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True
        )
    elif ma_type == "HMA":
        # Hull Moving Average = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
        half_p = max(period // 2, 1)
        sqrt_p = max(int(np.sqrt(period)), 1)
        wma_half = _calc_ma(series, half_p, "WMA")
        wma_full = _calc_ma(series, period, "WMA")
        return _calc_ma(2 * wma_half - wma_full, sqrt_p, "WMA")
    else:
        return series.ewm(span=period, adjust=False).mean()


@dataclass
class Signal:
    """Bir sinyal sonucu."""
    symbol: str
    signal_type: str          # "buy", "sell", "info"
    strength: int             # Ağırlıklı puan toplamı
    total_criteria: int       # Toplam ağırlık puanı
    price: float
    criteria_met: list        # Sağlanan kriterlerin isimleri
    criteria_details: dict    # Her kriterin detay bilgisi
    indicators: dict          # Hesaplanan indikatör değerleri
    strength_pct: float = 0.0  # Ağırlıklı güç yüzdesi (0.0 - 1.0)


class TechnicalAnalyzer:
    """Teknik analiz ve sinyal üretici."""

    def __init__(self, criteria: dict = None):
        self.criteria = criteria or CRITERIA
        self.min_criteria = MIN_CRITERIA_MET

    def analyze(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Bir parite için tüm kriterleri çalıştırır.
        Returns: Signal nesnesi veya None (sinyal yoksa)
        """
        if df is None or len(df) < 50:
            return None

        try:
            # İndikatörleri hesapla
            indicators = self._calculate_indicators(df)

            # Her kriteri kontrol et
            criteria_met = []
            criteria_details = {}
            total_weight = 0
            earned_weight = 0

            checks = {
                "ema_cross":          self._check_ema_cross,
                "rsi":                self._check_rsi,
                "macd":               self._check_macd,
                "bollinger":          self._check_bollinger,
                "volume_spike":       self._check_volume_spike,
                "trend_filter":       self._check_trend_filter,
                "support_resistance": self._check_support_resistance,
                "stoch_rsi":          self._check_stoch_rsi,
                "occ":                self._check_occ,
            }

            for name, check_fn in checks.items():
                cfg = self.criteria.get(name, {})
                if not cfg.get("enabled", False):
                    continue

                weight = cfg.get("weight", 1)
                total_weight += weight
                result = check_fn(df, indicators, cfg)

                if result["met"]:
                    criteria_met.append(name)
                    earned_weight += weight
                criteria_details[name] = result

            # Zorunlu kriter kontrolü: OCC (veya required=True olan herhangi bir kriter)
            for name, cfg in self.criteria.items():
                if cfg.get("enabled", False) and cfg.get("required", False):
                    if name not in criteria_met:
                        # Zorunlu kriter sağlanmadıysa sinyal üretme
                        return None

            # Ağırlıklı güç yüzdesi
            strength_pct = earned_weight / total_weight if total_weight > 0 else 0.0

            # Minimum kriter sayısı ve güç eşiği kontrolü
            if len(criteria_met) >= self.min_criteria and total_weight > 0:
                return Signal(
                    symbol=symbol,
                    signal_type="buy",
                    strength=earned_weight,
                    total_criteria=total_weight,
                    price=float(df["close"].iloc[-1]),
                    criteria_met=criteria_met,
                    criteria_details=criteria_details,
                    indicators=indicators,
                    strength_pct=strength_pct,
                )

            return None

        except Exception as e:
            logger.error(f"{symbol} analiz hatası: {e}", exc_info=True)
            return None

    # ==================== İNDİKATÖR HESAPLAMALARI ====================

    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """Tüm indikatörleri hesaplar ve sözlük olarak döndürür."""
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        ind = {}

        # EMA'lar
        for p in [9, 21, 50, 100, 200]:
            ind[f"ema_{p}"] = close.ewm(span=p, adjust=False).mean()

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        ind["rsi"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        ind["macd_line"] = ema12 - ema26
        ind["macd_signal"] = ind["macd_line"].ewm(span=9, adjust=False).mean()
        ind["macd_hist"] = ind["macd_line"] - ind["macd_signal"]

        # Bollinger Bands
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        ind["bb_upper"] = sma20 + 2 * std20
        ind["bb_middle"] = sma20
        ind["bb_lower"] = sma20 - 2 * std20
        ind["bb_pct"] = (close - ind["bb_lower"]) / (ind["bb_upper"] - ind["bb_lower"])

        # Volume MA
        ind["vol_ma"] = volume.rolling(20).mean()
        ind["vol_ratio"] = volume / ind["vol_ma"].replace(0, np.nan)

        # Stochastic RSI
        rsi = ind["rsi"]
        rsi_min = rsi.rolling(14).min()
        rsi_max = rsi.rolling(14).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
        ind["stoch_rsi_k"] = stoch_rsi.rolling(3).mean() * 100
        ind["stoch_rsi_d"] = ind["stoch_rsi_k"].rolling(3).mean()

        # Destek / Direnç seviyeleri
        ind["support"] = low.rolling(50).min()
        ind["resistance"] = high.rolling(50).max()

        # 24 saatlik değişim
        if len(close) >= 24:
            ind["change_24h"] = ((close.iloc[-1] - close.iloc[-24]) / close.iloc[-24]) * 100
        else:
            ind["change_24h"] = 0.0

        # OCC (Open Close Cross) - Non Repaint
        occ_cfg = self.criteria.get("occ", {})
        if occ_cfg.get("enabled", False):
            occ_period = occ_cfg.get("period", 5)
            occ_ma_type = occ_cfg.get("ma_type", "EMA")

            # Close MA ve Open MA hesapla
            ind["occ_close_ma"] = _calc_ma(close, occ_period, occ_ma_type)
            ind["occ_open_ma"] = _calc_ma(df["open"], occ_period, occ_ma_type)

            # Difference Factor (Close MA - Open MA)
            ind["occ_diff"] = ind["occ_close_ma"] - ind["occ_open_ma"]

            # Cross Strength: farkın yüzdesel büyüklüğü
            mid = (ind["occ_close_ma"] + ind["occ_open_ma"]) / 2
            ind["occ_strength"] = (ind["occ_diff"] / mid.replace(0, np.nan)) * 100

        # Son değerleri de kaydet
        ind["last_close"] = float(close.iloc[-1])
        ind["last_volume"] = float(volume.iloc[-1])

        return ind

    # ==================== KRİTER KONTROL FONKSİYONLARI ====================

    def _check_ema_cross(self, df, ind, cfg) -> dict:
        """EMA Crossover kontrolü."""
        fast_key = f"ema_{cfg['fast']}"
        slow_key = f"ema_{cfg['slow']}"

        fast = ind.get(fast_key, df["close"].ewm(span=cfg["fast"], adjust=False).mean())
        slow = ind.get(slow_key, df["close"].ewm(span=cfg["slow"], adjust=False).mean())

        fast_now = _safe_float(fast, -1)
        slow_now = _safe_float(slow, -1)
        fast_prev = _safe_float(fast, -2)
        slow_prev = _safe_float(slow, -2)

        if math.isnan(fast_now) or math.isnan(slow_now) or math.isnan(fast_prev) or math.isnan(slow_prev):
            return {"met": False, "detail": "EMA verisi yetersiz", "description": "Hesaplanamadı"}

        # Son mumda crossover oldu mu?
        cross_up = fast_now > slow_now and fast_prev <= slow_prev

        # Veya yakın zamanda (son 3 mum) crossover
        recent_cross = False
        for i in range(-3, 0):
            f_cur = _safe_float(fast, i)
            s_cur = _safe_float(slow, i)
            f_prev = _safe_float(fast, i - 1)
            s_prev = _safe_float(slow, i - 1)
            if math.isnan(f_cur) or math.isnan(s_cur) or math.isnan(f_prev) or math.isnan(s_prev):
                continue
            if f_cur > s_cur and f_prev <= s_prev:
                recent_cross = True
                break

        met = cross_up or recent_cross

        return {
            "met": met,
            "detail": f"EMA{cfg['fast']}={fast_now:.4f}, EMA{cfg['slow']}={slow_now:.4f}",
            "description": "EMA yukarı kesişim" if met else "Kesişim yok",
        }

    def _check_rsi(self, df, ind, cfg) -> dict:
        """RSI kontrolü — genişletilmiş alım bölgesi."""
        rsi_val = _safe_float(ind["rsi"], -1)
        prev_rsi = _safe_float(ind["rsi"], -2, default=rsi_val)

        if math.isnan(rsi_val):
            return {"met": False, "detail": "RSI verisi yetersiz", "description": "Hesaplanamadı"}

        oversold = cfg["oversold"]                    # 30
        oversold_zone = cfg.get("oversold_zone", 40)  # 30-40 arası potansiyel bölge

        # Aşırı satım bölgesinden çıkış (< 30 → > 30)
        oversold_bounce = prev_rsi <= oversold and rsi_val > oversold
        # Hâlâ aşırı satım bölgesinde (< 30)
        in_oversold = rsi_val <= oversold
        # Potansiyel alım bölgesi (30-40 arası ve yükseliyor)
        in_buy_zone = oversold < rsi_val <= oversold_zone and rsi_val > prev_rsi

        met = oversold_bounce or in_oversold or in_buy_zone

        if rsi_val <= oversold:
            zone = "Aşırı satım"
        elif rsi_val <= oversold_zone:
            zone = "Alım bölgesi"
        elif rsi_val < cfg["overbought"]:
            zone = "Nötr"
        else:
            zone = "Aşırı alım"

        desc = f"RSI {zone}"
        if in_buy_zone:
            desc = f"RSI Alım bölgesi (yükseliyor)"

        return {
            "met": met,
            "detail": f"RSI={rsi_val:.1f}",
            "description": desc,
        }

    def _check_macd(self, df, ind, cfg) -> dict:
        """MACD kontrolü."""
        macd_line = _safe_float(ind["macd_line"], -1)
        macd_signal = _safe_float(ind["macd_signal"], -1)
        macd_hist = _safe_float(ind["macd_hist"], -1)
        prev_hist = _safe_float(ind["macd_hist"], -2, default=0.0)
        prev_macd = _safe_float(ind["macd_line"], -2)
        prev_signal = _safe_float(ind["macd_signal"], -2)

        if math.isnan(macd_line) or math.isnan(macd_signal) or math.isnan(macd_hist):
            return {"met": False, "detail": "MACD verisi yetersiz", "description": "Hesaplanamadı"}

        # MACD sinyal çizgisini yukarı kesiyor veya histogram pozitife dönüyor
        cross_up = (macd_line > macd_signal and
                    not math.isnan(prev_macd) and not math.isnan(prev_signal) and
                    prev_macd <= prev_signal)
        hist_turn = prev_hist < 0 and macd_hist > 0

        met = cross_up or hist_turn

        return {
            "met": met,
            "detail": f"MACD={macd_line:.4f}, Signal={macd_signal:.4f}, Hist={macd_hist:.4f}",
            "description": "MACD yukarı kesişim" if cross_up else ("Histogram pozitife döndü" if hist_turn else "Sinyal yok"),
        }

    def _check_bollinger(self, df, ind, cfg) -> dict:
        """Bollinger Bands kontrolü."""
        close = float(df["close"].iloc[-1])
        bb_lower = _safe_float(ind["bb_lower"], -1)
        bb_upper = _safe_float(ind["bb_upper"], -1)
        bb_pct = _safe_float(ind["bb_pct"], -1)

        if math.isnan(bb_lower) or math.isnan(bb_upper) or math.isnan(bb_pct):
            return {"met": False, "detail": "Bollinger verisi yetersiz", "description": "Hesaplanamadı"}

        # Alt banda dokunma veya altına inme
        met = close <= bb_lower * 1.005  # %0.5 tolerans

        return {
            "met": met,
            "detail": f"BB%={bb_pct:.2f}, Alt={bb_lower:.4f}, Üst={bb_upper:.4f}",
            "description": "Alt banda temas" if met else "Band içinde",
        }

    def _check_volume_spike(self, df, ind, cfg) -> dict:
        """Hacim artışı kontrolü."""
        vol_ratio = _safe_float(ind["vol_ratio"], -1)

        if math.isnan(vol_ratio):
            return {"met": False, "detail": "Hacim verisi yetersiz", "description": "Hesaplanamadı"}

        met = vol_ratio >= cfg["multiplier"]

        return {
            "met": met,
            "detail": f"Hacim oranı={vol_ratio:.1f}x (eşik: {cfg['multiplier']}x)",
            "description": f"Hacim patlaması ({vol_ratio:.1f}x)" if met else "Normal hacim",
        }

    def _check_trend_filter(self, df, ind, cfg) -> dict:
        """Trend yönü filtresi (200 EMA)."""
        close = float(df["close"].iloc[-1])
        ema_key = f"ema_{cfg['ema_period']}"
        ema_series = ind.get(ema_key, df["close"].ewm(span=cfg["ema_period"], adjust=False).mean())
        ema_val = _safe_float(ema_series, -1)

        if math.isnan(ema_val) or ema_val == 0:
            return {"met": False, "detail": "EMA verisi yetersiz", "description": "Hesaplanamadı"}

        if cfg["mode"] == "above":
            met = close > ema_val
        elif cfg["mode"] == "below":
            met = close < ema_val
        else:
            met = True  # "both" = her zaman geçer

        pct_diff = ((close - ema_val) / ema_val) * 100

        return {
            "met": met,
            "detail": f"Fiyat={'üstünde' if close > ema_val else 'altında'} EMA{cfg['ema_period']} ({pct_diff:+.1f}%)",
            "description": f"Trend {'yükseliş' if close > ema_val else 'düşüş'}",
        }

    def _check_support_resistance(self, df, ind, cfg) -> dict:
        """Destek seviyesine yakınlık kontrolü."""
        close = float(df["close"].iloc[-1])
        support = _safe_float(ind["support"], -1)

        if math.isnan(support) or support <= 0:
            return {"met": False, "detail": "Destek verisi yetersiz", "description": "Hesaplanamadı"}

        proximity = abs(close - support) / support * 100

        met = proximity <= cfg["proximity_pct"]

        return {
            "met": met,
            "detail": f"Destek={support:.4f}, Mesafe=%{proximity:.2f}",
            "description": f"Desteğe yakın (%{proximity:.2f})" if met else "Destekten uzak",
        }

    def _check_stoch_rsi(self, df, ind, cfg) -> dict:
        """Stochastic RSI kontrolü."""
        k_val = _safe_float(ind["stoch_rsi_k"], -1)
        d_val = _safe_float(ind["stoch_rsi_d"], -1)
        prev_k = _safe_float(ind["stoch_rsi_k"], -2)
        prev_d = _safe_float(ind["stoch_rsi_d"], -2)

        if math.isnan(k_val) or math.isnan(d_val) or math.isnan(prev_k) or math.isnan(prev_d):
            return {"met": False, "detail": "StochRSI verisi yetersiz", "description": "Hesaplanamadı"}

        # K çizgisi D'yi yukarı kesiyor ve aşırı satım bölgesinde
        cross_up = k_val > d_val and prev_k <= prev_d
        in_oversold = k_val <= cfg["oversold"] or d_val <= cfg["oversold"]

        met = cross_up and in_oversold

        return {
            "met": met,
            "detail": f"StochRSI K={k_val:.1f}, D={d_val:.1f}",
            "description": "Aşırı satımda yukarı kesişim" if met else "Sinyal yok",
        }

    def _check_occ(self, df, ind, cfg) -> dict:
        """
        OCC (Open Close Cross) Non-Repaint kontrolü.
        Close MA ve Open MA kesişimine dayalı sinyal üretir.
        Non-repaint: Sadece kapanmış (onaylanmış) mumlara bakılır.
        """
        close_ma = ind.get("occ_close_ma")
        open_ma = ind.get("occ_open_ma")
        occ_strength = ind.get("occ_strength")

        if close_ma is None or open_ma is None:
            return {"met": False, "detail": "OCC verisi yok", "description": "Hesaplanamadı"}

        # Non-Repaint: Son kapanmış mumu kullan (iloc[-2]), mevcut mumu değil
        # iloc[-1] henüz kapanmamış olabilir, bu yüzden [-2] kullanıyoruz
        c_now = _safe_float(close_ma, -2)
        o_now = _safe_float(open_ma, -2)
        c_prev = _safe_float(close_ma, -3)
        o_prev = _safe_float(open_ma, -3)

        if math.isnan(c_now) or math.isnan(o_now) or math.isnan(c_prev) or math.isnan(o_prev):
            return {"met": False, "detail": "OCC verisi yetersiz", "description": "Hesaplanamadı"}

        # Yukarı kesişim: Close MA, Open MA'yı yukarı kesiyor (Long sinyali)
        cross_up = c_now > o_now and c_prev <= o_prev

        # Yakın zamanda kesişim (son 3 kapanmış mum)
        recent_cross = False
        if not cross_up:
            for i in range(-4, -1):
                c_i = _safe_float(close_ma, i)
                o_i = _safe_float(open_ma, i)
                c_i_prev = _safe_float(close_ma, i - 1)
                o_i_prev = _safe_float(open_ma, i - 1)
                if math.isnan(c_i) or math.isnan(o_i) or math.isnan(c_i_prev) or math.isnan(o_i_prev):
                    continue
                if c_i > o_i and c_i_prev <= o_i_prev:
                    recent_cross = True
                    break

        met = cross_up or recent_cross

        # Opsiyonel: Minimum cross strength filtresi
        min_strength = cfg.get("min_strength", 0.0)
        strength_val = _safe_float(occ_strength, -2, default=0.0) if occ_strength is not None else 0.0
        if met and abs(strength_val) < min_strength:
            met = False

        # Mevcut durum bilgisi
        if c_now > o_now:
            trend = "Yükseliş (Close MA > Open MA)"
        else:
            trend = "Düşüş (Close MA < Open MA)"

        return {
            "met": met,
            "detail": f"CloseMA={c_now:.4f}, OpenMA={o_now:.4f}, Güç={strength_val:+.3f}%",
            "description": f"OCC Long kesişim — {trend}" if met else f"OCC Kesişim yok — {trend}",
        }
