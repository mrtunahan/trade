# ============================================================================
# telegram_notifier.py - Hiyerarşik OCC Telegram Bildirimi
# ============================================================================
# Multi-TF OCC durumunu TF heatmap ile gösterir.
# Her renk değişiminde ve alım sinyalinde bildirim gönderir.
# ============================================================================

import io
import logging
from datetime import datetime
from typing import Optional

import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SEND_CHART_IMAGE,
    OCC_MIN_SCORE,
    OCC_TIMEFRAMES,
)

logger = logging.getLogger("Telegram")


class TelegramNotifier:
    """Telegram Bot API ile bildirim gönderici."""

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.session = requests.Session()

    # ==================== TEMEL MESAJ ====================

    def send_message(self, text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
        try:
            resp = self.session.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_preview,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(f"Telegram mesaj hatası: {resp.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"Telegram bağlantı hatası: {e}")
            return False

    def send_photo(self, photo_bytes: bytes, caption: str = "", parse_mode: str = "HTML") -> bool:
        try:
            resp = self.session.post(
                f"{self.api_url}/sendPhoto",
                data={
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "parse_mode": parse_mode,
                },
                files={"photo": ("chart.png", io.BytesIO(photo_bytes), "image/png")},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(f"Telegram fotoğraf hatası: {resp.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"Telegram fotoğraf bağlantı hatası: {e}")
            return False

    # ==================== TF RENK DEĞİŞİMİ ====================

    def send_tf_change(self, symbol: str, tf_status, price: float) -> bool:
        """Tek bir timeframe'deki OCC renk değişimini bildirir."""
        quote = "TRY" if symbol.endswith("TRY") else "USDT"
        base = symbol.replace("TRY", "").replace("USDT", "")

        if tf_status.is_green:
            emoji = "🟢"
            direction = "YEŞİL (Yükseliş)"
            action = "Close MA > Open MA"
        else:
            emoji = "🔴"
            direction = "KIRMIZI (Düşüş)"
            action = "Close MA < Open MA"

        message = (
            f"{emoji} <b>OCC Renk Değişimi</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{base}/{quote}</b> — {tf_status.label} ({tf_status.timeframe})\n"
            f"Yön: <b>{direction}</b>\n"
            f"Güç: {tf_status.strength:+.3f}%\n"
            f"Fiyat: {price:,.4f} {quote}\n"
            f"\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}'>TradingView</a>"
        )

        return self.send_message(message)

    # ==================== ALIM SİNYALİ (Multi-TF) ====================

    def send_multi_tf_signal(self, signal, chart_bytes: Optional[bytes] = None) -> bool:
        """
        Hiyerarşik multi-TF OCC alım sinyalini gönderir.
        TF heatmap + RSI/ADX bilgisi + SL/TP seviyeleri.
        """
        quote = "TRY" if signal.symbol.endswith("TRY") else "USDT"
        base = signal.symbol.replace("TRY", "").replace("USDT", "")

        # TF Heatmap
        heatmap_lines = []
        for ts in signal.tf_statuses:
            icon = "🟢" if ts.is_green else "🔴"
            cross_mark = " ←" if ts.just_crossed else ""
            pts = f"[{ts.weight}p]" if ts.weight > 0 else "[tetik]"
            heatmap_lines.append(
                f"  {icon} <b>{ts.label}</b> ({ts.timeframe}) "
                f"{pts}{cross_mark}"
            )
        heatmap_text = "\n".join(heatmap_lines)

        # Puan seviyesi — yıldız bazlı kalite sistemi
        score = signal.total_score
        max_score = signal.max_score
        rating = signal.signal_star_rating
        stars = rating["stars"]
        score_label = rating["label"]

        # Sinyal başlığı için emoji
        star_count = stars.count("⭐")
        if star_count >= 3:
            score_emoji = "🔥🔥🔥"
        elif star_count >= 2:
            score_emoji = "🔥🔥"
        else:
            score_emoji = "🔥"

        # Eşleşen desen adı
        matched_pattern = getattr(signal, 'matched_pattern_name', '') or ""

        # RSI bilgisi
        rsi_val = signal.rsi_value
        if signal.rsi_quality == "ideal":
            rsi_text = f"RSI {rsi_val:.1f} — Ideal giriş bölgesi"
            rsi_emoji = "✅"
        elif signal.rsi_quality == "caution":
            rsi_text = f"RSI {rsi_val:.1f} — DİKKAT: Hareket zaten olmuş olabilir"
            rsi_emoji = "⚠️"
        elif signal.rsi_quality == "blocked":
            rsi_text = f"RSI {rsi_val:.1f} — Aşırı alım bölgesi"
            rsi_emoji = "🚫"
        else:
            rsi_text = f"RSI {rsi_val:.1f}" if rsi_val == rsi_val else "RSI N/A"
            rsi_emoji = "📊"

        # ADX bilgisi
        adx_val = signal.adx_value
        if signal.adx_regime == "trending":
            adx_text = f"ADX {adx_val:.1f} — Güçlü trend"
            adx_emoji = "📈"
        elif signal.adx_regime == "weak":
            adx_text = f"ADX {adx_val:.1f} — Zayıf/yatay piyasa"
            adx_emoji = "📉"
        else:
            adx_text = f"ADX {adx_val:.1f}" if adx_val == adx_val else "ADX N/A"
            adx_emoji = "📊"

        # SL/TP seviyeleri
        price = signal.price
        sl_pct = signal.stop_loss_pct
        tp_pct = signal.take_profit_pct
        sl_price = price * (1 - sl_pct / 100)
        tp_price = price * (1 + tp_pct / 100)

        # Desen bilgisi satırı
        pattern_line = ""
        if matched_pattern:
            pattern_line = f"🏷 <b>Strateji:</b> {matched_pattern}\n"

        message = (
            f"{score_emoji} <b>ALIM SİNYALİ — {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"🎯 <b>Giriş:</b> {price:,.4f} {quote}\n"
            f"🛑 <b>Stop-Loss:</b> {sl_price:,.4f} (-%{sl_pct:.1f})\n"
            f"💰 <b>Hedef:</b> {tp_price:,.4f} (+%{tp_pct:.1f})\n"
            f"📊 <b>R:R:</b> 1:{tp_pct/sl_pct:.1f}\n"
            f"\n"
            f"<b>OCC Heatmap:</b> {score}/{max_score}p — {stars} {score_label}\n"
            f"{heatmap_text}\n"
            f"\n"
            f"{pattern_line}"
            f"{rsi_emoji} {rsi_text}\n"
            f"{adx_emoji} {adx_text}\n"
            f"💼 Pozisyon: %{signal.position_size_pct*100:.0f} ({signal.position_tier})\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{signal.symbol}'>TradingView</a>"
        )

        if chart_bytes and SEND_CHART_IMAGE:
            return self.send_photo(chart_bytes, caption=message)
        return self.send_message(message)

    # ==================== ÇIKIŞ SİNYALİ ====================

    def send_exit_signal(self, signal) -> bool:
        quote = "TRY" if signal.symbol.endswith("TRY") else "USDT"
        base = signal.symbol.replace("TRY", "").replace("USDT", "")

        message = (
            f"🚪 <b>ÇIKIŞ SİNYALİ — {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Fiyat: {signal.price:,.4f} {quote}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{signal.symbol}'>TradingView</a>"
        )
        return self.send_message(message)

    # ==================== GÜNLÜK ÖZET ====================

    def send_daily_summary(self, signals_today: list, total_pairs_scanned: int) -> bool:
        now = datetime.now()

        if not signals_today:
            message = (
                f"📋 <b>GÜNLÜK ÖZET — {now.strftime('%Y-%m-%d')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Taranan parite: {total_pairs_scanned}\n"
                f"⚡ Alım sinyali: 0\n"
                f"Bugün sinyal bulunamadı.\n"
                f"🕐 {now.strftime('%H:%M:%S')}"
            )
        else:
            signal_lines = []
            for s in signals_today:
                quote = "TRY" if s.symbol.endswith("TRY") else "USDT"
                base = s.symbol.replace("TRY", "").replace("USDT", "")
                signal_lines.append(
                    f"  • <b>{base}/{quote}</b> — {s.price:,.4f} "
                    f"(OCC puan: {s.total_score}/{s.max_score})"
                )

            signals_text = "\n".join(signal_lines)

            message = (
                f"📋 <b>GÜNLÜK ÖZET — {now.strftime('%Y-%m-%d')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Taranan parite: {total_pairs_scanned}\n"
                f"⚡ Alım sinyali: {len(signals_today)}\n"
                f"\n"
                f"<b>Sinyaller:</b>\n"
                f"{signals_text}\n"
                f"\n"
                f"🕐 {now.strftime('%H:%M:%S')}"
            )

        return self.send_message(message)

    # ==================== BAŞLANGIÇ ====================

    def send_startup(self, pair_count: int) -> bool:
        tf_list = ", ".join(f"{tf}({w}p)" for tf, (w, _, _) in OCC_TIMEFRAMES.items())

        message = (
            f"🎯 <b>Multi-TF OCC Scanner Aktif!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📊 Takip: {pair_count} parite\n"
            f"📐 Timeframe'ler: {tf_list}\n"
            f"🎯 Min puan eşiği: {OCC_MIN_SCORE}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"\n"
            f"Her OCC renk değişiminde bildirim gönderilecek.\n"
            f"Puan ≥{OCC_MIN_SCORE} + 15dk tetikleyici → ALIM sinyali."
        )
        return self.send_message(message)

    def send_error(self, error_msg: str) -> bool:
        message = (
            f"⚠️ <b>HATA</b>\n"
            f"{error_msg}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    # ==================== YARDIMCI ====================

    def test_connection(self) -> bool:
        try:
            resp = self.session.get(f"{self.api_url}/getMe", timeout=10)
            if resp.status_code == 200:
                bot_info = resp.json().get("result", {})
                logger.info(f"Telegram bot bağlantısı OK: @{bot_info.get('username', '?')}")
                return True
            else:
                logger.error(f"Telegram bağlantı hatası: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram bağlantı hatası: {e}")
            return False
