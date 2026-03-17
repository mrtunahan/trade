# ============================================================================
# analyzer.py - Hiyerarşik Multi-TF OCC Analiz Motoru
# ============================================================================
# 5 timeframe'de OCC (Open Close Cross) durumu kontrol eder.
# Haftalık(3p) + Günlük(2p) + 4H(2p) + 1H(1p) + 15dk(tetikleyici)
# Toplam ≥5 puan + 15dk yeşil → ALIM sinyali
#
# RSI: giriş kalitesi filtresi (30-50 ideal, 70+ dikkat)
# ADX: trend gücü filtresi (>25 trend var, <15 zayıf)
# ============================================================================

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    OCC_TIMEFRAMES, OCC_MIN_SCORE, OCC_PERIOD, OCC_MA_TYPE, OCC_MIN_STRENGTH,
    RSI_CONFIG, ADX_CONFIG, DYNAMIC_STOP_LOSS,
)

logger = logging.getLogger("Analyzer")


def _safe_float(series, index=-1, default=float("nan")) -> float:
    try:
        val = float(series.iloc[index])
        return val if not math.isnan(val) else default
    except (IndexError, TypeError, ValueError):
        return default


def _calc_ma(series: pd.Series, period: int, ma_type: str = "EMA") -> pd.Series:
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
    else:
        return series.ewm(span=period, adjust=False).mean()


# ==================== OCC TF DURUMU ====================

@dataclass
class OccTfStatus:
    """Tek bir timeframe'deki OCC durumu."""
    timeframe: str
    label: str           # "Haftalık", "Günlük" vb.
    weight: int          # Bu TF'nin puan ağırlığı
    is_green: bool       # True = yükseliş (Close MA > Open MA)
    just_crossed: bool   # True = bu mumda renk değişti
    close_ma: float      # Son Close MA değeri
    open_ma: float       # Son Open MA değeri
    strength: float      # Cross strength (fark yüzdesi)


@dataclass
class MultiTfSignal:
    """Hiyerarşik multi-TF OCC sinyal sonucu."""
    symbol: str
    signal_type: str          # "buy", "sell", "info", "tf_change"
    price: float
    tf_statuses: list         # [OccTfStatus, ...]
    total_score: int          # Ağırlıklı puan toplamı
    max_score: int            # Maksimum mümkün puan
    trigger_tf: str           # Tetikleyici TF ("15m")
    trigger_crossed: bool     # 15dk'da yeni cross oldu mu

    # RSI ve ADX filtreleri
    rsi_value: float = float("nan")
    rsi_quality: str = ""     # "ideal", "ok", "caution", "blocked"
    adx_value: float = float("nan")
    adx_regime: str = ""      # "trending", "ranging", "weak"

    # SL/TP
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 6.0

    # Meta
    indicators: dict = field(default_factory=dict)
    market_regime: str = "unknown"

    @property
    def is_valid_entry(self) -> bool:
        """Giriş sinyali geçerli mi?"""
        return (self.total_score >= OCC_MIN_SCORE and
                self.trigger_crossed and
                self.rsi_quality != "blocked")

    @property
    def score_pct(self) -> float:
        return self.total_score / self.max_score if self.max_score > 0 else 0.0

    # Eski Signal uyumluluğu
    @property
    def strength(self):
        return self.total_score

    @property
    def total_criteria(self):
        return self.max_score

    @property
    def strength_pct(self):
        return self.score_pct

    @property
    def criteria_met(self):
        return [s.timeframe for s in self.tf_statuses if s.is_green]

    @property
    def criteria_details(self):
        details = {}
        for s in self.tf_statuses:
            details[s.timeframe] = {
                "met": s.is_green,
                "detail": f"{s.label} OCC {'Yeşil' if s.is_green else 'Kırmızı'} (güç: {s.strength:.3f}%)",
                "description": f"{s.label} {'yükseliş' if s.is_green else 'düşüş'}",
                "weight": s.weight,
            }
        return details

    @property
    def exit_score(self):
        return 0

    @property
    def exit_details(self):
        return {}

    @property
    def position_size_pct(self):
        if self.total_score >= 7:
            return 1.0
        elif self.total_score >= 5:
            return 0.75
        return 0.50

    @property
    def position_tier(self):
        if self.total_score >= 7:
            return "Full Sniper"
        elif self.total_score >= 5:
            return "Strong"
        return "Normal"


# ==================== ANA ANALİZ MOTORU ====================

class MultiTfOccAnalyzer:
    """
    Hiyerarşik Multi-Timeframe OCC Analiz Motoru.

    Her sembol için 5 timeframe'de OCC durumunu kontrol eder,
    ağırlıklı puanlama yapar, RSI/ADX filtreleri uygular.
    """

    def __init__(self):
        self.occ_period = OCC_PERIOD
        self.occ_ma_type = OCC_MA_TYPE
        self.occ_min_strength = OCC_MIN_STRENGTH

        # Önceki OCC durumlarını cache'le (renk değişimi tespiti için)
        # {(symbol, timeframe): is_green}
        self._prev_occ_state = {}

    def analyze_multi_tf(self, symbol: str,
                         tf_data: dict) -> Optional[MultiTfSignal]:
        """
        Tüm timeframe'lerde OCC durumunu analiz eder.

        Args:
            symbol: Parite ismi (örn: "BIOTRY")
            tf_data: {timeframe: DataFrame} — 5 TF'nin mum verisi

        Returns: MultiTfSignal veya None
        """
        if not tf_data:
            return None

        tf_statuses = []
        total_score = 0
        max_score = 0
        trigger_crossed = False

        for tf, (weight, _, label) in OCC_TIMEFRAMES.items():
            df = tf_data.get(tf)
            if df is None or len(df) < 30:
                # Veri yoksa bu TF'yi atla (kırmızı say)
                tf_statuses.append(OccTfStatus(
                    timeframe=tf, label=label, weight=weight,
                    is_green=False, just_crossed=False,
                    close_ma=0, open_ma=0, strength=0,
                ))
                if tf != "15m":
                    max_score += weight
                continue

            # OCC hesapla (just_crossed veriden gelir, state'den değil)
            occ_status = self._check_occ_status(df, tf)
            occ_status.label = label
            occ_status.weight = weight

            tf_statuses.append(occ_status)

            if tf == "15m":
                # 15dk tetikleyici — puan vermez, sadece cross kontrolü
                trigger_crossed = just_crossed and occ_status.is_green
            else:
                max_score += weight
                if occ_status.is_green:
                    total_score += weight

        # 15dk verisi yoksa tetikleyici olamaz
        trigger_df = tf_data.get("15m")
        if trigger_df is None or len(trigger_df) < 30:
            trigger_crossed = False

        # RSI hesapla (15dk veya 1H verisinden)
        rsi_value = float("nan")
        rsi_quality = ""
        rsi_df = tf_data.get("15m")
        if rsi_df is None:
            rsi_df = tf_data.get("1h")
        if rsi_df is not None and len(rsi_df) >= 20 and RSI_CONFIG.get("enabled"):
            rsi_value = self._calculate_rsi(rsi_df)
            rsi_quality = self._assess_rsi_quality(rsi_value)

        # ADX hesapla (1H verisinden)
        adx_value = float("nan")
        adx_regime = "unknown"
        adx_df = tf_data.get("1h")
        if adx_df is None:
            adx_df = tf_data.get("4h")
        if adx_df is not None and len(adx_df) >= 30 and ADX_CONFIG.get("enabled"):
            adx_value = self._calculate_adx_value(adx_df)
            adx_regime = self._assess_adx_regime(adx_value)

        # Fiyat (15dk verisinden)
        price = 0.0
        for tf_key in ["15m", "1h", "4h", "1d", "1w"]:
            df = tf_data.get(tf_key)
            if df is not None and len(df) > 0:
                price = float(df["close"].iloc[-1])
                break

        # SL/TP hesapla
        sl_pct, tp_pct = self._calculate_sl_tp(adx_value)

        signal = MultiTfSignal(
            symbol=symbol,
            signal_type="buy" if trigger_crossed and total_score >= OCC_MIN_SCORE else "info",
            price=price,
            tf_statuses=tf_statuses,
            total_score=total_score,
            max_score=max_score,
            trigger_tf="15m",
            trigger_crossed=trigger_crossed,
            rsi_value=rsi_value,
            rsi_quality=rsi_quality,
            adx_value=adx_value,
            adx_regime=adx_regime,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            market_regime=adx_regime,
            indicators={"rsi_value": rsi_value, "adx_value": adx_value},
        )

        return signal

    def check_tf_changes(self, symbol: str,
                         tf_data: dict) -> list:
        """
        Her timeframe'deki OCC renk değişimlerini tespit eder.
        Her değişim ayrı bir bildirim olarak döndürülür.

        Returns: [MultiTfSignal, ...] — renk değişen TF'ler
        """
        changes = []

        for tf, (weight, _, label) in OCC_TIMEFRAMES.items():
            df = tf_data.get(tf)
            if df is None or len(df) < 30:
                continue

            occ_status = self._check_occ_status(df, tf)
            prev_state = self._prev_occ_state.get((symbol, tf))

            if prev_state is not None and prev_state != occ_status.is_green:
                # Renk değişti!
                occ_status.just_crossed = True
                occ_status.label = label
                occ_status.weight = weight

                price = float(df["close"].iloc[-1])

                change_signal = MultiTfSignal(
                    symbol=symbol,
                    signal_type="tf_change",
                    price=price,
                    tf_statuses=[occ_status],
                    total_score=weight if occ_status.is_green else 0,
                    max_score=weight,
                    trigger_tf=tf,
                    trigger_crossed=occ_status.is_green,
                    market_regime="unknown",
                )
                changes.append(change_signal)

            # State güncelle
            self._prev_occ_state[(symbol, tf)] = occ_status.is_green

        return changes

    # ==================== OCC HESAPLAMA ====================

    def _check_occ_status(self, df: pd.DataFrame, tf: str) -> OccTfStatus:
        """
        Tek bir timeframe için OCC durumunu hesaplar.
        Non-repaint: iloc[-2] kullanır (son kapanmış mum).
        """
        close = df["close"]
        open_ = df["open"]

        close_ma = _calc_ma(close, self.occ_period, self.occ_ma_type)
        open_ma = _calc_ma(open_, self.occ_period, self.occ_ma_type)

        # Non-repaint: Son kapanmış mumu kullan
        c_now = _safe_float(close_ma, -2)
        o_now = _safe_float(open_ma, -2)
        c_prev = _safe_float(close_ma, -3)
        o_prev = _safe_float(open_ma, -3)

        if math.isnan(c_now) or math.isnan(o_now):
            return OccTfStatus(
                timeframe=tf, label="", weight=0,
                is_green=False, just_crossed=False,
                close_ma=0, open_ma=0, strength=0,
            )

        is_green = c_now > o_now

        # Cross tespiti (son mumda renk değişti mi)
        just_crossed = False
        if not (math.isnan(c_prev) or math.isnan(o_prev)):
            was_green = c_prev > o_prev
            just_crossed = is_green != was_green

        # Strength: fark yüzdesi
        mid = (c_now + o_now) / 2 if (c_now + o_now) != 0 else 1
        strength = ((c_now - o_now) / mid) * 100

        return OccTfStatus(
            timeframe=tf, label="", weight=0,
            is_green=is_green, just_crossed=just_crossed,
            close_ma=c_now, open_ma=o_now, strength=strength,
        )

    # ==================== RSI ====================

    def _calculate_rsi(self, df: pd.DataFrame, period: int = None) -> float:
        period = period or RSI_CONFIG.get("period", 14)
        close = df["close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return _safe_float(rsi, -1)

    def _assess_rsi_quality(self, rsi_value: float) -> str:
        if math.isnan(rsi_value):
            return "ok"
        cfg = RSI_CONFIG
        if rsi_value >= cfg.get("block_level", 80):
            return "blocked"
        elif rsi_value >= cfg.get("caution_level", 70):
            return "caution"
        elif cfg.get("ideal_entry_min", 30) <= rsi_value <= cfg.get("ideal_entry_max", 50):
            return "ideal"
        return "ok"

    # ==================== ADX ====================

    def _calculate_adx_value(self, df: pd.DataFrame) -> float:
        period = ADX_CONFIG.get("period", 14)
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

        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        smooth_plus = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        smooth_minus = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        plus_di = (smooth_plus / atr.replace(0, np.nan)) * 100
        minus_di = (smooth_minus / atr.replace(0, np.nan)) * 100

        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        return _safe_float(adx, -1)

    def _assess_adx_regime(self, adx_value: float) -> str:
        if math.isnan(adx_value):
            return "unknown"
        cfg = ADX_CONFIG
        if adx_value >= cfg.get("strong_trend", 25):
            return "trending"
        elif adx_value <= cfg.get("weak_market", 15):
            return "weak"
        return "ranging"

    # ==================== SL/TP ====================

    def _calculate_sl_tp(self, adx_value: float) -> tuple:
        cfg = DYNAMIC_STOP_LOSS
        if not cfg.get("enabled", False) or math.isnan(adx_value):
            return cfg.get("base_sl_pct", 3.0), cfg.get("base_tp_pct", 6.0)

        if adx_value >= cfg.get("strong_trend_adx", 40):
            return cfg["trend_sl_pct"], cfg["trend_tp_pct"]
        elif adx_value <= cfg.get("ranging_adx", 20):
            return cfg["range_sl_pct"], cfg["range_tp_pct"]
        return cfg["base_sl_pct"], cfg["base_tp_pct"]


# ==================== ESKİ SİSTEM UYUMLULUĞU ====================
# Eski kodun beklediği TechnicalAnalyzer sınıfı

class TechnicalAnalyzer:
    """Geriye uyumluluk wrapper — yeni MultiTfOccAnalyzer'ı kullanır."""

    def __init__(self, criteria: dict = None, min_strength_pct: float = None):
        self.multi_tf = MultiTfOccAnalyzer()

    def analyze(self, symbol, df, htf_df=None, btc_df=None):
        # Eski single-TF analiz — artık kullanılmıyor
        return None

    def check_exit_signal(self, symbol, df):
        return None
