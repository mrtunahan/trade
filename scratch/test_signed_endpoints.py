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

print("API Key:", api_key[:10] + "..." if api_key else "None")

def binance_sign(params, secret):
    qs = urlencode(params)
    return hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()

def test_host(host_url):
    print(f"\n--- Testing host: {host_url} ---")
    params = {"timestamp": int(time.time() * 1000)}
    sig = binance_sign(params, api_secret)
    url = f"{host_url}/open/v1/account/spot?{urlencode(params)}&signature={sig}"
    
    try:
        resp = requests.get(url, headers={"X-MBX-APIKEY": api_key, "User-Agent": "Mozilla/5.0"})
        print("Status:", resp.status_code)
        print("Response:", resp.text[:300])
    except Exception as e:
        print("Connection Error:", e)

test_host("https://www.binance.tr")
test_host("https://api.binance.me")
