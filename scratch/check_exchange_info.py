import requests

url = "https://api.binance.me/api/v3/exchangeInfo?symbol=STRAXTRY"
try:
    resp = requests.get(url)
    print("Status:", resp.status_code)
    data = resp.json()
    symbols = data.get("symbols", [])
    if symbols:
        s = symbols[0]
        print("Symbol:", s.get("symbol"))
        print("Status:", s.get("status"))
        print("Order Types:", s.get("orderTypes"))
        print("Filters:")
        for f in s.get("filters", []):
            print("  -", f)
    else:
        print("Symbol not found in exchangeInfo.")
except Exception as e:
    print("Error:", e)
