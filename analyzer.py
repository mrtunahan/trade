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
    RSI_CONFIG, ADX_CONFIG, DYNAMIC_STOP_LOSS, SIGNAL_FILTER,
    VOLUME_CONFIRM, RSI_DIVERGENCE,
)

logger = logging.getLogger("Analyzer")


def _safe_float(series, index=-1, default=float("nan")) -> float:
    try:
        val = float(series.iloc[index])
        return val if not math.isnan(val) else default
    except (IndexError, TypeError, ValueError):
        return default


def _calc_ma(series: pd.Series, period: int, ma_type: str = "SMMA") -> pd.Series:
    """
    Pine Script OCC indikatöründeki tüm MA tiplerini destekler.
    Orijinal indikatörün varsayılanı: SMMA, periyot 8.
    """
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
        # Pine Script: v7 := na(v7[1]) ? sma(src, len) : (v7[1] * (len - 1) + src) / len
        # Bu, alpha=1/period olan EWM ile eşdeğerdir
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
    elif ma_type == "LSMA":
        return series.rolling(period).apply(
            lambda x: np.polyval(np.polyfit(np.arange(period), x, 1), period - 1), raw=True
        )
    elif ma_type == "TMA":
        # Triangular MA = SMA of SMA
        sma1 = series.rolling(period).mean()
        return sma1.rolling(period).mean()
    elif ma_type == "SSMA":
        # SuperSmoother filter (John Ehlers)
        a1 = np.exp(-1.414 * np.pi / period)
        b1 = 2 * a1 * np.cos(1.414 * np.pi / period)
        c2 = b1
        c3 = -a1 * a1
        c1 = 1 - c2 - c3
        result = series.copy().astype(float)
        vals = series.values.astype(float)
        res = np.empty_like(vals)
        res[0] = vals[0]
        res[1] = vals[1] if len(vals) > 1 else vals[0]
        for i in range(2, len(vals)):
            res[i] = c1 * (vals[i] + vals[i - 1]) / 2 + c2 * res[i - 1] + c3 * res[i - 2]
        return pd.Series(res, index=series.index)
    else:
        # Varsayılan: SMMA (orijinal Pine Script varsayılanı)
        return series.ewm(alpha=1.0 / period, adjust=False).mean()


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

    # Hacim Onayı
    volume_ratio: float = 0.0        # Mevcut hacim / ortalama hacim
    volume_confirmed: bool = False    # volume_ratio >= confirm_ratio
    volume_surge: bool = False        # volume_ratio >= surge_ratio
    volume_label: str = ""            # "Hacim Patlaması", "Hacim Onaylı", "Düşük Hacim"

    # RSI Divergence
    rsi_divergence: str = "none"      # "bullish", "bearish", "none"
    rsi_div_strength: float = 0.0     # RSI fark büyüklüğü (güç göstergesi)

    # Meta
    indicators: dict = field(default_factory=dict)
    market_regime: str = "unknown"

    @property
    def is_valid_entry(self) -> bool:
        """
        Giriş sinyali geçerli mi?

        4 sinyal tipi aktif:
        1. Dip Avcısı:       🟢1w 🟢1d 🔴4h 🔴1h 🟢15m + ADX > 25 + RSI >= 50
        2. Trend Takipçi:    🟢1w 🟢1d 🟢4h 🔴1h 🟢15m + ADX > 25 + RSI >= 50
        3. Trend Takipçi v2: 🟢1w 🟢1d 🔴4h 🟢1h 🟢15m + ADX > 25 + RSI >= 50
        4. Full Sniper:      Tüm TF'ler yeşil (puan >= 7) + ADX > 25 + RSI >= 50
        """
        # Temel koşullar: 15dk tetikleyici yeşil olmalı
        if not self.trigger_crossed:
            return False

        # Minimum puan kontrolü
        if self.total_score < OCC_MIN_SCORE:
            return False

        cfg = SIGNAL_FILTER
        if not cfg.get("enabled", False):
            # Filtre kapalıysa eski davranış
            return self.rsi_quality != "blocked"

        # RSI blocked ise her durumda engelle (>= 80)
        if self.rsi_quality == "blocked":
            return False

        # ADX veya RSI hesaplanamadıysa geçirme
        if math.isnan(self.adx_value) or math.isnan(self.rsi_value):
            return False

        # OCC dizilimini çıkar: {timeframe: is_green}
        current_pattern = {s.timeframe: s.is_green for s in self.tf_statuses}

        # ---- Kural 1: Tanımlı desen eşleşmesi (desen bazlı eşikler) ----
        for allowed in cfg.get("allowed_patterns", []):
            pattern = allowed.get("pattern", {})
            if all(current_pattern.get(tf) == expected
                   for tf, expected in pattern.items()):
                # Bu desen eşleşti — desenin kendi eşiklerini kullan
                min_adx = allowed.get("min_adx", 20)
                max_adx = allowed.get("max_adx", 100)
                min_rsi = allowed.get("min_rsi", 35)
                if self.adx_value > min_adx and self.adx_value <= max_adx and self.rsi_value >= min_rsi:
                    self._matched_pattern = allowed.get("name", "Desen")
                    return True
                return False  # Desen eşleşti ama eşikler tutmadı

        # ---- Kural 2: Full Sniper (tüm üst TF'ler yeşil) ----
        if cfg.get("allow_full_sniper", True):
            sniper_score = cfg.get("full_sniper_min_score", 7)
            if self.total_score >= sniper_score:
                min_adx = cfg.get("full_sniper_min_adx", 22)
                min_rsi = cfg.get("full_sniper_min_rsi", 45)
                if self.adx_value > min_adx and self.rsi_value >= min_rsi:
                    self._matched_pattern = "Full Sniper"
                    return True

        # ---- Kural 3: Puan bazlı geçiş (score_fallback) ----
        fallback = cfg.get("score_fallback", {})
        if fallback.get("enabled", False):
            fb_min_score = fallback.get("min_score", 6)
            if self.total_score >= fb_min_score:
                # Üst TF koruması: 1w veya 1d'den en az biri yeşil olmalı
                if fallback.get("require_upper_tf", True):
                    has_upper = current_pattern.get("1w", False) or current_pattern.get("1d", False)
                    if not has_upper:
                        return False
                min_adx = fallback.get("min_adx", 22)
                min_rsi = fallback.get("min_rsi", 45)
                if self.adx_value > min_adx and self.rsi_value >= min_rsi:
                    self._matched_pattern = "Puan Geçişi"
                    return True

        return False

    @property
    def matched_pattern_name(self) -> str:
        """Eşleşen desen adını döndürür."""
        return getattr(self, "_matched_pattern", "")

    @property
    def signal_star_rating(self) -> dict:
        """
        Yıldız bazlı kalite sistemi + hacim/divergence boost.

        Temel yıldız: Puana göre belirlenir (config tiers).
        Boost: Hacim surge veya bullish divergence varsa yıldız artırılır.
        Penalty: Düşük hacimde pozisyon küçültülür.

        Returns: {"stars": "⭐⭐", "label": "Güçlü Sinyal", "position_pct": 75,
                  "boosted": bool, "boost_reason": str}
        """
        cfg = SIGNAL_FILTER.get("star_rating", {})
        if not cfg.get("enabled", False):
            if self.total_score >= 7:
                return {"stars": "⭐⭐⭐", "label": "Full Sniper",
                        "position_pct": 100, "boosted": False, "boost_reason": ""}
            elif self.total_score >= 5:
                return {"stars": "⭐⭐", "label": "Güçlü Sinyal",
                        "position_pct": 75, "boosted": False, "boost_reason": ""}
            return {"stars": "⭐", "label": "Fırsat",
                    "position_pct": 50, "boosted": False, "boost_reason": ""}

        # Temel tier (puan bazlı)
        base = {"stars": "⭐", "label": "Fırsat", "position_pct": 50}
        for tier in cfg.get("tiers", []):
            if self.total_score >= tier["min_score"]:
                base = {
                    "stars": tier["stars"],
                    "label": tier["label"],
                    "position_pct": tier["position_pct"],
                }
                break

        # ---- Boost/Penalty sistemi ----
        boost_reasons = []

        # Hacim surge boost: yıldız + pozisyon artır
        if self.volume_surge and VOLUME_CONFIRM.get("boost_star", True):
            if base["stars"].count("⭐") < 3:
                base["stars"] += "⭐"
            base["position_pct"] = min(base["position_pct"] + 25, 100)
            boost_reasons.append("Hacim Patlaması")

        # Bullish divergence boost: pozisyon artır
        if self.rsi_divergence == "bullish":
            base["position_pct"] = min(base["position_pct"] + 15, 100)
            boost_reasons.append(f"Bullish Div (+{self.rsi_div_strength:.0f})")

        # Düşük hacim penalty: pozisyon küçült
        if self.volume_label == "Düşük Hacim":
            base["position_pct"] = max(base["position_pct"] - 25, 25)
            boost_reasons.append("Düşük Hacim ⚠️")

        # Bearish divergence warning: pozisyon küçült
        if self.rsi_divergence == "bearish":
            base["position_pct"] = max(base["position_pct"] - 20, 25)
            boost_reasons.append("Bearish Div ⚠️")

        base["boosted"] = len(boost_reasons) > 0
        base["boost_reason"] = " | ".join(boost_reasons)

        return base

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
        rating = self.signal_star_rating
        return rating["position_pct"] / 100.0

    @property
    def position_tier(self):
        rating = self.signal_star_rating
        return rating["label"]


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
                trigger_crossed = occ_status.just_crossed and occ_status.is_green
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

        # Hacim onayı (15dk verisinden)
        vol_data = self._calculate_volume_confirmation(tf_data.get("15m"))

        # RSI Divergence (15dk veya 1H verisinden)
        div_df = tf_data.get("15m")
        if div_df is None or len(div_df) < RSI_DIVERGENCE.get("lookback", 50):
            div_df = tf_data.get("1h")
        rsi_div = self._detect_rsi_divergence(div_df)

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
            volume_ratio=vol_data["ratio"],
            volume_confirmed=vol_data["confirmed"],
            volume_surge=vol_data["surge"],
            volume_label=vol_data["label"],
            rsi_divergence=rsi_div["type"],
            rsi_div_strength=rsi_div["strength"],
            market_regime=adx_regime,
            indicators={
                "rsi_value": rsi_value,
                "adx_value": adx_value,
                "volume_ratio": vol_data["ratio"],
                "rsi_divergence": rsi_div["type"],
            },
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

        # Strength: Pine Script formülü: pcd = 50000 * diff / closeOpenAvg
        avg = (c_now + o_now) / 2 if (c_now + o_now) != 0 else 1
        strength = 50000.0 * (c_now - o_now) / avg

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

    # ==================== HACİM ONAYI ====================

    def _calculate_volume_confirmation(self, df: pd.DataFrame) -> dict:
        """
        15dk verisinden hacim onay metrikleri hesaplar.

        Non-repaint: iloc[-2] kullanır (son kapanmış mum).
        Karşılaştırma: Son kapanmış mum hacmi vs N-bar ortalama.

        Returns: {
            "ratio": float,        # Hacim oranı (current / average)
            "confirmed": bool,     # >= confirm_ratio (1.5x)
            "surge": bool,         # >= surge_ratio (3.0x)
            "label": str,          # İnsan okunabilir etiket
        }
        """
        cfg = VOLUME_CONFIRM
        result = {"ratio": 0.0, "confirmed": False, "surge": False, "label": ""}

        if not cfg.get("enabled", True):
            return result

        if df is None or len(df) < cfg.get("period", 20) + 2:
            return result

        vol = df["quote_volume"]  # USDT/TRY cinsinden hacim
        period = cfg.get("period", 20)

        # Non-repaint: Son kapanmış mum (iloc[-2])
        current_vol = float(vol.iloc[-2])

        # Ortalama: Son N kapanmış mum ([-2-period:-2] aralığı)
        avg_vol = float(vol.iloc[-(period + 2):-2].mean())

        if avg_vol <= 0:
            return result

        ratio = current_vol / avg_vol
        result["ratio"] = round(ratio, 2)

        confirm_ratio = cfg.get("confirm_ratio", 1.5)
        surge_ratio = cfg.get("surge_ratio", 3.0)
        penalty_below = cfg.get("penalty_below", 0.5)

        if ratio >= surge_ratio:
            result["surge"] = True
            result["confirmed"] = True
            result["label"] = "Hacim Patlaması"
        elif ratio >= confirm_ratio:
            result["confirmed"] = True
            result["label"] = "Hacim Onaylı"
        elif ratio < penalty_below:
            result["label"] = "Düşük Hacim"
        else:
            result["label"] = "Normal Hacim"

        return result

    # ==================== RSI DIVERGENCE ====================

    def _find_pivot_lows(self, series: pd.Series,
                         left: int = 5, right: int = 2) -> list:
        """
        Lokal minimumları (pivot low) tespit eder.

        Bir noktanın pivot low olması için:
        - Sol tarafındaki 'left' mum ondan büyük olmalı
        - Sağ tarafındaki 'right' mum ondan büyük olmalı

        Returns: [(index_position, value), ...]
        """
        pivots = []
        arr = series.values

        for i in range(left, len(arr) - right):
            is_pivot = True
            # Sol taraf kontrolü
            for j in range(1, left + 1):
                if arr[i] > arr[i - j]:
                    is_pivot = False
                    break
            if not is_pivot:
                continue
            # Sağ taraf kontrolü
            for j in range(1, right + 1):
                if arr[i] > arr[i + j]:
                    is_pivot = False
                    break
            if is_pivot:
                pivots.append((i, float(arr[i])))

        return pivots

    def _detect_rsi_divergence(self, df: pd.DataFrame) -> dict:
        """
        RSI Bullish/Bearish Divergence tespiti.

        Bullish Divergence (Boğa Uyumsuzluğu):
        - Fiyat: daha düşük dip yapıyor (lower low)
        - RSI: daha yüksek dip yapıyor (higher low)
        → Satış baskısı zayıflıyor, dönüş sinyali

        Bearish Divergence (Ayı Uyumsuzluğu):
        - Fiyat: daha yüksek tepe yapıyor (higher high)
        - RSI: daha düşük tepe yapıyor (lower high)
        → Alım baskısı zayıflıyor, düşüş sinyali

        Non-repaint: Sadece onaylanmış pivotlar kullanılır
        (sağ tarafta 'pivot_right' mum onay bekler).

        Returns: {
            "type": "bullish" | "bearish" | "none",
            "strength": float,     # RSI fark büyüklüğü
            "price_drop_pct": float, # Fiyat düşüş yüzdesi
        }
        """
        cfg = RSI_DIVERGENCE
        result = {"type": "none", "strength": 0.0, "price_drop_pct": 0.0}

        if not cfg.get("enabled", True):
            return result

        lookback = cfg.get("lookback", 50)
        pivot_left = cfg.get("pivot_left", 5)
        pivot_right = cfg.get("pivot_right", 2)
        min_rsi_diff = cfg.get("min_rsi_diff", 5.0)
        min_price_drop = cfg.get("min_price_drop_pct", 1.0)

        if df is None or len(df) < lookback:
            return result

        # Son 'lookback' mumu al (non-repaint: son mumu hariç tut)
        df_window = df.iloc[-(lookback + 1):-1].copy()

        # RSI serisi hesapla
        period = RSI_CONFIG.get("period", 14)
        close = df_window["close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))

        low = df_window["low"]

        # Pivot low'ları bul (fiyat ve RSI için)
        price_pivots = self._find_pivot_lows(low, pivot_left, pivot_right)
        rsi_pivots = self._find_pivot_lows(rsi_series.dropna(), pivot_left, pivot_right)

        if len(price_pivots) < 2 or len(rsi_pivots) < 2:
            return result

        # ---- Bullish Divergence ----
        # Son iki fiyat pivot low'u karşılaştır
        p_prev_idx, p_prev_val = price_pivots[-2]
        p_last_idx, p_last_val = price_pivots[-1]

        # Fiyat lower low yapıyor mu?
        price_drop_pct = (p_prev_val - p_last_val) / p_prev_val * 100
        if p_last_val < p_prev_val and price_drop_pct >= min_price_drop:
            # RSI'da aynı bölgedeki pivotları bul
            # Price pivot indekslerine en yakın RSI değerlerini kullan
            rsi_at_prev = _safe_float(rsi_series, p_prev_idx)
            rsi_at_last = _safe_float(rsi_series, p_last_idx)

            if not (math.isnan(rsi_at_prev) or math.isnan(rsi_at_last)):
                rsi_diff = rsi_at_last - rsi_at_prev
                # RSI higher low yapıyor mu? (fiyat düşerken RSI yükseliyor)
                if rsi_diff >= min_rsi_diff:
                    result["type"] = "bullish"
                    result["strength"] = round(rsi_diff, 1)
                    result["price_drop_pct"] = round(price_drop_pct, 2)
                    return result

        # ---- Bearish Divergence (bilgilendirme amaçlı) ----
        # Fiyat higher high + RSI lower high
        high = df_window["high"]
        high_pivots = self._find_pivot_highs(high, pivot_left, pivot_right)

        if len(high_pivots) >= 2:
            h_prev_idx, h_prev_val = high_pivots[-2]
            h_last_idx, h_last_val = high_pivots[-1]

            if h_last_val > h_prev_val:
                rsi_at_prev = _safe_float(rsi_series, h_prev_idx)
                rsi_at_last = _safe_float(rsi_series, h_last_idx)

                if not (math.isnan(rsi_at_prev) or math.isnan(rsi_at_last)):
                    rsi_diff = rsi_at_prev - rsi_at_last
                    if rsi_diff >= min_rsi_diff:
                        result["type"] = "bearish"
                        result["strength"] = round(rsi_diff, 1)
                        return result

        return result

    def _find_pivot_highs(self, series: pd.Series,
                          left: int = 5, right: int = 2) -> list:
        """Lokal maksimumları (pivot high) tespit eder."""
        pivots = []
        arr = series.values

        for i in range(left, len(arr) - right):
            is_pivot = True
            for j in range(1, left + 1):
                if arr[i] < arr[i - j]:
                    is_pivot = False
                    break
            if not is_pivot:
                continue
            for j in range(1, right + 1):
                if arr[i] < arr[i + j]:
                    is_pivot = False
                    break
            if is_pivot:
                pivots.append((i, float(arr[i])))

        return pivots


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
