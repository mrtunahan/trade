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
        else:
            emoji = "🔴"
            direction = "KIRMIZI (Düşüş)"

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
        Premium Spot Pipeline alım sinyalini gönderir.
        Gelişmiş premium çıktı şablonu.
        """
        import math
        quote = "TRY" if signal.symbol.endswith("TRY") else "USDT"
        base = signal.symbol.replace("TRY", "").replace("USDT", "")

        # Puan ve segment
        rating = signal.signal_star_rating
        stars = rating["stars"]
        score_label = rating["label"]

        # Günlük gösterge detayları (örn: Daily EMA50>EMA200: Yeşil, Daily RSI: Yeşil, Daily Volume: Yeşil)
        tf_details = []
        for ts in signal.tf_statuses:
            status_str = "Yeşil" if ts.is_green else "Kırmızı"
            tf_details.append(f"{ts.label}: {status_str}")
        tf_details_str = ", ".join(tf_details)

        # Tetikleyici timeframe bilgisi
        trigger_tf_label = signal.trigger_tf
        trigger_tf_desc = f"{trigger_tf_label} Grafik Kapanışı ile Onaylandı"

        # Mum formasyonu / Tetikleyici
        extra_onay = signal.candlestick_pattern or "Pullback / Kesişim"

        # ADX bilgisi ve trend modu (Piyasa Rejimi)
        adx_desc = f"{signal.segment_type} (Boğa/Trend)" if signal.segment_type == "STRONG" else f"{signal.segment_type} (Aşırı Satım/Tepki)"

        # RSI bilgisi
        rsi_val = signal.rsi_value
        if not math.isnan(rsi_val):
            rsi_desc = f"{rsi_val:.1f} (Günlük Grafik)"
        else:
            rsi_desc = "N/A"

        # SL/TP fiyatları
        price = signal.price
        sl_pct = signal.stop_loss_pct
        tp_pct = signal.take_profit_pct
        sl_price = price * (1 - sl_pct / 100)
        tp_price = price * (1 + tp_pct / 100)

        # Dinamik SL & TP açıklama satırı
        dynamic_sl_tp = f"{sl_price:,.4f} (-%{sl_pct:.1f}) // Dinamik TP: {tp_price:,.4f} (+%{tp_pct:.1f})"

        message = (
            f"🟢 <b>[AL SİNYALİ] - {base}/{quote} // {score_label} {stars}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Strateji:</b> Spot 4-Stage Pipeline ({signal.segment_type} Segment)\n"
            f"<b>Günlük Skor:</b> {signal.total_score}/{signal.max_score} ({tf_details_str})\n"
            f"<b>Tetikleyici Zaman:</b> {trigger_tf_desc}\n"
            f"<b>Giriş Tetiği:</b> {extra_onay}\n"
            f"<b>Piyasa Rejimi:</b> {adx_desc}\n"
            f"<b>Günlük RSI:</b> {rsi_desc}\n"
            f"<b>Giriş Fiyatı:</b> {price:,.4f} {quote}\n"
            f"<b>Dinamik SL/TP:</b> {dynamic_sl_tp}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>Öneri:</b> %{signal.position_size_pct*100:.0f} ({signal.position_tier})\n"
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
        message = (
            f"🎯 <b>Spot 4-Stage Pipeline Scanner Aktif!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📊 Takip: {pair_count} parite\n"
            f"⚙️ Tarama Döngüsü: 5 Dakika\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"\n"
            f"Trend ve Tepki segment sinyalleri otomatik olarak takip ediliyor."
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
