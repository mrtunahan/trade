# test_execution.py  – Geçici entegrasyon testi (silmeyi unutma)
import logging
from market_data import MarketData

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")


def test_api():
    market = MarketData()

    print("\n--- 1. Cüzdan Bakiyeleri Çekiliyor ---")
    balances = market.get_asset_balances()
    if balances:
        for asset, b in balances.items():
            if b["free"] > 0 or b["locked"] > 0:
                print(f"{asset} -> Kullanılabilir: {b['free']} | Kilitli: {b['locked']}")
    else:
        print("Bakiye bilgisi alınamadı. API anahtarlarınızı (.env) kontrol edin.")

    print("\n--- 2. Tekil Bakiye Sorgulama (TRY) ---")
    try_balance = market.get_available_balance("TRY")
    print(f"Boştaki TRY Bakiyeniz: {try_balance} TRY")


if __name__ == "__main__":
    test_api()
