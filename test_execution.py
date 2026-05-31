# test_execution.py  – Geçici entegrasyon testi (silmeyi unutma)
import logging
from market_data import MarketData

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")


def test_api():
    market = MarketData()

    print("\n--- 1. Tekil Bakiye Sorgulama (TRY) ---")
    try_balance = market.get_available_balance("TRY")
    print(f"Boştaki TRY Bakiyeniz: {try_balance} TRY")


if __name__ == "__main__":
    test_api()
