# ============================================================================
# backtest.py - OCC Swing Trader Backtest Motoru
# ============================================================================
# Tek strateji: OCC-merkezli swing trading (TRY pariteleri, max 1 hafta)
# Walk-forward, look-ahead bias korumalı bar-by-bar replay.
#
# Kullanım:
#   python backtest.py                          (TRY paritelerinde backtest)
#   python backtest.py --symbol BTCTRY          (tek parite)
#   python backtest.py --bars 1000              (son 1000 bar)
#   python backtest.py --symbols 20             (en fazla 20 parite)
# ============================================================================

import sys
import time
import math
import logging
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    CRITERIA, KLINE_INTERVAL, KLINE_LIMIT, MIN_SIGNAL_STRENGTH_PCT,
    DYNAMIC_STOP_LOSS, MAX_HOLD_BARS,
)
from market_data import MarketData
from analyzer import TechnicalAnalyzer

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
    """Bir simüle edilmiş işlem."""
    symbol: str
    entry_price: float
    entry_time: datetime
    exit_price: float = 0.0
    exit_time: datetime = None
    exit_reason: str = ""
    pnl_pct: float = 0.0
    duration_hours: float = 0.0
    signal_strength: float = 0.0
    market_regime: str = "unknown"
    criteria_met: list = field(default_factory=list)

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0

    @property
    def is_closed(self) -> bool:
        return self.exit_price > 0


# ==================== BACKTEST SONUÇLARI ====================
@dataclass
class BacktestResult:
    """Backtest sonuç istatistikleri."""
    label: str
    trades: list
    total_bars: int = 0
    timeframe: str = "1h"

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

        if self.win_rate > 65:
            print(f"  ⚠️  UYARI: Win rate %{self.win_rate:.0f} > %65 — Overfitting riski!")
        if self.total_trades < 30:
            print(f"  ⚠️  UYARI: {self.total_trades} işlem istatistiksel olarak yetersiz (min 30+)")


# ==================== BACKTEST MOTORU ====================
class BacktestEngine:
    """
    OCC-merkezli swing trader backtest motoru.

    Tek strateji: OCC tetikleyici + doğrulama kriterleri.
    Max 1 hafta tutma süresi. TRY pariteleri.

    Look-ahead bias önleme:
    - Her bar sadece o ana kadar mevcut veriyle analiz edilir
    - OCC non-repaint (iloc[-2] kullanır)
    """

    TF_MINUTES = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
    }

    def __init__(self, criteria_override: dict = None,
                 min_strength_pct: float = None,
                 timeframe: str = None,
                 max_hold_bars: int = None):
        self.criteria = criteria_override or deepcopy(CRITERIA)
        self.min_strength_pct = min_strength_pct or MIN_SIGNAL_STRENGTH_PCT
        self.timeframe = timeframe or KLINE_INTERVAL
        self.max_hold_bars = max_hold_bars or MAX_HOLD_BARS
        self.market = MarketData()

    def run(self, symbols: list, label: str = "Backtest",
            lookback_bars: int = 1000) -> BacktestResult:
        all_trades = []
        total_bars = 0

        for symbol in symbols:
            logger.info(f"Backtest: {symbol} ({self.timeframe})...")
            trades, bars = self._backtest_symbol(symbol, lookback_bars)
            all_trades.extend(trades)
            total_bars += bars

        return BacktestResult(
            label=label,
            trades=all_trades,
            total_bars=total_bars,
            timeframe=self.timeframe,
        )

    def _backtest_symbol(self, symbol: str, lookback_bars: int) -> tuple:
        df = self.market.get_klines(symbol, interval=self.timeframe, limit=lookback_bars)
        if df is None or len(df) < 100:
            logger.warning(f"{symbol}: Yetersiz veri ({len(df) if df is not None else 0} bar)")
            return [], 0

        # HTF veri (multi-timeframe için)
        htf_df = None
        mtf_cfg = self.criteria.get("multi_timeframe", {})
        if mtf_cfg.get("enabled", False):
            higher_tf = mtf_cfg.get("higher_tf", "4h")
            htf_df = self.market.get_klines(symbol, interval=higher_tf, limit=lookback_bars)

        # BTC veri (BTC filtresi için — BTCUSDT veya BTCTRY)
        btc_df = None
        btc_cfg = self.criteria.get("btc_filter", {})
        if btc_cfg.get("enabled", False):
            btc_df = self.market.get_klines("BTCUSDT", interval=self.timeframe, limit=lookback_bars)
            if btc_df is None or len(btc_df) < 50:
                btc_df = self.market.get_klines("BTCTRY", interval=self.timeframe, limit=lookback_bars)

        trades = []
        active_trade = None
        min_warmup = 200

        # Backtest'te confluence_window ve candle_cooldown kapalı
        # (bar-by-bar replay'de state sorunu yaratır)
        bt_criteria = deepcopy(self.criteria)
        bt_criteria["confluence_window"]["enabled"] = False
        bt_criteria["candle_cooldown"]["enabled"] = False

        analyzer = TechnicalAnalyzer(criteria=bt_criteria, min_strength_pct=self.min_strength_pct)

        for bar_idx in range(min_warmup, len(df)):
            window = df.iloc[:bar_idx + 1]
            current_bar = df.iloc[bar_idx]
            current_time = df.index[bar_idx]
            current_close = float(current_bar["close"])
            current_high = float(current_bar["high"])
            current_low = float(current_bar["low"])

            htf_window = None
            if htf_df is not None and len(htf_df) > 50:
                htf_window = htf_df[htf_df.index <= current_time]
                if len(htf_window) < 50:
                    htf_window = None

            btc_window = None
            if btc_df is not None and len(btc_df) > 50:
                btc_window = btc_df[btc_df.index <= current_time]
                if len(btc_window) < 50:
                    btc_window = None

            # Aktif pozisyon varsa çıkış kontrol et
            if active_trade is not None:
                bars_held = bar_idx - active_trade._entry_bar_idx
                entry_price = active_trade.entry_price

                # 1. Stop-loss (dinamik — ADX bazlı)
                sl_pct = active_trade._sl_pct
                sl_price = entry_price * (1 - sl_pct / 100)
                if current_low <= sl_price:
                    active_trade.exit_price = sl_price
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Stop-Loss ({sl_pct:.1f}%)"
                    active_trade.pnl_pct = -sl_pct * active_trade._pos_size
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # 2. ATR Trailing Stop
                trail_cfg = DYNAMIC_STOP_LOSS.get("trailing_stop", {})
                if (trail_cfg.get("enabled", False) and
                        active_trade._regime in ("trending", "transition")):
                    if current_high > active_trade._trailing_high:
                        active_trade._trailing_high = current_high

                    current_pnl_pct = ((current_high - entry_price) / entry_price) * 100
                    activation = trail_cfg.get("activation_pct", 2.0)

                    if current_pnl_pct >= activation:
                        active_trade._trailing_active = True

                    if active_trade._trailing_active:
                        atr_mult = trail_cfg.get("atr_multiplier", 2.5)
                        if bar_idx >= 14:
                            recent = df.iloc[bar_idx - 14:bar_idx + 1]
                            tr_vals = pd.concat([
                                recent["high"] - recent["low"],
                                (recent["high"] - recent["close"].shift(1)).abs(),
                                (recent["low"] - recent["close"].shift(1)).abs(),
                            ], axis=1).max(axis=1)
                            atr_val = float(tr_vals.mean())
                        else:
                            atr_val = entry_price * 0.02

                        trail_stop = active_trade._trailing_high - (atr_val * atr_mult)

                        if current_low <= trail_stop:
                            pnl = ((trail_stop - entry_price) / entry_price) * 100 * active_trade._pos_size
                            active_trade.exit_price = trail_stop
                            active_trade.exit_time = current_time
                            active_trade.exit_reason = f"Trailing Stop ({atr_mult}x ATR)"
                            active_trade.pnl_pct = pnl
                            active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                            trades.append(active_trade)
                            active_trade = None
                            continue

                # 3. Take-profit (trailing yoksa)
                tp_pct = active_trade._tp_pct
                tp_price = entry_price * (1 + tp_pct / 100)
                if current_high >= tp_price and not active_trade._trailing_active:
                    active_trade.exit_price = tp_price
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Take-Profit ({tp_pct:.1f}%)"
                    active_trade.pnl_pct = tp_pct * active_trade._pos_size
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # 4. Exit strategy puanlaması
                exit_sig = analyzer.check_exit_signal(symbol, window)
                if exit_sig and exit_sig.exit_score >= 3:
                    pnl = ((current_close - entry_price) / entry_price) * 100 * active_trade._pos_size
                    active_trade.exit_price = current_close
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Exit Skor ({exit_sig.exit_score}/5)"
                    active_trade.pnl_pct = pnl
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # 5. Zaman bazlı timeout (max 1 hafta)
                if bars_held >= self.max_hold_bars:
                    pnl = ((current_close - entry_price) / entry_price) * 100 * active_trade._pos_size
                    active_trade.exit_price = current_close
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Timeout ({self.max_hold_bars} bar = {self.max_hold_bars//24} gün)"
                    active_trade.pnl_pct = pnl
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                continue

            # Sinyal ara (pozisyon yoksa)
            signal = analyzer.analyze(symbol, window, htf_df=htf_window, btc_df=btc_window)

            if signal and signal.strength_pct >= self.min_strength_pct:
                trade = Trade(
                    symbol=symbol,
                    entry_price=current_close,
                    entry_time=current_time,
                    signal_strength=signal.strength_pct,
                    market_regime=signal.market_regime,
                    criteria_met=signal.criteria_met[:],
                )
                trade._entry_bar_idx = bar_idx
                trade._sl_pct = getattr(signal, "stop_loss_pct", 3.0)
                trade._tp_pct = getattr(signal, "take_profit_pct", 6.0)
                trade._pos_size = getattr(signal, "position_size_pct", 1.0)
                trade._trailing_active = False
                trade._trailing_high = current_close
                trade._regime = signal.market_regime
                active_trade = trade

        # Açık kalan pozisyonu kapat
        if active_trade is not None:
            last_bar = df.iloc[-1]
            bars_held = len(df) - 1 - active_trade._entry_bar_idx
            pnl = ((float(last_bar["close"]) - active_trade.entry_price) / active_trade.entry_price) * 100 * active_trade._pos_size
            active_trade.exit_price = float(last_bar["close"])
            active_trade.exit_time = df.index[-1]
            active_trade.exit_reason = "Backtest Sonu"
            active_trade.pnl_pct = pnl
            active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
            trades.append(active_trade)

        bars_scanned = len(df) - min_warmup
        logger.info(f"{symbol}: {len(trades)} işlem, {bars_scanned} bar tarandı")

        time.sleep(0.5)
        return trades, bars_scanned


# ==================== TRY PARİTE BULUCU ====================

def get_try_symbols(market: MarketData, max_symbols: int = 20) -> list:
    """En yüksek hacimli TRY paritelerini seçer."""
    all_pairs = market.get_all_pairs()
    try_pairs = all_pairs["TRY"][:max_symbols * 2]
    if not try_pairs:
        try_pairs = [
            "BTCTRY", "ETHTRY", "BNBTRY", "XRPTRY", "SOLTRY",
            "AVXTRY", "DOGETRY", "ADATRY", "LINKTRY", "LTCTRY",
        ]
    filtered = market.filter_by_volume(try_pairs)
    return filtered[:max_symbols]


# ==================== ANA FONKSİYON ====================

def main():
    parser = argparse.ArgumentParser(description="OCC Swing Trader Backtest")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Tek sembol testi (örn: BTCTRY)")
    parser.add_argument("--symbols", type=int, default=15,
                        help="Test edilecek maksimum sembol sayısı (varsayılan: 15)")
    parser.add_argument("--bars", type=int, default=1000,
                        help="Geriye bakılacak bar sayısı (varsayılan: 1000)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Min sinyal gücü eşiği (0.0-1.0, varsayılan: config'den)")
    args = parser.parse_args()

    print(f"\n{'═' * 70}")
    print(f"  🎯 OCC Swing Trader Backtest")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  📊 Strateji: OCC-merkezli | Sadece TRY | Max {MAX_HOLD_BARS//24} gün tutma")
    print(f"{'═' * 70}")

    market = MarketData()

    if args.symbol:
        symbols = [args.symbol]
        print(f"  Sembol     : {args.symbol}")
    else:
        symbols = get_try_symbols(market, max_symbols=args.symbols)
        print(f"  Semboller  : {len(symbols)} TRY pariteleri")

    min_pct = args.threshold or MIN_SIGNAL_STRENGTH_PCT
    print(f"  Lookback   : {args.bars} bar")
    print(f"  Timeframe  : {KLINE_INTERVAL}")
    print(f"  Min Güç    : %{min_pct*100:.0f}")
    print(f"  Max Tutma  : {MAX_HOLD_BARS} bar ({MAX_HOLD_BARS//24} gün)")
    print(f"{'═' * 70}")

    if not symbols:
        print("❌ Test edilecek TRY pariteleri bulunamadı!")
        return

    print(f"\n  Pariteler: {', '.join(symbols)}")

    engine = BacktestEngine(
        min_strength_pct=min_pct,
        max_hold_bars=MAX_HOLD_BARS,
    )

    result = engine.run(
        symbols,
        label="OCC Swing Trader (TRY, 1H, Max 7 Gün)",
        lookback_bars=args.bars,
    )
    result.print_summary()

    # Trade detayları
    if result.trades:
        print(f"\n  📋 İşlem Detayları (son 15):")
        for t in result.trades[-15:]:
            status = "✅" if t.is_win else "❌"
            duration_days = t.duration_hours / 24
            print(f"    {status} {t.symbol} | "
                  f"{t.entry_time.strftime('%m/%d %H:%M')} → "
                  f"{t.exit_time.strftime('%m/%d %H:%M') if t.exit_time else '?'} | "
                  f"PnL: {t.pnl_pct:+.2f}% | {t.exit_reason} | "
                  f"Süre: {duration_days:.1f} gün | "
                  f"Güç: {t.signal_strength:.0%} | Rejim: {t.market_regime}")

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
            print(f"    {reason}: {data['count']} işlem, toplam PnL: {data['pnl']:+.2f}%, ort: {avg_pnl:+.2f}%")

    print(f"\n{'═' * 70}")
    print(f"  Backtest tamamlandı.")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()
