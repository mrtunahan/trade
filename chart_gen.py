# ============================================================================
# chart_gen.py - Mini Grafik Oluşturucu
# ============================================================================
# Telegram bildirimine eklenecek küçük grafik görselleri üretir.
# ============================================================================

import io
import logging

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # GUI olmadan çalış
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch

logger = logging.getLogger("ChartGen")

# Stil
plt.rcParams.update({
    "figure.facecolor": "#1a1a2e",
    "axes.facecolor": "#16213e",
    "axes.edgecolor": "#0f3460",
    "axes.labelcolor": "#e0e0e0",
    "text.color": "#e0e0e0",
    "xtick.color": "#a0a0a0",
    "ytick.color": "#a0a0a0",
    "grid.color": "#0f3460",
    "grid.alpha": 0.3,
    "font.size": 10,
})


def generate_signal_chart(symbol: str, df: pd.DataFrame, indicators: dict) -> bytes:
    """
    Sinyal bildirimi için mini grafik üretir.
    Returns: PNG görsel bytes
    """
    try:
        if df is None or len(df) < 10:
            logger.warning(f"{symbol}: Grafik için yeterli veri yok (min 10 mum gerekli)")
            return b""

        # Son 80 mumu göster
        df_plot = df.tail(80).copy()

        fig, axes = plt.subplots(3, 1, figsize=(10, 7), height_ratios=[3, 1, 1],
                                  gridspec_kw={"hspace": 0.05})

        # ==================== 1. PANEL: FİYAT + EMA ====================
        ax1 = axes[0]
        x = range(len(df_plot))

        # Mum renkleri
        colors = ["#00e676" if c >= o else "#ff1744"
                  for o, c in zip(df_plot["open"], df_plot["close"])]

        # Mum gövdeleri
        for i, (idx, row) in enumerate(df_plot.iterrows()):
            body_low = min(row["open"], row["close"])
            body_high = max(row["open"], row["close"])
            body_h = max(body_high - body_low, row["close"] * 0.0005)
            color = colors[i]

            # Fitil
            ax1.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8)
            # Gövde
            ax1.bar(i, body_h, bottom=body_low, width=0.6, color=color, edgecolor=color)

        # EMA çizgileri
        ema9 = indicators.get("ema_9")
        ema21 = indicators.get("ema_21")
        ema200 = indicators.get("ema_200")

        if ema9 is not None:
            ema9_plot = ema9.reindex(df_plot.index).dropna()
            if not ema9_plot.empty:
                positions = [df_plot.index.get_loc(i) for i in ema9_plot.index]
                ax1.plot(positions, ema9_plot.values, color="#42a5f5", linewidth=1.2,
                        label="EMA 9", alpha=0.9)
        if ema21 is not None:
            ema21_plot = ema21.reindex(df_plot.index).dropna()
            if not ema21_plot.empty:
                positions = [df_plot.index.get_loc(i) for i in ema21_plot.index]
                ax1.plot(positions, ema21_plot.values, color="#ffa726", linewidth=1.2,
                        label="EMA 21", alpha=0.9)
        if ema200 is not None:
            ema200_plot = ema200.reindex(df_plot.index).dropna()
            if not ema200_plot.empty:
                positions = [df_plot.index.get_loc(i) for i in ema200_plot.index]
                ax1.plot(positions, ema200_plot.values, color="#78909c", linewidth=1,
                        label="EMA 200", linestyle="--", alpha=0.7)

        # Bollinger Bands
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        if bb_upper is not None and bb_lower is not None:
            bbu = bb_upper.reindex(df_plot.index).fillna(method="bfill")
            bbl = bb_lower.reindex(df_plot.index).fillna(method="bfill")
            mask = bbu.notna() & bbl.notna()
            if mask.any():
                ax1.fill_between(range(len(bbu)), bbu.values, bbl.values,
                                where=mask.values, alpha=0.08, color="#42a5f5")

        # Son fiyat etiketi
        last_price = float(df_plot["close"].iloc[-1])
        ax1.axhline(y=last_price, color="#e0e0e0", linewidth=0.5, linestyle=":", alpha=0.5)
        ax1.text(len(df_plot) + 1, last_price, f" {last_price:,.2f}",
                fontsize=9, color="#ffffff", va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#42a5f5", alpha=0.8))

        # Son muma ok işareti (sinyal noktası)
        ax1.annotate("⬆ AL", xy=(len(df_plot)-1, float(df_plot["low"].iloc[-1])),
                    xytext=(len(df_plot)-1, float(df_plot["low"].iloc[-1]) - (float(df_plot["high"].max()) - float(df_plot["low"].min())) * 0.08),
                    fontsize=11, color="#00e676", fontweight="bold",
                    ha="center", va="top")

        ax1.set_title(f"  {symbol}", fontsize=14, fontweight="bold", loc="left", pad=10)
        ax1.legend(loc="upper left", fontsize=8, framealpha=0.3)
        ax1.set_xlim(-1, len(df_plot) + 5)
        ax1.set_xticks([])
        ax1.grid(True, alpha=0.2)

        # ==================== 2. PANEL: RSI ====================
        ax2 = axes[1]
        rsi = indicators.get("rsi")
        if rsi is not None:
            rsi_plot = rsi.reindex(df_plot.index)
            rsi_vals = rsi_plot.values
            valid_mask = ~np.isnan(rsi_vals)
            ax2.plot(range(len(rsi_vals)), rsi_vals, color="#ce93d8", linewidth=1.2)
            ax2.axhline(y=70, color="#ff1744", linewidth=0.7, linestyle="--", alpha=0.5)
            ax2.axhline(y=30, color="#00e676", linewidth=0.7, linestyle="--", alpha=0.5)
            ax2.fill_between(range(len(rsi_vals)), rsi_vals, 30,
                            where=(valid_mask & (rsi_vals < 30)), alpha=0.15, color="#00e676")
            ax2.fill_between(range(len(rsi_vals)), rsi_vals, 70,
                            where=(valid_mask & (rsi_vals > 70)), alpha=0.15, color="#ff1744")

            last_rsi_val = rsi_vals[valid_mask]
            if len(last_rsi_val) > 0:
                last_rsi = float(last_rsi_val[-1])
                ax2.text(len(rsi_vals) + 1, last_rsi, f" {last_rsi:.0f}",
                        fontsize=9, color="#ce93d8", va="center")

        ax2.set_ylabel("RSI", fontsize=9)
        ax2.set_ylim(10, 90)
        ax2.set_xlim(-1, len(df_plot) + 5)
        ax2.set_xticks([])
        ax2.grid(True, alpha=0.2)

        # ==================== 3. PANEL: HACİM ====================
        ax3 = axes[2]
        volumes = df_plot["volume"].values
        vol_colors = ["#00e676" if c >= o else "#ff1744"
                     for o, c in zip(df_plot["open"], df_plot["close"])]
        ax3.bar(range(len(volumes)), volumes, color=vol_colors, alpha=0.7, width=0.6)

        # Volume MA
        vol_ma = indicators.get("vol_ma")
        if vol_ma is not None:
            vma_plot = vol_ma.reindex(df_plot.index).dropna()
            if not vma_plot.empty:
                positions = [df_plot.index.get_loc(i) for i in vma_plot.index]
                ax3.plot(positions, vma_plot.values, color="#ffa726",
                        linewidth=1, alpha=0.7, label="Vol MA")

        ax3.set_ylabel("Hacim", fontsize=9)
        ax3.set_xlim(-1, len(df_plot) + 5)
        ax3.grid(True, alpha=0.2)

        # X ekseni: seyrek tarih etiketleri
        n = len(df_plot)
        step = max(n // 6, 1)
        tick_positions = list(range(0, n, step))
        tick_labels = [df_plot.index[i].strftime("%d/%m\n%H:%M") for i in tick_positions]
        ax3.set_xticks(tick_positions)
        ax3.set_xticklabels(tick_labels, fontsize=8)

        plt.tight_layout()

        # PNG olarak kaydet
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)

        return buf.read()

    except Exception as e:
        logger.error(f"Grafik oluşturma hatası: {e}", exc_info=True)
        return b""
