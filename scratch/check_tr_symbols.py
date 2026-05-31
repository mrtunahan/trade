import requests

url = "https://www.binance.tr/api/v3/exchangeInfo"
try:
    resp = requests.get(url, timeout=15)
    print("Status:", resp.status_code)
    data = resp.json()
    symbols = data.get("symbols", [])
    print("Total symbols on Binance.TR:", len(symbols))
    
    # Check if STRAXTRY or other TRY pairs exist
    found_strax = [s for s in symbols if "STRAX" in s.get("symbol", "")]
    print("STRAX symbols on Binance.TR:", found_strax)
    
    # Print the first 5 symbols
    if symbols:
        print("First 5 symbols:", [s["symbol"] for s in symbols[:5]])
except Exception as e:
    print("Error:", e)
