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

def test_place_order_minimal(symbol, side, order_type, quantity, price):
    print(f"\n--- Testing minimal POST body order: {symbol} | {side} | {order_type} | {quantity} | {price} ---")
    params = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": order_type.upper(),
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

# Test with minimal LIMIT buy order
test_place_order_minimal("STRAXTRY", "BUY", "LIMIT", 150.0, 0.1)
