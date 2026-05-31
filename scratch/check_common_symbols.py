import requests

url = "https://www.binance.tr/open/v1/common/symbols"
try:
    resp = requests.get(url, timeout=15)
    print("Status:", resp.status_code)
    data = resp.json()
    print("Code:", data.get("code"))
    print("Msg:", data.get("msg"))
    symbols = data.get("data", {}).get("list", [])
    print("Total symbols in list:", len(symbols))
    
    # Check if STRAXTRY or other TRY pairs exist
    found_strax = [s for s in symbols if "STRAX" in s.get("symbol", "")]
    print("STRAX symbols in list:", found_strax)
    
    if symbols:
        print("First symbol keys:", symbols[0].keys())
        print("First symbol example:", symbols[0])
except Exception as e:
    print("Error:", e)
