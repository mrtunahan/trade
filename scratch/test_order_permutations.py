import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_API_SECRET", "")

def test_permutation(symbol, side, order_type, quantity, price):
    print(f"\n--- Testing: side={side} (type {type(side)}), type={order_type} (type {type(order_type)}) ---")
    params = {
        "symbol": symbol.upper(),
        "side": str(side),
        "type": str(order_type),
        "quantity": str(int(quantity)),
        "price": f"{price:.3f}",
        "timestamp": int(time.time() * 1000)
    }
    
    # Generate signature on the parameters query string
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    
    # Payload for the POST body includes the signature
    payload = params.copy()
    payload["signature"] = sig
    
    url = "https://www.binance.tr/open/v1/orders"
    headers = {
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        print("Status:", resp.status_code)
        print("Response:", resp.text)
    except Exception as e:
        print("Error:", e)

# Test different permutations
# Standard price 0.1 TRY and quantity 150 (minNotional = 15 TRY > 10 TRY)
test_permutation("STRAXTRY", "BUY", "LIMIT", 150.0, 0.1)  # Permutation 1
test_permutation("STRAXTRY", 0, "LIMIT", 150.0, 0.1)      # Permutation 2
test_permutation("STRAXTRY", "BUY", 1, 150.0, 0.1)        # Permutation 3
test_permutation("STRAXTRY", 0, 1, 150.0, 0.1)            # Permutation 4
