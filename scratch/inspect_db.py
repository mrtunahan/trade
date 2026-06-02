import pymongo
from datetime import datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["trade_bot"]
signals = list(db["signals"].find({"status": "PENDING"}))

print(f"Total PENDING signals: {len(signals)}")
for sig in signals:
    ts = sig["timestamp"]
    now = datetime.now()
    age = (now - ts).total_seconds()
    print(f"Symbol: {sig['symbol']}, Timestamp in DB: {ts}, Current Time: {now}, Age: {age} seconds")
