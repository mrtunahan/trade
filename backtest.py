# ============================================================================
# backtest.py - Backtest Motoru
# ============================================================================
# Tarihi veri üzerinde strateji performansını ölçer.
# Look-ahead bias ve overfitting kontrolü ile gerçekçi sonuçlar üretir.
#
# Kullanım:
#   python backtest.py                          (varsayılan 3 adımlı test)
#   python backtest.py --step 1                 (sadece Adım 1)
#   python backtest.py --symbol BTCUSDT         (tek parite)
#   python backtest.py --days 90                (son 90 gün)
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

from config import CRITERIA, KLINE_INTERVAL, KLINE_LIMIT, MIN_SIGNAL_STRENGTH_PCT
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
        """Her işlemden beklenen ortalama kâr/zarar (%)."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades

    def print_summary(self):
        """Sonuç özetini yazdırır."""
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
        print(f"  Ort. Süre        : {self.avg_duration_hours:.1f} saat")
        print(f"  Toplam Bar       : {self.total_bars}")
        print(f"{'─' * 70}")

        if self.win_rate > 65:
            print(f"  ⚠️  UYARI: Win rate %{self.win_rate:.0f} > %65 — Overfitting riski!")
            print(f"  ⚠️  Gerçekçi hedef: %55-%65 arası")
        if self.total_trades < 30:
            print(f"  ⚠️  UYARI: {self.total_trades} işlem istatistiksel olarak yetersiz (min 30+)")


# ==================== BACKTEST MOTORU ====================
class BacktestEngine:
    """
    Bar-by-bar (Walk-Forward) backtest motoru.

    Look-ahead bias önleme:
    - Her bar sadece o ana kadar mevcut veriyle analiz edilir
    - Gelecek veriye erişim yok
    - OCC zaten non-repaint (iloc[-2] kullanır)

    Çıkış stratejileri:
    1. Exit Strategy puanlaması (OCC reverse, RSI overbought, vb.)
    2. Stop-loss: ATR bazlı (%2 veya 2xATR)
    3. Take-profit: ATR bazlı (%4 veya 3xATR)
    4. Zaman bazlı timeout (max 48 bar = 48 saat for 1h)
    """

    # Zaman dilimi → dakika eşlemesi
    TF_MINUTES = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
    }

    def __init__(self, criteria_override: dict = None,
                 min_strength_pct: float = None,
                 timeframe: str = None,
                 stop_loss_pct: float = 2.0,
                 take_profit_pct: float = 4.0,
                 max_hold_bars: int = 48):
        """
        Args:
            criteria_override: Özel kriter konfigürasyonu (None=varsayılan)
            min_strength_pct: Minimum sinyal gücü eşiği (None=config'den)
            timeframe: Zaman dilimi (None=config'den)
            stop_loss_pct: Stop-loss yüzdesi
            take_profit_pct: Take-profit yüzdesi
            max_hold_bars: Maksimum pozisyon tutma süresi (bar)
        """
        self.criteria = criteria_override or deepcopy(CRITERIA)
        self.min_strength_pct = min_strength_pct or MIN_SIGNAL_STRENGTH_PCT
        self.timeframe = timeframe or KLINE_INTERVAL
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_bars = max_hold_bars
        self.market = MarketData()

    def run(self, symbols: list, label: str = "Backtest",
            lookback_bars: int = 500) -> BacktestResult:
        """
        Belirtilen semboller üzerinde backtest çalıştırır.

        Args:
            symbols: Test edilecek sembol listesi
            label: Sonuç etiketi
            lookback_bars: Kaç bar geriye bakılacak

        Returns: BacktestResult
        """
        all_trades = []
        total_bars = 0

        for symbol in symbols:
            logger.info(f"Backtest: {symbol} ({self.timeframe})...")
            trades, bars = self._backtest_symbol(symbol, lookback_bars)
            all_trades.extend(trades)
            total_bars += bars

        result = BacktestResult(
            label=label,
            trades=all_trades,
            total_bars=total_bars,
            timeframe=self.timeframe,
        )
        return result

    def _backtest_symbol(self, symbol: str, lookback_bars: int) -> tuple:
        """
        Tek sembol için bar-by-bar backtest.
        Returns: (trades_list, bars_scanned)
        """
        # Veri çek
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

        # BTC veri
        btc_df = None
        btc_cfg = self.criteria.get("btc_filter", {})
        if btc_cfg.get("enabled", False):
            btc_df = self.market.get_klines("BTCUSDT", interval=self.timeframe, limit=lookback_bars)

        trades = []
        active_trade = None
        min_warmup = 200  # İndikatörlerin ısınması için ilk N bar atla

        # Her bar analiz et
        analyzer = TechnicalAnalyzer(criteria=self.criteria, min_strength_pct=self.min_strength_pct)

        for bar_idx in range(min_warmup, len(df)):
            # Sadece o ana kadar olan veriyi ver (look-ahead bias önleme)
            window = df.iloc[:bar_idx + 1]
            current_bar = df.iloc[bar_idx]
            current_time = df.index[bar_idx]
            current_close = float(current_bar["close"])
            current_high = float(current_bar["high"])
            current_low = float(current_bar["low"])

            # HTF penceresi (varsa)
            htf_window = None
            if htf_df is not None and len(htf_df) > 50:
                # HTF'de mevcut zamana kadar olan veriyi al
                htf_window = htf_df[htf_df.index <= current_time]
                if len(htf_window) < 50:
                    htf_window = None

            # BTC penceresi (varsa)
            btc_window = None
            if btc_df is not None and len(btc_df) > 50:
                btc_window = btc_df[btc_df.index <= current_time]
                if len(btc_window) < 50:
                    btc_window = None

            # Aktif pozisyon varsa çıkış kontrol et
            if active_trade is not None:
                bars_held = bar_idx - active_trade._entry_bar_idx
                entry_price = active_trade.entry_price

                # 1. Stop-loss kontrolü (dinamik — ADX bazlı)
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

                # 2. Take-profit kontrolü (dinamik — ADX bazlı)
                tp_pct = active_trade._tp_pct
                tp_price = entry_price * (1 + tp_pct / 100)
                if current_high >= tp_price:
                    active_trade.exit_price = tp_price
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Take-Profit ({tp_pct:.1f}%)"
                    active_trade.pnl_pct = tp_pct * active_trade._pos_size
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # 3. Exit strategy puanlaması
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

                # 4. Zaman bazlı timeout
                if bars_held >= self.max_hold_bars:
                    pnl = ((current_close - entry_price) / entry_price) * 100 * active_trade._pos_size
                    active_trade.exit_price = current_close
                    active_trade.exit_time = current_time
                    active_trade.exit_reason = f"Timeout ({self.max_hold_bars} bar)"
                    active_trade.pnl_pct = pnl
                    active_trade.duration_hours = bars_held * self.TF_MINUTES.get(self.timeframe, 60) / 60
                    trades.append(active_trade)
                    active_trade = None
                    continue

                # Pozisyon hâlâ açık, sinyal aramaya gerek yok
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
                # Dinamik SL/TP: sinyalden al (varsa), yoksa engine default
                trade._sl_pct = getattr(signal, "stop_loss_pct", self.stop_loss_pct)
                trade._tp_pct = getattr(signal, "take_profit_pct", self.take_profit_pct)
                trade._pos_size = getattr(signal, "position_size_pct", 1.0)
                active_trade = trade

        # Açık kalan pozisyonu kapat (son bar'da)
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

        # Rate limit
        time.sleep(0.5)
        return trades, bars_scanned


# ==================== ADIM KONFİGÜRASYONLARI ====================

def make_step1_criteria() -> dict:
    """
    Adım 1: İzole Test — Sadece ADX + EMA + Hacim üçlüsü.
    Diğer tüm kriterler devre dışı.
    """
    c = deepcopy(CRITERIA)

    # Tüm kriterleri kapat
    for name in c:
        if isinstance(c[name], dict):
            c[name]["enabled"] = False

    # Sadece bu üçlüyü aç
    c["market_regime"]["enabled"] = True   # ADX (market rejimi)
    c["ema_cross"]["enabled"] = True       # EMA 9/21 crossover
    c["ema_cross"]["weight"] = 2
    c["volume_spike"]["enabled"] = True    # Hacim patlaması
    c["volume_spike"]["weight"] = 2
    c["trend_filter"]["enabled"] = True    # EMA 200 trend
    c["trend_filter"]["weight"] = 2

    # OCC'yi de aç ama required=False yap (izole test)
    c["occ"]["enabled"] = True
    c["occ"]["required"] = False
    c["occ"]["weight"] = 2

    # Filtreler kapalı
    c["btc_filter"]["enabled"] = False
    c["time_filter"]["enabled"] = False
    c["multi_timeframe"]["enabled"] = False
    c["confluence_window"]["enabled"] = False
    c["candle_cooldown"]["enabled"] = False

    return c


def make_step2_criteria() -> dict:
    """
    Adım 2: Filtre Ekleme — Adım 1 + BTC Filtresi + Zaman Filtresi.
    Amaç: Filtrelerin sinyal sayısını mı yoksa kârlılığı mı etkilediğini ölçmek.
    """
    c = make_step1_criteria()

    # BTC ve zaman filtrelerini ekle
    c["btc_filter"]["enabled"] = True
    c["time_filter"]["enabled"] = True
    c["time_filter"]["low_volume_penalty"] = True

    return c


def make_step3a_criteria() -> dict:
    """
    Adım 3a: 1H/4H Timeframe Uyumu.
    Tam strateji + 1H ana TF, 4H üst TF.
    Backtest için confluence window ve candle cooldown kapalı
    (bu zamanlama filtreleri real-time'da anlamlı, backtest'te state sorunu yaratır).
    """
    c = deepcopy(CRITERIA)
    c["multi_timeframe"]["enabled"] = True
    c["multi_timeframe"]["higher_tf"] = "4h"
    c["occ"]["required"] = False       # Backtest'te zorunlu kriter kaldır
    c["confluence_window"]["enabled"] = False  # Bar-by-bar state sorunu
    c["candle_cooldown"]["enabled"] = False     # Bar-by-bar state sorunu
    return c


def make_full_criteria() -> dict:
    """Tam strateji (mevcut config, backtest uyumlu)."""
    c = deepcopy(CRITERIA)
    c["occ"]["required"] = False       # Backtest'te gevşet
    c["confluence_window"]["enabled"] = False
    c["candle_cooldown"]["enabled"] = False
    return c


# ==================== KARŞILAŞTIRMA RAPORU ====================

def print_comparison(results: list):
    """Birden fazla backtest sonucunu yan yana karşılaştırır."""
    print(f"\n{'=' * 90}")
    print(f"  KARŞILAŞTIRMA TABLOSU")
    print(f"{'=' * 90}")

    headers = ["Metrik"]
    for r in results:
        # Etiketi kısalt
        short_label = r.label[:25] if len(r.label) > 25 else r.label
        headers.append(short_label)

    # Tablo formatı
    col_w = max(28, max(len(h) + 2 for h in headers))
    header_line = f"  {'Metrik':<28}"
    for r in results:
        short_label = r.label[:col_w - 2] if len(r.label) > col_w - 2 else r.label
        header_line += f" | {short_label:>{col_w - 2}}"
    print(header_line)
    print(f"  {'─' * 28}" + (f" | {'─' * (col_w - 2)}" * len(results)))

    metrics = [
        ("Toplam İşlem", lambda r: f"{r.total_trades}"),
        ("Win Rate (%)", lambda r: f"{r.win_rate:.1f}%"),
        ("Toplam PnL (%)", lambda r: f"{r.total_pnl:+.2f}%"),
        ("Beklenti/Trade (%)", lambda r: f"{r.expectancy:+.3f}%"),
        ("Profit Factor", lambda r: f"{r.profit_factor:.2f}"),
        ("Max Drawdown (%)", lambda r: f"{r.max_drawdown:.2f}%"),
        ("Ort. Kazanç (%)", lambda r: f"{r.avg_win:+.2f}%"),
        ("Ort. Kayıp (%)", lambda r: f"{r.avg_loss:+.2f}%"),
        ("Ort. Süre (saat)", lambda r: f"{r.avg_duration_hours:.1f}"),
    ]

    for name, fn in metrics:
        line = f"  {name:<28}"
        for r in results:
            line += f" | {fn(r):>{col_w - 2}}"
        print(line)

    print(f"{'─' * 90}")

    # En iyi sonuç analizi
    print(f"\n  📊 ANALİZ:")
    best_pnl = max(results, key=lambda r: r.total_pnl)
    best_wr = max(results, key=lambda r: r.win_rate)
    best_pf = max(results, key=lambda r: r.profit_factor if r.profit_factor != float("inf") else 0)

    print(f"  • En yüksek PnL         : {best_pnl.label} ({best_pnl.total_pnl:+.2f}%)")
    print(f"  • En yüksek Win Rate    : {best_wr.label} ({best_wr.win_rate:.1f}%)")
    print(f"  • En iyi Profit Factor  : {best_pf.label} ({best_pf.profit_factor:.2f})")

    # Overfitting uyarısı
    for r in results:
        if r.win_rate > 70 and r.total_trades > 5:
            print(f"\n  ⚠️  DİKKAT: '{r.label}' — Win rate %{r.win_rate:.0f} aşırı yüksek!")
            print(f"     Bu muhtemelen overfitting veya yetersiz sample size göstergesidir.")
            print(f"     Gerçekçi hedef: %55-%65 arası sürdürülebilir win rate.")

    if any(r.total_trades < 20 for r in results):
        print(f"\n  ⚠️  UYARI: Bazı testlerde işlem sayısı < 20.")
        print(f"     İstatistiksel güvenilirlik için minimum 30+ işlem önerilir.")
        print(f"     Daha fazla sembol veya daha uzun zaman aralığı kullanın.")


# ==================== ANA FONKSİYON ====================

def get_test_symbols(market: MarketData, max_symbols: int = 20) -> list:
    """En yüksek hacimli sembolleri seçer."""
    all_pairs = market.get_all_pairs()
    combined = all_pairs["USDT"][:max_symbols]  # USDT çiftleri genelde daha likit
    if not combined:
        combined = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    filtered = market.filter_by_volume(combined)
    return filtered[:max_symbols]


def run_step1(symbols: list, lookback: int) -> BacktestResult:
    """Adım 1: ADX + EMA + Hacim izole testi."""
    logger.info("=" * 60)
    logger.info("ADIM 1: İzole Test — ADX + EMA + Hacim")
    logger.info("=" * 60)

    engine = BacktestEngine(
        criteria_override=make_step1_criteria(),
        min_strength_pct=0.60,  # İzole testte düşük eşik (daha az kriter var)
        stop_loss_pct=2.5,
        take_profit_pct=5.0,
        max_hold_bars=48,
    )
    result = engine.run(symbols, label="Adım 1: ADX+EMA+Hacim (İzole)", lookback_bars=lookback)
    result.print_summary()
    return result


def run_step2(symbols: list, lookback: int) -> BacktestResult:
    """Adım 2: Adım 1 + BTC Filtre + Zaman Filtresi."""
    logger.info("=" * 60)
    logger.info("ADIM 2: Filtre Ekleme — ADX+EMA+Hacim + BTC + Zaman")
    logger.info("=" * 60)

    engine = BacktestEngine(
        criteria_override=make_step2_criteria(),
        min_strength_pct=0.60,
        stop_loss_pct=2.5,
        take_profit_pct=5.0,
        max_hold_bars=48,
    )
    result = engine.run(symbols, label="Adım 2: +BTC/Zaman Filtre", lookback_bars=lookback)
    result.print_summary()
    return result


def run_step3(symbols: list, lookback: int) -> BacktestResult:
    """Adım 3: 1H/4H Timeframe Uyumu (Tam Strateji, bonus olarak MTF)."""
    logger.info("=" * 60)
    logger.info("ADIM 3: 1H/4H Timeframe Uyumu (Tam Strateji)")
    logger.info("=" * 60)
    logger.info("15M/1H backtest'te zarar etti (PF 0.92) → devre dışı")

    engine = BacktestEngine(
        criteria_override=make_step3a_criteria(),
        min_strength_pct=0.65,
        timeframe="1h",
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        max_hold_bars=48,
    )
    result = engine.run(symbols, label="Adım 3: 1H/4H (Tam)", lookback_bars=lookback)
    result.print_summary()
    return result


def run_full(symbols: list, lookback: int) -> BacktestResult:
    """Mevcut tam strateji testi."""
    logger.info("=" * 60)
    logger.info("TAM STRATEJİ: Mevcut config aynen")
    logger.info("=" * 60)

    engine = BacktestEngine(
        criteria_override=make_full_criteria(),
        min_strength_pct=0.70,  # 12 puanlık sistemde ~9/12 = %75 → backtest'te %70
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        max_hold_bars=48,
    )
    result = engine.run(symbols, label="Tam Strateji (Mevcut)", lookback_bars=lookback)
    result.print_summary()
    return result


def main():
    parser = argparse.ArgumentParser(description="BinanceTR Trade Scanner Backtester")
    parser.add_argument("--step", type=int, choices=[1, 2, 3], default=0,
                        help="Sadece belirli adımı çalıştır (1, 2 veya 3)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Tek sembol testi (örn: BTCUSDT)")
    parser.add_argument("--symbols", type=int, default=10,
                        help="Test edilecek maksimum sembol sayısı (varsayılan: 10)")
    parser.add_argument("--bars", type=int, default=1000,
                        help="Geriye bakılacak bar sayısı (varsayılan: 1000)")
    parser.add_argument("--full-only", action="store_true",
                        help="Sadece mevcut tam stratejiyi test et")
    args = parser.parse_args()

    print(f"\n{'═' * 70}")
    print(f"  🔬 BinanceTR Scanner Backtest v1.0")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═' * 70}")

    market = MarketData()

    # Sembol listesi
    if args.symbol:
        symbols = [args.symbol]
        print(f"  Sembol     : {args.symbol}")
    else:
        symbols = get_test_symbols(market, max_symbols=args.symbols)
        print(f"  Semboller  : {len(symbols)} adet")

    print(f"  Lookback   : {args.bars} bar")
    print(f"  Ana TF     : {KLINE_INTERVAL}")
    print(f"{'═' * 70}")

    if not symbols:
        print("❌ Test edilecek sembol bulunamadı!")
        return

    results = []

    if args.full_only:
        result = run_full(symbols, args.bars)
        results.append(result)
    elif args.step == 1:
        results.append(run_step1(symbols, args.bars))
    elif args.step == 2:
        results.append(run_step1(symbols, args.bars))
        results.append(run_step2(symbols, args.bars))
    elif args.step == 3:
        results.append(run_step3(symbols, args.bars))
    else:
        # Tüm adımlar
        results.append(run_step1(symbols, args.bars))
        results.append(run_step2(symbols, args.bars))
        results.append(run_step3(symbols, args.bars))
        results.append(run_full(symbols, args.bars))

    # Karşılaştırma tablosu
    if len(results) > 1:
        print_comparison(results)

    # Trade detayları (ilk 10)
    for result in results:
        if result.trades:
            print(f"\n  📋 Son işlemler ({result.label}):")
            for t in result.trades[-10:]:
                status = "✅" if t.is_win else "❌"
                print(f"    {status} {t.symbol} | {t.entry_time.strftime('%m/%d %H:%M')} → "
                      f"{t.exit_time.strftime('%m/%d %H:%M') if t.exit_time else '?'} | "
                      f"PnL: {t.pnl_pct:+.2f}% | {t.exit_reason} | "
                      f"Güç: {t.signal_strength:.0%} | Rejim: {t.market_regime}")

    print(f"\n{'═' * 70}")
    print(f"  Backtest tamamlandı.")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()
