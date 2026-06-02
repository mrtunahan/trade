from pymongo import MongoClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Enricher")

try:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["trade_bot"]
    signals_col = db["signals"]
    
    # 1. NEARTRY Güncellemesi (Boğa / Trend & Full Sniper)
    res_near = signals_col.update_one(
        {"symbol": "NEARTRY"},
        {"$set": {
            "segment_type": "STRONG",
            "candlestick_pattern": "EMA20 Pullback (Geri Çekilip Tutunma)",
            "trigger_tf": "15m",
            "rs_score": 0.154,
            "pipeline_filters": {
                "ema_ok": True,
                "rsi_ok": True,
                "vol_ok": True
            }
        }}
    )
    logger.info(f"NEARTRY güncellendi: {res_near.modified_count}")
    
    # 2. WLDTRY Güncellemesi (Boğa / Trend & Golden Cross)
    res_wld = signals_col.update_one(
        {"symbol": "WLDTRY"},
        {"$set": {
            "segment_type": "STRONG",
            "candlestick_pattern": "EMA9 > EMA20 Kesişimi (Golden Cross)",
            "trigger_tf": "5m",
            "rs_score": 0.285,
            "pipeline_filters": {
                "ema_ok": True,
                "rsi_ok": False,
                "vol_ok": True
            }
        }}
    )
    logger.info(f"WLDTRY güncellendi: {res_wld.modified_count}")
    
    # 3. FFTRY Güncellemesi (Tepki / Aşırı Satım)
    res_ff = signals_col.update_one(
        {"symbol": "FFTRY"},
        {"$set": {
            "segment_type": "WEAK",
            "candlestick_pattern": "RSI 30 Yukarı Kesim (Aşırı Satım Dönüşü)",
            "trigger_tf": "1h",
            "rs_score": -0.182,
            "pipeline_filters": {
                "ema_ok": False,
                "rsi_ok": True,
                "vol_ok": True
            }
        }}
    )
    logger.info(f"FFTRY güncellendi: {res_ff.modified_count}")
    
except Exception as e:
    logger.error(f"Hata oluştu: {e}")
