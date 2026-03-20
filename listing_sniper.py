# ============================================================================
# listing_sniper.py - Binance Listing Sniper
# ============================================================================
# Binance duyuru sayfasını periyodik olarak tarar.
# Yeni listing/airdrop/delist duyurularını tespit eder.
# Coin adını regex ile parse eder (LLM yok, deterministik).
# Anında Telegram bildirimi gönderir.
#
# Ayrı servis olarak çalışır (scanner.py'den bağımsız).
# Kullanım: python listing_sniper.py
# ============================================================================

import re
import time
import signal
import logging
import hashlib
import json
import os
from datetime import datetime
from typing import Optional

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LOG_LEVEL

# ==================== AYARLAR ====================

# Binance duyuru API endpoint'i
BINANCE_ANNOUNCEMENT_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"

# Tarama aralığı (saniye) — düşük tutmak hız kazandırır
CHECK_INTERVAL = 30

# Kaç duyuru geriye bakılsın
PAGE_SIZE = 20

# Duyuru kategorileri (Binance API katalog ID'leri)
# 48: New Cryptocurrency Listing
# 49: Latest Binance News
# 131: Airdrop
CATALOG_IDS = [48, 49, 131]

# Bilinen duyuruları takip etmek için dosya
SEEN_FILE = "listing_sniper_seen.json"

# ==================== LOGLAMA ====================

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(name)-14s | %(message)s",
    datefmt="%H:%M:%S",
)
root = logging.getLogger()
root.setLevel(getattr(logging, LOG_LEVEL, "INFO"))

ch = logging.StreamHandler()
ch.setFormatter(formatter)
root.addHandler(ch)

fh = logging.FileHandler("listing_sniper.log", encoding="utf-8")
fh.setFormatter(formatter)
root.addHandler(fh)

logger = logging.getLogger("ListingSniper")

# ==================== COIN PARSE REGEX ====================

# Binance listing duyurularından coin sembollerini çıkaran regex desenleri
LISTING_PATTERNS = [
    # "Binance Will List XXX (SYMBOL)"
    r"(?:Will\s+List|Lists?|Listing)\s+[\w\s]*?\((\w+)\)",
    # "Binance Adds XXX (SYMBOL)"
    r"(?:Adds?|Adding)\s+[\w\s]*?\((\w+)\)",
    # "New Trading Pair: SYMBOL/USDT"
    r"Trading\s+Pair[s]?:?\s*(\w+)/(?:USDT|BTC|BNB|TRY)",
    # "SYMBOL (XXX) listelenecek"
    r"(\w+)\s*\([^)]+\)\s*(?:listelen|eklen)",
    # "XXX (SYMBOL) Perpetual Contract"
    r"\((\w+)\)\s*(?:Perpetual|Token|Coin)",
    # "(SYMBOL)" tek başına parantez içinde — en genel
    r"\(([A-Z]{2,10})\)",
]

# Bu semboller listing değil, false positive'leri filtrele
IGNORE_SYMBOLS = {
    "USD", "USDT", "USDC", "BTC", "ETH", "BNB", "TRY", "EUR", "GBP",
    "API", "VIP", "FAQ", "NFT", "CEO", "CTO", "AML", "KYC", "OTC",
    "THE", "AND", "FOR", "NEW", "ALL", "NOT", "ARE", "HAS", "WAS",
}


def extract_symbols(title: str) -> list[str]:
    """
    Duyuru başlığından coin sembollerini çıkarır.
    Birden fazla sembol olabilir (multi-listing).
    """
    symbols = set()
    for pattern in LISTING_PATTERNS:
        for match in re.finditer(pattern, title, re.IGNORECASE):
            sym = match.group(1).upper()
            if sym not in IGNORE_SYMBOLS and 2 <= len(sym) <= 10:
                symbols.add(sym)
    return sorted(symbols)


def classify_announcement(title: str) -> str:
    """Duyuruyu kategorize eder."""
    title_lower = title.lower()
    if any(w in title_lower for w in ["list", "listeleme", "adds"]):
        return "listing"
    if any(w in title_lower for w in ["delist", "kaldır", "remove"]):
        return "delisting"
    if any(w in title_lower for w in ["airdrop", "launchpool", "launchpad"]):
        return "airdrop"
    if any(w in title_lower for w in ["trading pair", "işlem çifti"]):
        return "new_pair"
    if any(w in title_lower for w in ["futures", "perpetual", "vadeli"]):
        return "futures"
    return "other"


# ==================== ANA SERVİS ====================

class ListingSniper:
    """Binance duyurularını tarar, yeni listing'leri anında bildirir."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.seen_ids = self._load_seen()
        self.running = True

        # Telegram
        self.tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        self.chat_id = TELEGRAM_CHAT_ID

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Kapatılıyor...")
        self.running = False

    def _load_seen(self) -> set:
        """Daha önce görülen duyuru ID'lerini yükler."""
        if os.path.exists(SEEN_FILE):
            try:
                with open(SEEN_FILE, "r") as f:
                    data = json.load(f)
                return set(data.get("seen_ids", []))
            except Exception:
                pass
        return set()

    def _save_seen(self):
        """Görülen duyuru ID'lerini kaydeder."""
        try:
            with open(SEEN_FILE, "w") as f:
                json.dump({"seen_ids": list(self.seen_ids)[-500:]}, f)
        except Exception as e:
            logger.error(f"Seen dosyası yazılamadı: {e}")

    def fetch_announcements(self, catalog_id: int) -> list[dict]:
        """Binance duyuru API'sinden son duyuruları çeker."""
        try:
            payload = {
                "catalogId": catalog_id,
                "pageNo": 1,
                "pageSize": PAGE_SIZE,
            }
            resp = self.session.post(
                BINANCE_ANNOUNCEMENT_URL,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("data", {}).get("catalogs", [])
            if articles:
                return articles[0].get("articles", [])
            return []
        except Exception as e:
            logger.warning(f"Duyuru çekme hatası (catalog={catalog_id}): {e}")
            return []

    def check_new_announcements(self) -> list[dict]:
        """Tüm kategorilerdeki yeni duyuruları kontrol eder."""
        new_announcements = []

        for catalog_id in CATALOG_IDS:
            articles = self.fetch_announcements(catalog_id)
            for article in articles:
                article_id = str(article.get("id", ""))
                if not article_id or article_id in self.seen_ids:
                    continue

                title = article.get("title", "")
                release_date = article.get("releaseDate", 0)

                # Yeni duyuru bulundu
                self.seen_ids.add(article_id)
                symbols = extract_symbols(title)
                category = classify_announcement(title)

                new_announcements.append({
                    "id": article_id,
                    "title": title,
                    "symbols": symbols,
                    "category": category,
                    "release_date": release_date,
                    "url": f"https://www.binance.com/en/support/announcement/{article.get('code', '')}",
                })

            time.sleep(0.5)  # Kategori arası rate limit

        return new_announcements

    def send_alert(self, announcement: dict):
        """Yeni duyuru için Telegram bildirimi gönderir."""
        category = announcement["category"]
        symbols = announcement["symbols"]
        title = announcement["title"]
        url = announcement["url"]

        # Kategori bazlı emoji
        emoji_map = {
            "listing": "🚀",
            "delisting": "⚠️",
            "airdrop": "🎁",
            "new_pair": "🔄",
            "futures": "📈",
            "other": "📢",
        }
        emoji = emoji_map.get(category, "📢")

        category_labels = {
            "listing": "YENİ LİSTELEME",
            "delisting": "LİSTEDEN ÇIKARMA",
            "airdrop": "AIRDROP / LAUNCHPOOL",
            "new_pair": "YENİ İŞLEM ÇİFTİ",
            "futures": "FUTURES LİSTELEME",
            "other": "DUYURU",
        }
        label = category_labels.get(category, "DUYURU")

        # Sembol satırı
        if symbols:
            sym_text = ", ".join(f"<b>${s}</b>" for s in symbols)
            sym_line = f"🪙 Semboller: {sym_text}\n"
        else:
            sym_line = ""

        message = (
            f"{emoji} <b>BİNANCE {label}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📰 {title}\n"
            f"\n"
            f"{sym_line}"
            f"\n"
            f"🔗 <a href='{url}'>Duyuruyu Oku</a>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        try:
            resp = self.session.post(
                f"{self.tg_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info(f"✅ Bildirim gönderildi: {title[:60]}")
            else:
                logger.error(f"Telegram hata: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram bağlantı hatası: {e}")

    def run(self):
        """Ana döngü — sürekli duyuru tarar."""
        logger.info("=" * 60)
        logger.info("🔫 Binance Listing Sniper başlatılıyor...")
        logger.info(f"   Tarama aralığı: {CHECK_INTERVAL}s")
        logger.info(f"   Kategoriler: {CATALOG_IDS}")
        logger.info(f"   Bilinen duyuru: {len(self.seen_ids)}")
        logger.info("=" * 60)

        # İlk çalıştırmada mevcut duyuruları "seen" olarak işaretle
        if not self.seen_ids:
            logger.info("İlk çalıştırma: mevcut duyurular kaydediliyor...")
            for catalog_id in CATALOG_IDS:
                articles = self.fetch_announcements(catalog_id)
                for article in articles:
                    self.seen_ids.add(str(article.get("id", "")))
                time.sleep(0.5)
            self._save_seen()
            logger.info(f"   {len(self.seen_ids)} mevcut duyuru kaydedildi")

        # Başlangıç bildirimi
        try:
            self.session.post(
                f"{self.tg_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": (
                        "🔫 <b>Listing Sniper Aktif!</b>\n"
                        f"Takip: {len(CATALOG_IDS)} kategori\n"
                        f"Tarama: her {CHECK_INTERVAL}s\n"
                        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    ),
                    "parse_mode": "HTML",
                },
                timeout=15,
            )
        except Exception:
            pass

        cycle = 0
        while self.running:
            cycle += 1
            try:
                new = self.check_new_announcements()
                if new:
                    logger.info(f"📢 {len(new)} yeni duyuru tespit edildi!")
                    for ann in new:
                        self.send_alert(ann)
                    self._save_seen()
                elif cycle % 20 == 0:
                    logger.info(f"Döngü #{cycle}: yeni duyuru yok")

            except Exception as e:
                logger.error(f"Tarama hatası: {e}")

            # Sonraki kontrol
            for _ in range(CHECK_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        self._save_seen()
        logger.info("Listing Sniper durduruldu.")


# ==================== CLI ====================

def main():
    import sys

    if "--test" in sys.argv:
        # Regex test
        test_titles = [
            "Binance Will List Ethena (ENA)",
            "Binance Adds Jupiter (JUP) and Pyth (PYTH)",
            "New Trading Pair: PEPE/USDT",
            "Binance Futures Will Launch BONK Perpetual Contract",
            "Binance Completes Sei (SEI) Airdrop Distribution",
            "Notice of Removal of Spot Trading Pairs - 2024-03-15",
        ]
        print("=== Regex Parse Testi ===")
        for title in test_titles:
            symbols = extract_symbols(title)
            category = classify_announcement(title)
            print(f"  [{category:>10}] {title}")
            print(f"             Semboller: {symbols or '(yok)'}")
        return

    sniper = ListingSniper()
    sniper.run()


if __name__ == "__main__":
    main()
