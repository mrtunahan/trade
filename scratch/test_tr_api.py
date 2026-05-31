import requests

# Let's test with api.binance.me
base_url = "https://api.binance.me"

print("--- Testing exchangeInfo on api.binance.me ---")
try:
    resp = requests.get(f"{base_url}/api/v3/exchangeInfo")
    print("Status:", resp.status_code)
    data = resp.json()
    symbols = data.get("symbols", [])
    print("Total symbols in exchangeInfo:", len(symbols))
    if symbols:
        print("First symbol details:", {k: symbols[0][k] for k in ["symbol", "status", "quoteAsset"] if k in symbols[0]})
except Exception as e:
    print("Error in exchangeInfo:", e)

print("\n--- Testing ticker/24hr on api.binance.me ---")
try:
    resp = requests.get(f"{base_url}/api/v3/ticker/24hr")
    print("Status:", resp.status_code)
    data = resp.json()
    print("Type of data:", type(data))
    if isinstance(data, list):
        print("Total tickers:", len(data))
        if data:
            print("First ticker:", {k: data[0][k] for k in ["symbol", "quoteVolume"] if k in data[0]})
except Exception as e:
    print("Error in ticker/24hr:", e)
