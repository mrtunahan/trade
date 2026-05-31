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

def binance_sign(params, secret):
    qs = urlencode(params)
    return hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()

def test_get_orders(symbol=None):
    print(f"\n--- Testing GET orders for symbol: {symbol} ---")
    params = {
        "timestamp": int(time.time() * 1000)
    }
    if symbol:
        params["symbol"] = symbol.upper()
        
    sig = binance_sign(params, api_secret)
    url = f"https://www.binance.tr/open/v1/orders?{urlencode(params)}&signature={sig}"
    
    try:
        resp = requests.get(url, headers={"X-MBX-APIKEY": api_key, "User-Agent": "Mozilla/5.0"})
        print("Status:", resp.status_code)
        print("Response:", resp.text)
    except Exception as e:
        print("Error:", e)

test_get_orders("STRAXTRY")
