# ============================================================================
# analyzer.py - Spot Pipeline Trend & Reversal Analyzer
# ============================================================================
import logging
import math
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from config import SPOT_PIPELINE

logger = logging.getLogger("Analyzer")


def _safe_float(series, index=-1, default=float("nan")) -> float:
    try:
        val = float(series.iloc[index])
        return val if not math.isnan(val) else default
    except (IndexError, TypeError, ValueError):
        return default


@dataclass
class OccTfStatus:
    """Tek bir gösterge puan durumu (Dashboard ve Telegram heatmap uyumluluğu için)."""
    timeframe: str
    label: str
    weight: int
    is_green: bool
    just_crossed: bool = False
    close_ma: float = 0.0
    open_ma: float = 0.0
    strength: float = 0.0


@dataclass
class SpotPipelineSignal:
    """Geriye dönük uyumlu ve premium 4-stage spot pipeline sinyal kartı."""
    symbol: str
    signal_type: str  # "buy", "info", "tf_change"
    price: float
    tf_statuses: list  # [OccTfStatus, ...] (Dashboard uyumluluğu için)
    total_score: int
    max_score: int
    trigger_tf: str
    trigger_crossed: bool
    segment_type: str  # "STRONG" veya "WEAK"
    
    rsi_value: float = float("nan")
    rsi_quality: str = "ok"
    adx_value: float = float("nan")
    adx_regime: str = "ranging"
    
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 6.0
    
    candlestick_pattern: str = ""  # Ekstra onay desenleri veya tetik açıklaması
    indicators: dict = field(default_factory=dict)

    @property
    def is_valid_entry(self) -> bool:
        # Sinyal zaten tetiklendiyse True döner
        return self.trigger_crossed and self.signal_type == "buy"

    @property
    def matched_pattern_name(self) -> str:
        return f"{self.segment_type} SEGMENT // {self.candlestick_pattern}"

    @property
    def signal_star_rating(self) -> dict:
        # Puanlama sistemine göre star rating (Dashboard & Telegram uyumluluğu)
        if self.segment_type == "STRONG":
            stars = "⭐⭐⭐" if self.total_score >= 7 else "⭐⭐"
            label = "Full Sniper" if self.total_score >= 7 else "Güçlü Trend"
            position_pct = 100 if self.total_score >= 7 else 75
        else:
            stars = "⭐⭐" if self.total_score >= 6 else "⭐"
            label = "Dip Avcısı" if self.total_score >= 6 else "Tepki Alımı"
            position_pct = 75 if self.total_score >= 6 else 50
            
        return {"stars": stars, "label": label, "position_pct": position_pct}

    @property
    def position_size_pct(self) -> float:
        return self.signal_star_rating["position_pct"] / 100.0

    @property
    def position_tier(self) -> str:
        return self.signal_star_rating["label"]


class SpotPipelineAnalyzer:
    """
    Spot Pipeline Trend ve Reversal Analiz Motoru.
    Görevi: Günlük göstergeleri puanlamak (Aşama 3) ve alt zaman dilimlerinde tetik kontrolü yapmak (Aşama 4).
    """

    def __init__(self):
        pass

    def calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        
        # Smoothed RS using RMA (Pine Script standard)
        avg_gain = gain.ewm(alpha=1.0/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0/period, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        atr = tr.ewm(alpha=1.0/period, adjust=False).mean()
        smooth_plus = plus_dm.ewm(alpha=1.0/period, adjust=False).mean()
        smooth_minus = minus_dm.ewm(alpha=1.0/period, adjust=False).mean()

        plus_di = (smooth_plus / atr.replace(0, np.nan)) * 100
        minus_di = (smooth_minus / atr.replace(0, np.nan)) * 100

        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        return dx.ewm(alpha=1.0/period, adjust=False).mean()

    def analyze_candidate(self, symbol: str, segment: str, daily_df: pd.DataFrame, 
                          lower_tfs_data: dict) -> Optional[SpotPipelineSignal]:
        """
        Her bir aday coin için Aşama 3 (Skorlama) ve Aşama 4 (Tetikleme) kontrolünü gerçekleştirir.
        
        Args:
            symbol: Coin sembolü (örn. "BTC_TRY")
            segment: "STRONG" (Güçlü 30) veya "WEAK" (Güçsüz 30)
            daily_df: Günlük mum verisi
            lower_tfs_data: Alt zaman dilimleri verisi {"5m": df, "15m": df, "1h": df}
        """
        if daily_df is None or len(daily_df) < 30:
            return None

        closes = daily_df["close"]
        volumes = daily_df["volume"]
        
        # ── GÜNLÜK GÖSTERGELER ──
        ema50 = closes.ewm(span=50, adjust=False).mean()
        ema200 = closes.ewm(span=200, adjust=False).mean()
        rsi = self.calculate_rsi(closes, 14)
        vol_ma = volumes.rolling(20).mean()

        # Son kapanmış günlük bar (-2)
        ema50_val = _safe_float(ema50, -2)
        ema200_val = _safe_float(ema200, -2)
        rsi_val = _safe_float(rsi, -2)
        rsi_prev = _safe_float(rsi, -3)
        vol_val = _safe_float(volumes, -2)
        vol_ma_val = _safe_float(vol_ma, -2)
        
        price = _safe_float(closes, -1)  # Canlı fiyat son bardır (-1)

        total_score = 0
        max_score = 7
        tf_statuses = []

        cfg = SPOT_PIPELINE["strong"] if segment == "STRONG" else SPOT_PIPELINE["weak"]
        sl_pct = cfg["base_sl_pct"]
        tp_pct = cfg["base_tp_pct"]

        # ── AŞAMA 3: SKORLAMA (Trend + Momentum Hibriti) ──
        if segment == "STRONG":
            # 1. EMA50 > EMA200 (+3 Puan)
            ema_ok = ema50_val > ema200_val
            if ema_ok:
                total_score += 3
            tf_statuses.append(OccTfStatus(timeframe="1d_ema", label="Daily EMA50 > EMA200", weight=3, is_green=ema_ok))

            # 2. RSI 55 - 70 (+2 Puan)
            rsi_ok = 55.0 <= rsi_val <= 70.0
            if rsi_ok:
                total_score += 2
            tf_statuses.append(OccTfStatus(timeframe="1d_rsi", label="Daily RSI (55-70)", weight=2, is_green=rsi_ok))

            # 3. Volume > 20MA * 1.5 (+2 Puan)
            vol_ok = False
            if not math.isnan(vol_val) and not math.isnan(vol_ma_val) and vol_ma_val > 0:
                vol_ok = vol_val > (vol_ma_val * 1.5)
            if vol_ok:
                total_score += 2
            tf_statuses.append(OccTfStatus(timeframe="1d_vol", label="Daily Vol > 1.5xMA", weight=2, is_green=vol_ok))

            score_threshold = SPOT_PIPELINE["strong"]["score_threshold"]
            
        else:  # WEAK segment
            # 1. EMA50 < EMA200 (+0 Puan)
            ema_ok = ema50_val < ema200_val
            tf_statuses.append(OccTfStatus(timeframe="1d_ema", label="Daily EMA50 < EMA200", weight=0, is_green=ema_ok))

            # 2. RSI < 30 veya RSI Dip Dönüş (+3 Puan)
            # RSI dip dönüşü: RSI 30 ile 45 arasında ve dünkünden daha yukarıda (kafayı kaldırmış)
            rsi_ok = rsi_val < 30.0 or (30.0 <= rsi_val <= 45.0 and rsi_val > rsi_prev)
            if rsi_ok:
                total_score += 3
            tf_statuses.append(OccTfStatus(timeframe="1d_rsi", label="Daily RSI Bottom/Up", weight=3, is_green=rsi_ok))

            # 3. Volume > 20MA * 2.0 (+4 Puan)
            vol_ok = False
            if not math.isnan(vol_val) and not math.isnan(vol_ma_val) and vol_ma_val > 0:
                vol_ok = vol_val > (vol_ma_val * 2.0)
            if vol_ok:
                total_score += 4
            tf_statuses.append(OccTfStatus(timeframe="1d_vol", label="Daily Vol > 2.0xMA", weight=4, is_green=vol_ok))

            score_threshold = SPOT_PIPELINE["weak"]["score_threshold"]

        # Skor yetersizse sinyali iptal et/atla
        if total_score < score_threshold:
            return SpotPipelineSignal(
                symbol=symbol, signal_type="info", price=price, tf_statuses=tf_statuses,
                total_score=total_score, max_score=max_score, trigger_tf="N/A", trigger_crossed=False,
                segment_type=segment, rsi_value=rsi_val, adx_value=float("nan"), stop_loss_pct=sl_pct, take_profit_pct=tp_pct
            )

        # ── AŞAMA 4: TETİK (Zaman Dilimi ve Giriş Stratejisi) ──
        trigger_crossed = False
        trigger_tf = "N/A"
        candlestick_pattern = ""

        if segment == "STRONG":
            # 5m veya 15m pullback hold veya golden cross kontrolü
            for tf in ["5m", "15m"]:
                df_lower = lower_tfs_data.get(tf)
                if df_lower is None or len(df_lower) < 55:
                    continue

                lows_lower = df_lower["low"]
                closes_lower = df_lower["close"]
                
                ema9_lower = closes_lower.ewm(span=9, adjust=False).mean()
                ema20_lower = closes_lower.ewm(span=20, adjust=False).mean()
                ema50_lower = closes_lower.ewm(span=50, adjust=False).mean()

                # Golden Cross check
                gc_ok = ema9_lower.iloc[-2] > ema20_lower.iloc[-2] and ema9_lower.iloc[-3] <= ema20_lower.iloc[-3]
                
                # Pullback checks (Low <= EMA, Close >= EMA)
                pb_ema20 = lows_lower.iloc[-2] <= ema20_lower.iloc[-2] and closes_lower.iloc[-2] >= ema20_lower.iloc[-2]
                pb_ema50 = lows_lower.iloc[-2] <= ema50_lower.iloc[-2] and closes_lower.iloc[-2] >= ema50_lower.iloc[-2]

                if gc_ok:
                    trigger_crossed = True
                    trigger_tf = tf
                    candlestick_pattern = "EMA9 > EMA20 Kesişimi (Golden Cross)"
                    break
                elif pb_ema20:
                    trigger_crossed = True
                    trigger_tf = tf
                    candlestick_pattern = "EMA20 Pullback (Geri Çekilip Tutunma)"
                    break
                elif pb_ema50:
                    trigger_crossed = True
                    trigger_tf = tf
                    candlestick_pattern = "EMA50 Pullback (Geri Çekilip Tutunma)"
                    break
        else:
            # 15m veya 1h RSI dip dönüşü veya golden cross kontrolü
            for tf in ["15m", "1h"]:
                df_lower = lower_tfs_data.get(tf)
                if df_lower is None or len(df_lower) < 30:
                    continue

                closes_lower = df_lower["close"]
                rsi_lower = self.calculate_rsi(closes_lower, 14)
                ema9_lower = closes_lower.ewm(span=9, adjust=False).mean()
                ema20_lower = closes_lower.ewm(span=20, adjust=False).mean()

                # RSI 30 yukarı kesim check (RSI[-2] > 30 ve RSI[-3] <= 30)
                rsi_cross = rsi_lower.iloc[-2] > 30.0 and rsi_lower.iloc[-3] <= 30.0
                
                # Golden Cross check
                gc_ok = ema9_lower.iloc[-2] > ema20_lower.iloc[-2] and ema9_lower.iloc[-3] <= ema20_lower.iloc[-3]

                if rsi_cross:
                    trigger_crossed = True
                    trigger_tf = tf
                    candlestick_pattern = "RSI 30 Yukarı Kesim (Aşırı Satım Dönüşü)"
                    break
                elif gc_ok:
                    trigger_crossed = True
                    trigger_tf = tf
                    candlestick_pattern = "EMA9 > EMA20 Kesişimi (Dip Formasyonu Onayı)"
                    break

        # Enriched indicators for matplotlib signal rendering
        enriched_indicators = {
            "rsi_value": rsi_val,
            "vol_ma": vol_ma,
            "ema_50": ema50,
            "ema_200": ema200
        }
        
        # If trigger tf is active, enrich lower indicators for chart overlay
        tr_df = lower_tfs_data.get(trigger_tf)
        if tr_df is not None and len(tr_df) >= 30:
            try:
                enriched_indicators["ema_9"] = tr_df["close"].ewm(span=9, adjust=False).mean()
                enriched_indicators["ema_21"] = tr_df["close"].ewm(span=20, adjust=False).mean()
                
                bb_middle = tr_df["close"].rolling(20).mean()
                bb_std = tr_df["close"].rolling(20).std()
                enriched_indicators["bb_upper"] = bb_middle + 2 * bb_std
                enriched_indicators["bb_lower"] = bb_middle - 2 * bb_std
                
                enriched_indicators["vol_ma"] = tr_df["volume"].rolling(20).mean()
                enriched_indicators["rsi"] = self.calculate_rsi(tr_df["close"], 14)
            except Exception as chart_err:
                logger.error(f"Enriched chart indicators computation failed: {chart_err}")

        return SpotPipelineSignal(
            symbol=symbol,
            signal_type="buy" if trigger_crossed else "info",
            price=price,
            tf_statuses=tf_statuses,
            total_score=total_score,
            max_score=max_score,
            trigger_tf=trigger_tf,
            trigger_crossed=trigger_crossed,
            segment_type=segment,
            rsi_value=rsi_val,
            adx_value=float("nan"),
            adx_regime="trending" if segment == "STRONG" else "weak",
            rsi_quality="ideal" if rsi_ok else "ok",
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            candlestick_pattern=candlestick_pattern,
            indicators=enriched_indicators
        )

    def _calc_ma(self, series: pd.Series, period: int, ma_type: str = "SMMA") -> pd.Series:
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
        elif ma_type == "SMMA" or ma_type == "RMA":
            return series.ewm(alpha=1.0 / period, adjust=False).mean()
        elif ma_type == "HULLMA":
            half_len = int(period / 2)
            sqrt_len = int(round(np.sqrt(period)))
            wma_half = series.rolling(half_len).apply(
                lambda x: np.dot(x, np.arange(1, half_len + 1, dtype=float)) / np.arange(1, half_len + 1).sum(), raw=True
            )
            wma_full = series.rolling(period).apply(
                lambda x: np.dot(x, np.arange(1, period + 1, dtype=float)) / np.arange(1, period + 1).sum(), raw=True
            )
            hull_src = 2 * wma_half - wma_full
            return hull_src.rolling(sqrt_len).apply(
                lambda x: np.dot(x, np.arange(1, sqrt_len + 1, dtype=float)) / np.arange(1, sqrt_len + 1).sum(), raw=True
            )
        return series.rolling(period).mean()

    def calculate_occ_status(self, df: pd.DataFrame, timeframe: str) -> OccTfStatus:
        if df is None or len(df) < 15:
            return OccTfStatus(timeframe=timeframe, label="", weight=0, is_green=False)
        close = df["close"]
        open_ = df["open"]
        close_ma = self._calc_ma(close, period=8, ma_type="SMMA")
        open_ma = self._calc_ma(open_, period=8, ma_type="SMMA")
        
        c_now = _safe_float(close_ma, -2)
        o_now = _safe_float(open_ma, -2)
        c_prev = _safe_float(close_ma, -3)
        o_prev = _safe_float(open_ma, -3)
        
        if math.isnan(c_now) or math.isnan(o_now):
            return OccTfStatus(timeframe=timeframe, label="", weight=0, is_green=False)
            
        is_green = c_now > o_now
        just_crossed = False
        if not (math.isnan(c_prev) or math.isnan(o_prev)):
            just_crossed = is_green != (c_prev > o_prev)
            
        avg = (c_now + o_now) / 2 if (c_now + o_now) != 0 else 1
        strength = 50000.0 * (c_now - o_now) / avg
        
        occ_labels = {
            "1w": "Weekly Trend",
            "1d": "Daily Trend",
            "4h": "4-Hour Trend",
            "1h": "1-Hour Trend",
            "15m": "15-Min Momentum"
        }
        
        return OccTfStatus(
            timeframe=timeframe,
            label=occ_labels.get(timeframe, ""),
            weight=1,
            is_green=is_green,
            just_crossed=just_crossed,
            close_ma=c_now,
            open_ma=o_now,
            strength=strength
        )



# ==================== GERİYE UYUMLULUK WRAPPER ====================
# Eski MultiTfOccAnalyzer ve TechnicalAnalyzer referanslarının hata vermemesi için uyumluluk katmanı

class MultiTfOccAnalyzer:
    """Wrapper that routes analyze calls to SpotPipelineAnalyzer."""
    def __init__(self):
        self.spa = SpotPipelineAnalyzer()

    def analyze_multi_tf(self, symbol: str, tf_data: dict):
        # Bu metod eski OCC analizini simüle eder. Yeni Pipeline scanner.py içinde çalışacak.
        return None


class TechnicalAnalyzer:
    """Geriye uyumluluk wrapper."""
    def __init__(self, criteria: dict = None, min_strength_pct: float = None):
        self.spa = SpotPipelineAnalyzer()

    def analyze(self, symbol, df, htf_df=None, btc_df=None):
        return None

    def check_exit_signal(self, symbol, df):
        return None
