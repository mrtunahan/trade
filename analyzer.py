# ============================================================================
# analyzer.py - Teknik Analiz Motoru (Geliştirilmiş v2)
# ============================================================================
# Mum verisinden indikatörler hesaplar ve kriter kontrolü yapar.
# v2: ADX market rejimi, ATR adaptif eşikler, confluence window,
#     çıkış stratejisi puanlaması, dinamik ağırlık sistemi
# ============================================================================

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import CRITERIA, MIN_CRITERIA_MET, MIN_SIGNAL_STRENGTH_PCT, POSITION_SIZING, DYNAMIC_STOP_LOSS

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
    signal_type: str          # "buy", "sell", "info", "exit"
    strength: int             # Ağırlıklı puan toplamı
    total_criteria: int       # Toplam ağırlık puanı
    price: float
    criteria_met: list        # Sağlanan kriterlerin isimleri
    criteria_details: dict    # Her kriterin detay bilgisi
    indicators: dict          # Hesaplanan indikatör değerleri
    strength_pct: float = 0.0  # Ağırlıklı güç yüzdesi (0.0 - 1.0)
    market_regime: str = "unknown"  # "trending", "ranging", "transition"
    exit_score: int = 0       # Çıkış stratejisi puanı
    exit_details: dict = field(default_factory=dict)  # Çıkış detayları
    position_size_pct: float = 1.0  # Pozisyon büyüklüğü (0.0 - 1.0)
    position_tier: str = ""         # "Full Sniper", "High Probability"
    stop_loss_pct: float = 2.0      # Dinamik stop-loss yüzdesi
    take_profit_pct: float = 4.0    # Dinamik take-profit yüzdesi


class TechnicalAnalyzer:
    """Teknik analiz ve sinyal üretici."""

    def __init__(self, criteria: dict = None, min_strength_pct: float = None):
        self.criteria = criteria or CRITERIA
        self.min_criteria = MIN_CRITERIA_MET
        self.min_strength_pct = min_strength_pct if min_strength_pct is not None else MIN_SIGNAL_STRENGTH_PCT
        # Confluence window: sembol bazında OCC tetiklenme zamanı
        self._occ_trigger_candles = {}  # {symbol: candle_count_since_occ}
        # Candle cooldown: sembol bazında son sinyal sonrası mum sayısı
        self._signal_candle_counts = {}  # {symbol: candles_since_signal}

    def analyze(self, symbol: str, df: pd.DataFrame,
                htf_df: pd.DataFrame = None,
                btc_df: pd.DataFrame = None) -> Optional[Signal]:
        """
        Bir parite için tüm kriterleri çalıştırır.
        htf_df: Üst zaman dilimi DataFrame (multi-timeframe doğrulama için)
        btc_df: BTC mum verisi (BTC dominans filtresi için)
        Returns: Signal nesnesi veya None (sinyal yoksa)
        """
        if df is None or len(df) < 50:
            return None

        try:
            # İndikatörleri hesapla
            indicators = self._calculate_indicators(df)

            # Market rejimi algıla (ADX bazlı)
            market_regime = self._detect_market_regime(indicators)
            indicators["market_regime"] = market_regime

            # Dinamik ağırlıkları hesapla (market rejimine göre)
            dynamic_weights = self._get_dynamic_weights(market_regime)

            # Candle cooldown kontrolü
            candle_cd_cfg = self.criteria.get("candle_cooldown", {})
            if candle_cd_cfg.get("enabled", False):
                count = self._signal_candle_counts.get(symbol, 999)
                cd_limit = candle_cd_cfg.get("cooldown_candles", 5)
                if count < cd_limit:
                    self._signal_candle_counts[symbol] = count + 1
                    return None
                # Cooldown geçtiyse sayacı artırmaya devam et
                self._signal_candle_counts[symbol] = count + 1

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

                # Dinamik ağırlık: market rejimine göre ayarla
                base_weight = cfg.get("weight", 1)
                weight = dynamic_weights.get(name, base_weight)
                total_weight += weight

                # Volatilite bazlı dinamik hacim eşiği
                if name == "volume_spike":
                    cfg = self._apply_adaptive_volume_threshold(cfg, indicators)

                result = check_fn(df, indicators, cfg)

                if result["met"]:
                    criteria_met.append(name)
                    earned_weight += weight
                criteria_details[name] = result
                criteria_details[name]["weight"] = weight

            # Multi-Timeframe doğrulama (bonus puan)
            mtf_cfg = self.criteria.get("multi_timeframe", {})
            if mtf_cfg.get("enabled", False):
                mtf_weight = mtf_cfg.get("weight", 1)
                total_weight += mtf_weight
                mtf_result = self._check_multi_timeframe(htf_df, indicators)
                if mtf_result["met"]:
                    criteria_met.append("multi_timeframe")
                    earned_weight += mtf_weight
                criteria_details["multi_timeframe"] = mtf_result
                criteria_details["multi_timeframe"]["weight"] = mtf_weight

            # Zaman filtresi (yumuşak bonus puan)
            time_cfg = self.criteria.get("time_filter", {})
            if time_cfg.get("enabled", False):
                time_weight = time_cfg.get("weight", 1)
                total_weight += time_weight
                is_high_volume = not self._check_time_filter(df)  # True = yüksek hacim saati
                time_result = {
                    "met": is_high_volume,
                    "detail": f"Seans: {'Yüksek hacim' if is_high_volume else 'Düşük hacim'}",
                    "description": "Yüksek hacimli seans" if is_high_volume else "Düşük hacimli seans",
                }
                if is_high_volume:
                    criteria_met.append("time_filter")
                    earned_weight += time_weight
                criteria_details["time_filter"] = time_result
                criteria_details["time_filter"]["weight"] = time_weight

            # BTC filtresi (yumuşak bonus puan)
            btc_cfg = self.criteria.get("btc_filter", {})
            if btc_cfg.get("enabled", False):
                btc_weight = btc_cfg.get("weight", 1)
                total_weight += btc_weight
                btc_bullish = False
                if btc_df is not None:
                    btc_bearish = self._check_btc_filter(btc_df)
                    btc_bullish = not btc_bearish
                btc_result = {
                    "met": btc_bullish,
                    "detail": f"BTC: {'Yükseliş' if btc_bullish else 'Düşüş/Veri yok'}",
                    "description": "BTC yükseliş trendi" if btc_bullish else "BTC düşüş/belirsiz",
                }
                if btc_bullish:
                    criteria_met.append("btc_filter")
                    earned_weight += btc_weight
                criteria_details["btc_filter"] = btc_result
                criteria_details["btc_filter"]["weight"] = btc_weight

            # Zorunlu kriter kontrolü: OCC (veya required=True olan herhangi bir kriter)
            for name, cfg in self.criteria.items():
                if cfg.get("enabled", False) and cfg.get("required", False):
                    if name not in criteria_met:
                        self._update_confluence_state(symbol, name, criteria_met)
                        return None

            # Confluence Window kontrolü
            conf_cfg = self.criteria.get("confluence_window", {})
            if conf_cfg.get("enabled", False):
                if not self._check_confluence_window(symbol, criteria_met, conf_cfg):
                    return None

            # Ağırlıklı güç yüzdesi
            strength_pct = earned_weight / total_weight if total_weight > 0 else 0.0

            # Eşik (artık sert filtre yok, sadece min_strength_pct)
            effective_threshold = self.min_strength_pct

            # Çıkış stratejisi puanlaması
            exit_score, exit_details = self._calculate_exit_score(df, indicators)

            # Minimum kriter sayısı ve güç eşiği kontrolü
            if len(criteria_met) >= self.min_criteria and total_weight > 0:
                if strength_pct >= effective_threshold:
                    # Sinyal oluştu - cooldown sayacını sıfırla
                    self._signal_candle_counts[symbol] = 0

                    # Dinamik pozisyon boyutlandırma
                    pos_size, pos_tier = self._calculate_position_size(strength_pct)

                    # 4H Confidence Multiplier: 4H uyumu varsa pozisyonu büyüt
                    mtf_conf = self.criteria.get("multi_timeframe", {})
                    if "multi_timeframe" in criteria_met and mtf_conf.get("confidence_multiplier"):
                        multiplier = mtf_conf["confidence_multiplier"]
                        pos_size = min(1.0, pos_size * multiplier)
                        pos_tier += " +4H"

                    # Dinamik stop-loss / take-profit (ADX bazlı)
                    sl_pct, tp_pct = self._calculate_dynamic_sl_tp(indicators)

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
                        market_regime=market_regime,
                        exit_score=exit_score,
                        exit_details=exit_details,
                        position_size_pct=pos_size,
                        position_tier=pos_tier,
                        stop_loss_pct=sl_pct,
                        take_profit_pct=tp_pct,
                    )

            return None

        except Exception as e:
            logger.error(f"{symbol} analiz hatası: {e}", exc_info=True)
            return None

    def check_exit_signal(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Mevcut pozisyon için çıkış sinyali kontrolü.
        Giriş gibi puanlama sistemiyle kademeli çıkış değerlendirmesi yapar.
        """
        exit_cfg = self.criteria.get("exit_strategy", {})
        if not exit_cfg.get("enabled", False):
            return None

        if df is None or len(df) < 50:
            return None

        try:
            indicators = self._calculate_indicators(df)
            exit_score, exit_details = self._calculate_exit_score(df, indicators)
            min_exit = exit_cfg.get("min_exit_score", 3)

            if exit_score >= min_exit:
                return Signal(
                    symbol=symbol,
                    signal_type="exit",
                    strength=exit_score,
                    total_criteria=5,  # Max çıkış puanı
                    price=float(df["close"].iloc[-1]),
                    criteria_met=list(exit_details.keys()),
                    criteria_details=exit_details,
                    indicators=indicators,
                    strength_pct=exit_score / 5.0,
                    exit_score=exit_score,
                    exit_details=exit_details,
                )
            return None

        except Exception as e:
            logger.error(f"{symbol} çıkış analiz hatası: {e}", exc_info=True)
            return None

    # ==================== DİNAMİK POZİSYON BOYUTLANDIRMA ====================

    def _calculate_position_size(self, strength_pct: float) -> tuple:
        """
        Sinyal gücüne göre pozisyon büyüklüğü belirler.
        Returns: (position_size_pct, tier_label)
        """
        if not POSITION_SIZING.get("enabled", False):
            return 1.0, "Standart"

        for min_pct, max_pct, pos_size, label in POSITION_SIZING["tiers"]:
            if min_pct <= strength_pct <= max_pct:
                return pos_size, label

        return 0.60, "High Probability"  # Varsayılan

    def _calculate_dynamic_sl_tp(self, indicators: dict) -> tuple:
        """
        ADX bazlı dinamik stop-loss ve take-profit hesaplar.
        - Güçlü trend (ADX > 40): Geniş SL/TP (trende alan ver)
        - Yatay piyasa (ADX < 20): Dar SL/TP (hızlı kes)
        - Geçiş (20-40): Varsayılan
        Returns: (stop_loss_pct, take_profit_pct)
        """
        cfg = DYNAMIC_STOP_LOSS
        if not cfg.get("enabled", False):
            return cfg.get("base_sl_pct", 2.0), cfg.get("base_tp_pct", 4.0)

        adx_val = indicators.get("adx_last", float("nan"))
        if math.isnan(adx_val):
            return cfg["base_sl_pct"], cfg["base_tp_pct"]

        if adx_val >= cfg["strong_trend_adx"]:
            return cfg["trend_sl_pct"], cfg["trend_tp_pct"]
        elif adx_val <= cfg["ranging_adx"]:
            return cfg["range_sl_pct"], cfg["range_tp_pct"]
        else:
            return cfg["base_sl_pct"], cfg["base_tp_pct"]

    # ==================== MARKET REJİMİ ALGILAMA ====================

    def _detect_market_regime(self, indicators: dict) -> str:
        """ADX bazlı market rejimi algılama."""
        cfg = self.criteria.get("market_regime", {})
        if not cfg.get("enabled", False):
            return "unknown"

        adx_val = indicators.get("adx_last", float("nan"))
        if math.isnan(adx_val):
            return "unknown"

        trend_th = cfg.get("trend_threshold", 25)
        range_th = cfg.get("range_threshold", 20)

        if adx_val >= trend_th:
            return "trending"
        elif adx_val <= range_th:
            return "ranging"
        else:
            return "transition"

    def _get_dynamic_weights(self, regime: str) -> dict:
        """Market rejimine göre dinamik ağırlıklar döndürür."""
        if regime == "unknown":
            # Varsayılan ağırlıklar
            return {name: cfg.get("weight", 1)
                    for name, cfg in self.criteria.items()
                    if cfg.get("enabled", False)}

        base = {}
        for name, cfg in self.criteria.items():
            if not cfg.get("enabled", False):
                continue
            w = cfg.get("weight", 1)
            base[name] = w

        if regime == "trending":
            # Trend piyasasında: trend kriterlerine daha fazla ağırlık
            for name in ["trend_filter", "ema_cross", "macd"]:
                if name in base:
                    base[name] = max(base[name], int(base[name] * 1.5))
            # Bollinger ve StochRSI ağırlığını azalt
            for name in ["bollinger", "stoch_rsi"]:
                if name in base:
                    base[name] = max(1, base[name] - 1)

        elif regime == "ranging":
            # Yatay piyasada: osilatörlere daha fazla ağırlık
            for name in ["bollinger", "stoch_rsi", "rsi"]:
                if name in base:
                    base[name] = base[name] + 1
            # Trend kriterlerinin ağırlığını azalt
            for name in ["trend_filter", "ema_cross"]:
                if name in base:
                    base[name] = max(1, base[name] - 1)

        return base

    # ==================== VOLATİLİTE BAZLI DİNAMİK EŞİK ====================

    def _apply_adaptive_volume_threshold(self, cfg: dict, indicators: dict) -> dict:
        """ATR'ye göre hacim eşiğini dinamik ayarla."""
        atr_val = indicators.get("atr_last", float("nan"))
        atr_avg = indicators.get("atr_avg", float("nan"))

        if math.isnan(atr_val) or math.isnan(atr_avg) or atr_avg == 0:
            return cfg

        # ATR ortalamanın üstündeyse → yüksek volatilite → eşiği yükselt
        # ATR ortalamanın altındaysa → düşük volatilite → eşiği düşür
        cfg = dict(cfg)  # Kopyala, orijinali değiştirme
        if atr_val > atr_avg:
            cfg["multiplier"] = 2.0
        else:
            cfg["multiplier"] = 1.3

        return cfg

    # ==================== ZAMAN FİLTRESİ ====================

    def _check_time_filter(self, df: pd.DataFrame) -> bool:
        """
        Mevcut saatin düşük hacimli seans olup olmadığını kontrol eder.
        Returns: True = düşük hacimli saat (sinyal kalitesi düşük)
        """
        cfg = self.criteria.get("time_filter", {})
        if not cfg.get("enabled", False):
            return False

        # Son mumun saatini al (UTC)
        try:
            last_time = df.index[-1]
            current_hour = last_time.hour

            high_vol_hours = cfg.get("high_volume_hours_utc", [(13, 21)])
            for start_h, end_h in high_vol_hours:
                if start_h <= current_hour < end_h:
                    return False  # Yüksek hacimli saat

            return True  # Düşük hacimli saat
        except Exception:
            return False

    # ==================== BTC FİLTRESİ ====================

    def _check_btc_filter(self, btc_df: pd.DataFrame) -> bool:
        """
        BTC'nin düşüş trendinde olup olmadığını kontrol eder.
        Returns: True = BTC düşüşte (altcoin sinyallerini baskıla)
        """
        if btc_df is None or len(btc_df) < 50:
            return False

        try:
            close = btc_df["close"]
            # BTC'nin son 20 mumda EMA9 < EMA21 ise düşüş trendi
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()

            ema9_now = float(ema9.iloc[-1])
            ema21_now = float(ema21.iloc[-1])

            # Ek: Son 5 mumda sürekli düşüş
            recent_close = close.tail(5)
            downtrend = all(recent_close.iloc[i] <= recent_close.iloc[i-1]
                          for i in range(1, len(recent_close)))

            return ema9_now < ema21_now and downtrend
        except Exception:
            return False

    # ==================== CONFLUENCE WINDOW ====================

    def _update_confluence_state(self, symbol: str, required_name: str, criteria_met: list):
        """OCC tetiklenme durumunu günceller (confluence window için)."""
        if required_name == "occ" and "occ" in criteria_met:
            self._occ_trigger_candles[symbol] = 0
        elif symbol in self._occ_trigger_candles:
            self._occ_trigger_candles[symbol] += 1

    def _check_confluence_window(self, symbol: str, criteria_met: list,
                                  conf_cfg: dict) -> bool:
        """
        OCC tetiklendikten sonra pencere içinde diğer kriterlerin
        tamamlanıp tamamlanmadığını kontrol eder.
        """
        window = conf_cfg.get("window_candles", 3)

        if "occ" in criteria_met:
            # OCC bu mumda tetiklendi, pencereyi başlat
            self._occ_trigger_candles[symbol] = 0
            return True  # İlk mumda tüm kriterler de sağlanıyorsa geçerli

        # OCC daha önce tetiklendi mi?
        if symbol in self._occ_trigger_candles:
            candles_since = self._occ_trigger_candles[symbol]
            if candles_since <= window:
                # Pencere içindeyiz, OCC olmasa da diğer kriterler yeterliyse geçerli
                self._occ_trigger_candles[symbol] = candles_since + 1
                return True
            else:
                # Pencere kapandı
                del self._occ_trigger_candles[symbol]

        return False

    # ==================== ÇIKIŞ STRATEJİSİ PUANLAMASI ====================

    def _calculate_exit_score(self, df: pd.DataFrame, indicators: dict) -> tuple:
        """
        Çıkış stratejisi puanlaması.
        Returns: (score, details_dict)
        """
        exit_cfg = self.criteria.get("exit_strategy", {})
        if not exit_cfg.get("enabled", False):
            return 0, {}

        score = 0
        details = {}

        # 1. OCC Ters Kesişim (Close MA < Open MA olarak dönüyor)
        close_ma = indicators.get("occ_close_ma")
        open_ma = indicators.get("occ_open_ma")
        if close_ma is not None and open_ma is not None:
            c_now = _safe_float(close_ma, -2)
            o_now = _safe_float(open_ma, -2)
            c_prev = _safe_float(close_ma, -3)
            o_prev = _safe_float(open_ma, -3)

            if not any(math.isnan(v) for v in [c_now, o_now, c_prev, o_prev]):
                # Aşağı kesişim: Close MA, Open MA'nın altına iniyor
                cross_down = c_now < o_now and c_prev >= o_prev
                if cross_down:
                    w = exit_cfg.get("occ_reverse_weight", 2)
                    score += w
                    details["occ_reverse"] = {
                        "met": True,
                        "detail": f"OCC ters kesişim (CloseMA < OpenMA)",
                        "weight": w,
                    }

        # 2. RSI Aşırı Alım
        rsi_val = _safe_float(indicators.get("rsi", pd.Series()), -1)
        if not math.isnan(rsi_val):
            overbought = self.criteria.get("rsi", {}).get("overbought", 70)
            if rsi_val >= overbought:
                w = exit_cfg.get("rsi_overbought_weight", 1)
                score += w
                details["rsi_overbought"] = {
                    "met": True,
                    "detail": f"RSI aşırı alım ({rsi_val:.1f})",
                    "weight": w,
                }

        # 3. Hacim Düşüşü (son 3 mumda azalan hacim)
        vol_ratio = _safe_float(indicators.get("vol_ratio", pd.Series()), -1)
        if not math.isnan(vol_ratio) and vol_ratio < 0.7:
            w = exit_cfg.get("volume_drop_weight", 1)
            score += w
            details["volume_drop"] = {
                "met": True,
                "detail": f"Hacim düşüşü ({vol_ratio:.1f}x)",
                "weight": w,
            }

        # 4. Stochastic RSI Aşırı Alım
        k_val = _safe_float(indicators.get("stoch_rsi_k", pd.Series()), -1)
        d_val = _safe_float(indicators.get("stoch_rsi_d", pd.Series()), -1)
        if not math.isnan(k_val) and not math.isnan(d_val):
            stoch_ob = self.criteria.get("stoch_rsi", {}).get("overbought", 80)
            cross_down = k_val < d_val
            in_overbought = k_val >= stoch_ob or d_val >= stoch_ob
            if cross_down and in_overbought:
                w = exit_cfg.get("stoch_overbought_weight", 1)
                score += w
                details["stoch_overbought"] = {
                    "met": True,
                    "detail": f"StochRSI aşırı alımda aşağı kesişim (K={k_val:.1f})",
                    "weight": w,
                }

        return score, details

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

        # ADX (Average Directional Index) - Market Rejimi
        regime_cfg = self.criteria.get("market_regime", {})
        if regime_cfg.get("enabled", False):
            adx_period = regime_cfg.get("adx_period", 14)
            ind["adx"], ind["plus_di"], ind["minus_di"] = self._calculate_adx(
                high, low, close, adx_period
            )
            ind["adx_last"] = _safe_float(ind["adx"], -1)
        else:
            ind["adx_last"] = float("nan")

        # ATR (Average True Range) - Volatilite Ölçümü
        ind["atr"] = self._calculate_atr(high, low, close, period=14)
        ind["atr_avg"] = float(ind["atr"].rolling(20).mean().iloc[-1]) if len(ind["atr"].dropna()) >= 20 else float("nan")
        ind["atr_last"] = _safe_float(ind["atr"], -1)

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

    def _calculate_adx(self, high: pd.Series, low: pd.Series,
                       close: pd.Series, period: int = 14) -> tuple:
        """ADX, +DI, -DI hesaplar."""
        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        # Smoothed TR, +DM, -DM (Wilder's smoothing)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        smooth_plus = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        smooth_minus = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        # +DI, -DI
        plus_di = (smooth_plus / atr.replace(0, np.nan)) * 100
        minus_di = (smooth_minus / atr.replace(0, np.nan)) * 100

        # DX ve ADX
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        return adx, plus_di, minus_di

    def _calculate_atr(self, high: pd.Series, low: pd.Series,
                       close: pd.Series, period: int = 14) -> pd.Series:
        """ATR (Average True Range) hesaplar."""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()

    # ==================== MULTI-TIMEFRAME DOĞRULAMA ====================

    def _check_multi_timeframe(self, htf_df: pd.DataFrame, indicators: dict) -> dict:
        """Üst zaman diliminde trend yönü doğrulaması."""
        if htf_df is None or len(htf_df) < 50:
            return {
                "met": False,
                "detail": "Üst TF verisi yok",
                "description": "Multi-TF doğrulanamadı",
            }

        try:
            htf_close = htf_df["close"]
            htf_ema9 = htf_close.ewm(span=9, adjust=False).mean()
            htf_ema21 = htf_close.ewm(span=21, adjust=False).mean()
            htf_ema200 = htf_close.ewm(span=200, adjust=False).mean()

            ema9_now = float(htf_ema9.iloc[-1])
            ema21_now = float(htf_ema21.iloc[-1])
            ema200_now = float(htf_ema200.iloc[-1])
            htf_price = float(htf_close.iloc[-1])

            # Üst TF'de trend yukarı mı?
            uptrend = (ema9_now > ema21_now and htf_price > ema200_now)

            higher_tf = self.criteria.get("multi_timeframe", {}).get("higher_tf", "4h")

            return {
                "met": uptrend,
                "detail": f"{higher_tf} EMA9={ema9_now:.2f}, EMA21={ema21_now:.2f}, Fiyat {'>' if htf_price > ema200_now else '<'} EMA200",
                "description": f"{higher_tf} trend {'yükseliş' if uptrend else 'düşüş'}",
            }
        except Exception as e:
            return {
                "met": False,
                "detail": f"MTF hesaplama hatası: {e}",
                "description": "Multi-TF doğrulanamadı",
            }

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
        if oversold_bounce:
            desc = "RSI aşırı satımdan çıkış (güçlü sinyal)"
        elif in_buy_zone:
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
        bb_middle = _safe_float(ind["bb_middle"], -1)
        bb_pct = _safe_float(ind["bb_pct"], -1)

        if math.isnan(bb_lower) or math.isnan(bb_upper) or math.isnan(bb_pct):
            return {"met": False, "detail": "Bollinger verisi yetersiz", "description": "Hesaplanamadı"}

        # Alt banda dokunma veya altına inme
        touch_lower = close <= bb_lower * 1.005  # %0.5 tolerans
        # Orta bandın (20 SMA) üstüne çıkış — Trend filtresiyle uyum
        prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close
        cross_middle_up = prev_close <= bb_middle and close > bb_middle

        met = touch_lower or cross_middle_up

        if touch_lower:
            desc = "Alt banda temas"
        elif cross_middle_up:
            desc = "Orta band üstüne çıkış (trend doğrulama)"
        else:
            desc = "Band içinde"

        return {
            "met": met,
            "detail": f"BB%={bb_pct:.2f}, Alt={bb_lower:.4f}, Orta={bb_middle:.4f}, Üst={bb_upper:.4f}",
            "description": desc,
        }

    def _check_volume_spike(self, df, ind, cfg) -> dict:
        """Hacim artışı kontrolü (ATR-adaptif eşik)."""
        vol_ratio = _safe_float(ind["vol_ratio"], -1)

        if math.isnan(vol_ratio):
            return {"met": False, "detail": "Hacim verisi yetersiz", "description": "Hesaplanamadı"}

        multiplier = cfg["multiplier"]
        met = vol_ratio >= multiplier

        return {
            "met": met,
            "detail": f"Hacim oranı={vol_ratio:.1f}x (eşik: {multiplier}x)",
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
