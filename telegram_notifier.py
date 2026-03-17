# ============================================================================
# telegram_notifier.py - Telegram Bildirim Modülü (Geliştirilmiş v2)
# ============================================================================
# Bulunan sinyalleri Telegram'a zengin formatlı mesajlarla gönderir.
# v2: Market rejimi, çıkış sinyali, gelişmiş modül bilgileri
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
    MIN_SIGNAL_STRENGTH_PCT,
)

logger = logging.getLogger("Telegram")


class TelegramNotifier:
    """Telegram Bot API ile bildirim gönderici."""

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.session = requests.Session()

    # ==================== MESAJ GÖNDER ====================

    def send_message(self, text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
        """Basit metin mesajı gönderir."""
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
        """Fotoğraf gönderir (mini grafik için)."""
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

    # ==================== SİNYAL BİLDİRİMİ ====================

    def send_signal(self, signal, chart_bytes: Optional[bytes] = None) -> bool:
        """
        Sinyal bildirimini Telegram'a gönderir.
        signal: analyzer.Signal nesnesi (ağırlıklı puanlama sistemi)
        """
        # Ağırlıklı güç yüzdesi
        strength_pct = signal.strength_pct
        if strength_pct >= 0.85:
            strength_emoji = "🔥🔥🔥"
            strength_text = "Full Sniper"
        elif strength_pct >= 0.70:
            strength_emoji = "🔥🔥"
            strength_text = "High Probability"
        else:
            strength_emoji = "🔥"
            strength_text = "Güçlü"

        # Parite bilgisi
        quote = "TRY" if signal.symbol.endswith("TRY") else "USDT"
        base = signal.symbol.replace("TRY", "").replace("USDT", "")

        # İndikatör değerleri
        rsi_val = signal.indicators.get("rsi")
        rsi_str = f"{float(rsi_val.iloc[-1]):.1f}" if rsi_val is not None and len(rsi_val) > 0 else "N/A"

        change_24h = signal.indicators.get("change_24h", 0)
        change_emoji = "📈" if change_24h >= 0 else "📉"

        # Market rejimi bilgisi
        regime_map = {
            "trending": "📊 Trend",
            "ranging": "📐 Yatay",
            "transition": "🔄 Geçiş",
            "unknown": "❓ Belirsiz",
        }
        regime_text = regime_map.get(signal.market_regime, "")

        # ADX bilgisi
        adx_val = signal.indicators.get("adx_last", float("nan"))
        adx_str = f" (ADX: {adx_val:.1f})" if adx_val == adx_val else ""  # NaN check

        # Sağlanan kriterler listesi
        criteria_lines = []
        for name in signal.criteria_met:
            detail = signal.criteria_details.get(name, {})
            desc = detail.get("description", name)
            weight = detail.get("weight", "?")
            criteria_lines.append(f"  ✅ <b>{self._format_criteria_name(name)}</b>: {desc} [{weight}p]")

        # Sağlanmayan kriterleri de göster (kapalı olanları atlayarak)
        for name, detail in signal.criteria_details.items():
            if name not in signal.criteria_met:
                desc = detail.get("description", name)
                weight = detail.get("weight", "?")
                criteria_lines.append(f"  ❌ {self._format_criteria_name(name)}: {desc} [{weight}p]")

        criteria_text = "\n".join(criteria_lines)

        # Çıkış bilgisi
        exit_info = ""
        if signal.exit_score > 0:
            exit_info = f"\n⚠️ <b>Çıkış Puanı:</b> {signal.exit_score}/5\n"

        # Ana mesaj
        message = (
            f"{strength_emoji} <b>ALIM SİNYALİ - {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"💰 <b>Fiyat:</b> {signal.price:,.4f} {quote}\n"
            f"📊 <b>Güç:</b> {strength_text} ({signal.strength}/{signal.total_criteria} puan — %{strength_pct*100:.0f})\n"
            f"📉 <b>RSI:</b> {rsi_str}\n"
            f"{change_emoji} <b>24s Değişim:</b> {change_24h:+.2f}%\n"
        )

        if regime_text:
            message += f"🏷 <b>Piyasa:</b> {regime_text}{adx_str}\n"

        # Pozisyon boyutu ve dinamik SL/TP
        pos_size = getattr(signal, "position_size_pct", 1.0)
        pos_tier = getattr(signal, "position_tier", "")
        sl_pct = getattr(signal, "stop_loss_pct", 2.0)
        tp_pct = getattr(signal, "take_profit_pct", 4.0)

        message += (
            f"\n"
            f"💼 <b>Pozisyon:</b> %{pos_size*100:.0f}"
        )
        if pos_tier:
            message += f" ({pos_tier})"
        message += (
            f"\n"
            f"🛑 <b>Stop-Loss:</b> %{sl_pct:.1f} | "
            f"🎯 <b>Take-Profit:</b> %{tp_pct:.1f}\n"
        )

        message += (
            f"\n"
            f"<b>Kriterler:</b>\n"
            f"{criteria_text}\n"
            f"{exit_info}"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{signal.symbol}'>TradingView</a>"
        )

        # Grafik varsa fotoğraf olarak, yoksa metin olarak gönder
        if chart_bytes and SEND_CHART_IMAGE:
            return self.send_photo(chart_bytes, caption=message)
        else:
            return self.send_message(message)

    # ==================== ÇIKIŞ SİNYALİ ====================

    def send_exit_signal(self, signal) -> bool:
        """Çıkış sinyali bildirimini gönderir."""
        quote = "TRY" if signal.symbol.endswith("TRY") else "USDT"
        base = signal.symbol.replace("TRY", "").replace("USDT", "")

        exit_lines = []
        for name, detail in signal.exit_details.items():
            if detail.get("met", False):
                w = detail.get("weight", 1)
                exit_lines.append(f"  ⚠️ {detail.get('detail', name)} [{w}p]")

        exit_text = "\n".join(exit_lines)

        message = (
            f"🚪 <b>ÇIKIŞ SİNYALİ - {base}/{quote}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"💰 <b>Fiyat:</b> {signal.price:,.4f} {quote}\n"
            f"📊 <b>Çıkış Puanı:</b> {signal.exit_score}/5\n"
            f"\n"
            f"<b>Çıkış Nedenleri:</b>\n"
            f"{exit_text}\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{signal.symbol}'>TradingView</a>"
        )

        return self.send_message(message)

    # ==================== GÜNLÜK ÖZET ====================

    def send_daily_summary(self, signals_today: list, total_pairs_scanned: int) -> bool:
        """Günlük özet rapor gönderir."""
        now = datetime.now()

        if not signals_today:
            message = (
                f"📋 <b>GÜNLÜK ÖZET - {now.strftime('%Y-%m-%d')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"📊 Taranan parite: {total_pairs_scanned}\n"
                f"⚡ Bulunan sinyal: 0\n"
                f"\n"
                f"Bugün alım sinyali bulunamadı.\n"
                f"🕐 {now.strftime('%H:%M:%S')}"
            )
        else:
            signal_lines = []
            for s in signals_today:
                quote = "TRY" if s.symbol.endswith("TRY") else "USDT"
                base = s.symbol.replace("TRY", "").replace("USDT", "")
                regime = f" [{s.market_regime}]" if s.market_regime != "unknown" else ""
                signal_lines.append(
                    f"  • <b>{base}/{quote}</b> — {s.price:,.4f} {quote} "
                    f"(güç: {s.strength}/{s.total_criteria}){regime}"
                )

            signals_text = "\n".join(signal_lines)

            # En güçlü sinyaller
            sorted_signals = sorted(signals_today, key=lambda s: s.strength, reverse=True)
            top3 = sorted_signals[:3]
            top_lines = []
            for i, s in enumerate(top3):
                medal = ["🥇", "🥈", "🥉"][i]
                base = s.symbol.replace("TRY", "").replace("USDT", "")
                top_lines.append(f"  {medal} {base} ({s.strength}/{s.total_criteria} puan)")

            message = (
                f"📋 <b>GÜNLÜK ÖZET - {now.strftime('%Y-%m-%d')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"📊 Taranan parite: {total_pairs_scanned}\n"
                f"⚡ Bulunan sinyal: {len(signals_today)}\n"
                f"\n"
                f"<b>En güçlü sinyaller:</b>\n"
                f"{''.join(t + chr(10) for t in top_lines)}\n"
                f"<b>Tüm sinyaller:</b>\n"
                f"{signals_text}\n"
                f"\n"
                f"🕐 {now.strftime('%H:%M:%S')}"
            )

        return self.send_message(message)

    # ==================== DURUM BİLDİRİMLERİ ====================

    def send_startup(self, pair_count: int, active_modules: list = None) -> bool:
        """Bot başlatıldığında bildirim gönderir."""
        modules_text = ""
        if active_modules:
            modules_text = f"🧩 Gelişmiş modüller: {', '.join(active_modules)}\n"

        message = (
            f"🤖 <b>Scanner Bot v2.0 Aktif!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📊 Takip edilen parite: {pair_count}\n"
            f"🎯 Min sinyal gücü: %{MIN_SIGNAL_STRENGTH_PCT*100:.0f}\n"
            f"{modules_text}"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"\n"
            f"Sadece güçlü sinyaller bildirilecek..."
        )
        return self.send_message(message)

    def send_error(self, error_msg: str) -> bool:
        """Hata bildirimi gönderir."""
        message = (
            f"⚠️ <b>HATA</b>\n"
            f"{error_msg}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    # ==================== YARDIMCI ====================

    def _format_criteria_name(self, name: str) -> str:
        """Kriter ismini okunabilir formata çevirir."""
        names = {
            "ema_cross": "EMA Kesişim",
            "rsi": "RSI",
            "macd": "MACD",
            "bollinger": "Bollinger Band",
            "volume_spike": "Hacim Artışı",
            "trend_filter": "Trend Filtresi",
            "support_resistance": "Destek/Direnç",
            "stoch_rsi": "Stochastic RSI",
            "occ": "OCC",
            "multi_timeframe": "Multi-TF",
            "market_regime": "Piyasa Rejimi",
            "time_filter": "Seans Filtresi",
            "btc_filter": "BTC Trend",
        }
        return names.get(name, name)

    def test_connection(self) -> bool:
        """Telegram bağlantısını test eder."""
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
