# ============================================================================
# backtest.py - Hiyerarşik Multi-TF OCC Backtest Motoru
# ============================================================================
# 5 timeframe'de OCC durumunu bar-by-bar replay ile test eder.
# Puan ≥5 + 15dk tetikleyici → giriş. RSI/ADX filtresi.
#
# Kullanım:
#   python backtest.py                          (varsayılan)
#   python backtest.py --symbol BTCTRY          (tek parite)
#   python backtest.py --bars 1000              (lookback)
#   python backtest.py --symbols 15             (parite sayısı)
# ============================================================================

import sys
import time
import math
import logging
import argparse
from copy import deepcopy
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    OCC_TIMEFRAMES, OCC_MIN_SCORE, OCC_PERIOD, OCC_MA_TYPE,
    RSI_CONFIG, ADX_CONFIG, DYNAMIC_STOP_LOSS, ONLY_TRY,
)
from market_data import MarketData
from analyzer import MultiTfOccAnalyzer, _calc_ma, _safe_float

# ==================== LOGLAMA ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Backtest")


# ==================== TRADE KAYDI ====================
@dataclass
class Trade:
    symbol: str
    entry_price: float
    entry_time: datetime
    exit_price: float = 0.0
    exit_time: datetime = None
    exit_reason: str = ""
    pnl_pct: float = 0.0
    duration_hours: float = 0.0
    occ_score: int = 0
    max_score: int = 8
    rsi_at_entry: float = float("nan")
    adx_at_entry: float = float("nan")
    tf_green: list = field(default_factory=list)

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0

    @property
    def is_closed(self) -> bool:
        return self.exit_price > 0


# ==================== BACKTEST SONUÇLARI ====================
@dataclass
class BacktestResult:
    label: str
    trades: list
    total_bars: int = 0

    @property
    def total_trades(self) -> int:
        return len([t for t in self.trades if t.is_closed])

    @property
    def winning_trades(self) -> int:
        return len([t for t in self.trades if t.is_closed and t.is_win])

    @property
    def losing_trades(self) -> int:
        return len([t for t in self.trades if t.is_closed and not t.is_win])

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    @property
    def avg_win(self) -> float:
        wins = [t.pnl_pct for t in self.trades if t.is_closed and t.is_win]
        return np.mean(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl_pct for t in self.trades if t.is_closed and not t.is_win]
        return np.mean(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pct for t in self.trades if t.is_closed and t.is_win)
        gross_loss = abs(sum(t.pnl_pct for t in self.trades if t.is_closed and not t.is_win))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_pct for t in self.trades if t.is_closed)

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        equity = [0.0]
        for t in self.trades:
            if t.is_closed:
                equity.append(equity[-1] + t.pnl_pct)
        peak = equity[0]
        max_dd = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_duration_hours(self) -> float:
        durations = [t.duration_hours for t in self.trades if t.is_closed]
        return np.mean(durations) if durations else 0.0

    @property
    def expectancy(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades

    def print_summary(self):
        print(f"\n{'=' * 70}")
        print(f"  {self.label}")
        print(f"{'=' * 70}")
        print(f"  Toplam İşlem     : {self.total_trades}")
        print(f"  Kazanan          : {self.winning_trades} ({self.win_rate:.1f}%)")
        print(f"  Kaybeden         : {self.losing_trades}")
        print(f"  Toplam PnL       : {self.total_pnl:+.2f}%")
        print(f"  Beklenti (Trade) : {self.expectancy:+.3f}%")
        print(f"  Profit Factor    : {self.profit_factor:.2f}")
        print(f"  Max Drawdown     : {self.max_drawdown:.2f}%")
        print(f"  Ort. Kazanç      : {self.avg_win:+.2f}%")
        print(f"  Ort. Kayıp       : {self.avg_loss:+.2f}%")
        print(f"  Ort. Süre        : {self.avg_duration_hours:.1f} saat ({self.avg_duration_hours/24:.1f} gün)")
        print(f"  Toplam Bar       : {self.total_bars}")
        print(f"{'─' * 70}")

        if self.win_rate > 65 and self.total_trades > 10:
            print(f"  ⚠️  Win rate %{self.win_rate:.0f} > %65 — Overfitting riski!")
        if self.total_trades < 30:
            print(f"  ⚠️  {self.total_trades} işlem — istatistiksel olarak yetersiz (min 30+)")


# ==================== BACKTEST MOTORU ====================
class MultiTfBacktestEngine:
    """
    Multi-TF OCC bar-by-bar backtest motoru.

    15dk bar'ları iterate eder, her bar'da tüm üst TF'lerin
    OCC durumunu hesaplar. Puan ≥5 + 15dk cross → giriş.
    """

    TF_MINUTES = {
        "15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
    }

    def __init__(self, min_score: int = None, max_hold_bars: int = 672):
        self.min_score = min_score or OCC_MIN_SCORE
        # 672 = 7 gün × 24 saat × (60/15) = 672 bar (15dk TF)
        self.max_hold_bars = max_hold_bars
        self.market = MarketData()

    def run(self, symbols: list, label: str = "Backtest",
            lookback_bars: int = 1000) -> BacktestResult:
        all_trades = []
        total_bars = 0

        for symbol in symbols:
            logger.info(f"Backtest: {symbol}...")
            trades, bars = self._backtest_symbol(symbol, lookback_bars)
            all_trades.extend(trades)
            total_bars += bars

        return BacktestResult(label=label, trades=all_trades, total_bars=total_bars)

    def _backtest_symbol(self, symbol: str, lookback_bars: int) -> tuple:
        """Tek sembol için multi-TF backtest."""
        # Tüm TF verilerini çek
        tf_dfs = {}
        for tf, (weight, limit, label) in OCC_TIMEFRAMES.items():
            df = self.market.get_klines(symbol, interval=tf, limit=max(lookback_bars, limit))
            if df is not None and len(df) >= 30:
                tf_dfs[tf] = df
            time.sleep(0.3)

        # 15dk verisi zorunlu (iterate edeceğimiz ana TF)
        df_15m = tf_dfs.get("15m")
        if df_15m is None or len(df_15m) < 100:
            logger.warning(f"{symbol}: 15dk verisi yetersiz")
            return [], 0

        trades = []
        active_trade = None
        min_warmup = 50
        prev_occ_states = {}  # {tf: is_green}

        for bar_idx in range(min_warmup, len(df_15m)):
            current_bar = df_15m.iloc[bar_idx]
            current_time = df_15m.index[bar_idx]
            current_close = float(current_bar["close"])
            current_high = float(current_bar["high"])
            current_low = float(current_bar["low"])

            # Her TF için OCC durumunu hesapla (look-ahead korumalı)
            tf_scores = {}
            total_score = 0
            max_score = 0
            trigger_crossed = False
            tf_green_list = []

            for tf, (weight, _, label) in OCC_TIMEFRAMES.items():
                df_tf = tf_dfs.get(tf)
                if df_tf is None:
                    if tf != "15m":
                        max_score += weight
                    continue

                # Look-ahead koruması: sadece current_time'a kadar olan veriyi kullan
                if tf == "15m":
                    window = df_15m.iloc[:bar_idx + 1]
                else:
                    window = df_tf[df_tf.index <= current_time]
                    if len(window) < 20:
                        if tf != "15m":
                            max_score += weight
                        continue

                # OCC hesapla
                close_ma = _calc_ma(window["close"], OCC_PERIOD, OCC_MA_TYPE)
                open_ma = _calc_ma(window["open"], OCC_PERIOD, OCC_MA_TYPE)

                c_now = _safe_float(close_ma, -2)
                o_now = _safe_float(open_ma, -2)

                if math.isnan(c_now) or math.isnan(o_now):
                    if tf != "15m":
                        max_score += weight
                    continue

                is_green = c_now > o_now
                prev_green = prev_occ_states.get(tf)
                just_crossed = prev_green is not None and prev_green != is_green
                prev_occ_states[tf] = is_green

                if tf == "15m":
                    trigger_crossed = just_crossed and is_green
                else:
                    max_score += weight
                    if is_green:
                        total_score += weight
                        tf_green_list.append(f"{tf}")

            # Aktif pozisyon varsa çıkış kontrol et
            if active_trade is not None:
                bars_held = bar_idx - active_trade._entry_bar_idx
                entry_price = active_trade.entry_price

                # Stop-loss
                sl_pct = active_trade._sl_pct
                sl_price = entry_price * (1 - sl_pct / 100)
                if current_low <= sl_price:
                    active_trade.exit_price = sl_price
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Stop-Loss ({sl_pct:.1f}%)"
                    active_trade.pnl_pct = -sl_pct
                    active_trade.duration_hours = bars_held * 15 / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # ATR Trailing Stop
                trail_cfg = DYNAMIC_STOP_LOSS.get("trailing_stop", {})
                if trail_cfg.get("enabled", False):
                    if current_high > active_trade._trailing_high:
                        active_trade._trailing_high = current_high

                    current_pnl_pct = ((current_high - entry_price) / entry_price) * 100
                    if current_pnl_pct >= trail_cfg.get("activation_pct", 2.0):
                        active_trade._trailing_active = True

                    if active_trade._trailing_active and bar_idx >= 14:
                        atr_mult = trail_cfg.get("atr_multiplier", 2.5)
                        recent = df_15m.iloc[bar_idx - 14:bar_idx + 1]
                        tr_vals = pd.concat([
                            recent["high"] - recent["low"],
                            (recent["high"] - recent["close"].shift(1)).abs(),
                            (recent["low"] - recent["close"].shift(1)).abs(),
                        ], axis=1).max(axis=1)
                        atr_val = float(tr_vals.mean())
                        trail_stop = active_trade._trailing_high - (atr_val * atr_mult)

                        if current_low <= trail_stop:
                            pnl = ((trail_stop - entry_price) / entry_price) * 100
                            active_trade.exit_price = trail_stop
                            active_trade.exit_time = current_time
                            active_trade.exit_reason = f"Trailing Stop ({atr_mult}x ATR)"
                            active_trade.pnl_pct = pnl
                            active_trade.duration_hours = bars_held * 15 / 60
                            trades.append(active_trade)
                            active_trade = None
                            continue

                # Take-profit
                tp_pct = active_trade._tp_pct
                tp_price = entry_price * (1 + tp_pct / 100)
                if current_high >= tp_price and not active_trade._trailing_active:
                    active_trade.exit_price = tp_price
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Take-Profit ({tp_pct:.1f}%)"
                    active_trade.pnl_pct = tp_pct
                    active_trade.duration_hours = bars_held * 15 / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # Timeout (max hold)
                if bars_held >= self.max_hold_bars:
                    pnl = ((current_close - entry_price) / entry_price) * 100
                    active_trade.exit_price = current_close
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Timeout ({bars_held * 15 // 60}h)"
                    active_trade.pnl_pct = pnl
                    active_trade.duration_hours = bars_held * 15 / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                continue

            # Giriş kontrolü
            if total_score >= self.min_score and trigger_crossed:
                # RSI filtresi
                rsi_val = float("nan")
                if RSI_CONFIG.get("enabled") and bar_idx >= 20:
                    close_series = df_15m["close"].iloc[:bar_idx + 1]
                    delta = close_series.diff()
                    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
                    loss_s = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
                    rs = gain / loss_s.replace(0, np.nan)
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_val = _safe_float(rsi_series, -1)

                    # RSI bloğu
                    if not math.isnan(rsi_val) and rsi_val >= RSI_CONFIG.get("block_level", 80):
                        continue

                # ADX
                adx_val = float("nan")
                df_1h = tf_dfs.get("1h")
                if ADX_CONFIG.get("enabled") and df_1h is not None:
                    h_window = df_1h[df_1h.index <= current_time]
                    if len(h_window) >= 30:
                        period = ADX_CONFIG.get("period", 14)
                        high = h_window["high"]
                        low = h_window["low"]
                        close = h_window["close"]
                        tr1 = high - low
                        tr2 = (high - close.shift(1)).abs()
                        tr3 = (low - close.shift(1)).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        plus_dm = high.diff()
                        minus_dm = -low.diff()
                        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
                        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
                        atr = tr.ewm(alpha=1/period, adjust=False).mean()
                        sm_plus = plus_dm.ewm(alpha=1/period, adjust=False).mean()
                        sm_minus = minus_dm.ewm(alpha=1/period, adjust=False).mean()
                        plus_di = (sm_plus / atr.replace(0, np.nan)) * 100
                        minus_di = (sm_minus / atr.replace(0, np.nan)) * 100
                        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
                        adx_series = dx.ewm(alpha=1/period, adjust=False).mean()
                        adx_val = _safe_float(adx_series, -1)

                # SL/TP hesapla
                sl_pct = DYNAMIC_STOP_LOSS.get("base_sl_pct", 3.0)
                tp_pct = DYNAMIC_STOP_LOSS.get("base_tp_pct", 6.0)
                if not math.isnan(adx_val):
                    if adx_val >= DYNAMIC_STOP_LOSS.get("strong_trend_adx", 40):
                        sl_pct = DYNAMIC_STOP_LOSS["trend_sl_pct"]
                        tp_pct = DYNAMIC_STOP_LOSS["trend_tp_pct"]
                    elif adx_val <= DYNAMIC_STOP_LOSS.get("ranging_adx", 20):
                        sl_pct = DYNAMIC_STOP_LOSS["range_sl_pct"]
                        tp_pct = DYNAMIC_STOP_LOSS["range_tp_pct"]

                trade = Trade(
                    symbol=symbol,
                    entry_price=current_close,
                    entry_time=current_time,
                    occ_score=total_score,
                    max_score=max_score,
                    rsi_at_entry=rsi_val,
                    adx_at_entry=adx_val,
                    tf_green=tf_green_list[:],
                )
                trade._entry_bar_idx = bar_idx
                trade._sl_pct = sl_pct
                trade._tp_pct = tp_pct
                trade._trailing_active = False
                trade._trailing_high = current_close
                active_trade = trade

        # Açık kalan pozisyonu kapat
        if active_trade is not None:
            last_bar = df_15m.iloc[-1]
            bars_held = len(df_15m) - 1 - active_trade._entry_bar_idx
            pnl = ((float(last_bar["close"]) - active_trade.entry_price) / active_trade.entry_price) * 100
            active_trade.exit_price = float(last_bar["close"])
            active_trade.exit_time = df_15m.index[-1]
            active_trade.exit_reason = "Backtest Sonu"
            active_trade.pnl_pct = pnl
            active_trade.duration_hours = bars_held * 15 / 60
            trades.append(active_trade)

        bars_scanned = len(df_15m) - min_warmup
        logger.info(f"{symbol}: {len(trades)} işlem, {bars_scanned} bar tarandı")

        time.sleep(0.5)
        return trades, bars_scanned


# ==================== SEMBOL BULUCU ====================

def get_symbols(market: MarketData, max_symbols: int = 15) -> list:
    all_pairs = market.get_all_pairs()
    if ONLY_TRY:
        candidates = all_pairs["TRY"][:max_symbols * 2]
    else:
        candidates = (all_pairs["TRY"] + all_pairs["USDT"])[:max_symbols * 2]
    if not candidates:
        candidates = [
            "BTCTRY", "ETHTRY", "BNBTRY", "XRPTRY", "SOLTRY",
            "BIOTRY", "DOGETRY", "ADATRY", "LINKTRY", "LTCTRY",
        ]
    filtered = market.filter_by_volume(candidates)
    return filtered[:max_symbols]


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(description="Multi-TF OCC Backtest")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--symbols", type=int, default=10)
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--min-score", type=int, default=None)
    args = parser.parse_args()

    max_score = sum(w for tf, (w, _, _) in OCC_TIMEFRAMES.items() if tf != "15m")

    print(f"\n{'═' * 70}")
    print(f"  🎯 Multi-TF OCC Backtest")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  📐 TF'ler: {', '.join(f'{tf}({w}p)' for tf, (w, _, _) in OCC_TIMEFRAMES.items())}")
    print(f"  🎯 Min puan: {args.min_score or OCC_MIN_SCORE}/{max_score}")
    print(f"{'═' * 70}")

    market = MarketData()

    if args.symbol:
        symbols = [args.symbol]
        print(f"  Sembol     : {args.symbol}")
    else:
        symbols = get_symbols(market, max_symbols=args.symbols)
        print(f"  Semboller  : {len(symbols)}")

    print(f"  Lookback   : {args.bars} bar")
    print(f"  Iterate    : 15dk bar'ları")
    print(f"{'═' * 70}")

    if not symbols:
        print("❌ Parite bulunamadı!")
        return

    print(f"\n  Pariteler: {', '.join(symbols)}")

    engine = MultiTfBacktestEngine(
        min_score=args.min_score,
    )

    result = engine.run(
        symbols,
        label=f"Multi-TF OCC (min {args.min_score or OCC_MIN_SCORE}p)",
        lookback_bars=args.bars,
    )
    result.print_summary()

    # Trade detayları
    if result.trades:
        print(f"\n  📋 İşlem Detayları (son 20):")
        for t in result.trades[-20:]:
            status = "✅" if t.is_win else "❌"
            days = t.duration_hours / 24
            rsi_str = f"RSI:{t.rsi_at_entry:.0f}" if t.rsi_at_entry == t.rsi_at_entry else "RSI:?"
            adx_str = f"ADX:{t.adx_at_entry:.0f}" if t.adx_at_entry == t.adx_at_entry else "ADX:?"
            tf_str = ",".join(t.tf_green) if t.tf_green else "?"
            print(f"    {status} {t.symbol} | "
                  f"{t.entry_time.strftime('%m/%d %H:%M')} → "
                  f"{t.exit_time.strftime('%m/%d %H:%M') if t.exit_time else '?'} | "
                  f"PnL: {t.pnl_pct:+.2f}% | {t.exit_reason} | "
                  f"OCC: {t.occ_score}/{t.max_score} [{tf_str}] | "
                  f"{rsi_str} {adx_str} | {days:.1f}gün")

        # Çıkış nedeni dağılımı
        print(f"\n  📊 Çıkış Nedeni Dağılımı:")
        reasons = {}
        for t in result.trades:
            if t.is_closed:
                key = t.exit_reason.split("(")[0].strip()
                if key not in reasons:
                    reasons[key] = {"count": 0, "pnl": 0.0}
                reasons[key]["count"] += 1
                reasons[key]["pnl"] += t.pnl_pct
        for reason, data in sorted(reasons.items(), key=lambda x: x[1]["count"], reverse=True):
            avg_pnl = data["pnl"] / data["count"]
            print(f"    {reason}: {data['count']} işlem, "
                  f"toplam PnL: {data['pnl']:+.2f}%, ort: {avg_pnl:+.2f}%")

        # OCC puan dağılımı
        print(f"\n  📊 OCC Puan Dağılımı (girişteki):")
        score_dist = {}
        for t in result.trades:
            if t.is_closed:
                s = t.occ_score
                if s not in score_dist:
                    score_dist[s] = {"count": 0, "wins": 0, "pnl": 0.0}
                score_dist[s]["count"] += 1
                if t.is_win:
                    score_dist[s]["wins"] += 1
                score_dist[s]["pnl"] += t.pnl_pct
        for score in sorted(score_dist.keys()):
            data = score_dist[score]
            wr = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
            print(f"    {score}/{max_score}p: {data['count']} işlem, "
                  f"WR: {wr:.0f}%, PnL: {data['pnl']:+.2f}%")

    print(f"\n{'═' * 70}")
    print(f"  Backtest tamamlandı.")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()
