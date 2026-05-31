// ============================================================================
// dashboard_backend/server.js - Jarvis Monitor API & WebSocket Sunucusu
// ============================================================================

const express   = require('express');
const http      = require('http');
const { Server } = require('socket.io');
const mongoose  = require('mongoose');
const cors      = require('cors');
const fs        = require('fs');
const path      = require('path');
const crypto    = require('crypto');
const axios     = require('axios');
require('dotenv').config({ path: path.join(__dirname, '../.env') });

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: '*', methods: ['GET', 'POST'] }
});

// ==================== BINANCE TR SPOT PROXY ====================
const TR_API_BASE = 'https://www.binance.tr';
const TR_PUBLIC_BASE = 'https://api.binance.me';
const API_KEY     = process.env.BINANCE_API_KEY     || '';
const API_SECRET  = process.env.BINANCE_API_SECRET  || '';
const QUOTE_ASSET = (process.env.QUOTE_ASSET || 'TRY').toUpperCase();
const MAX_BUDGET_PER_TRADE = parseFloat(process.env.MAX_BUDGET_PER_TRADE || (QUOTE_ASSET === 'TRY' ? '500' : '50'));

const STABLECOIN_BASES = new Set([
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", 
    "USDP", "EUR", "GBP", "TRY", "USDE", "PYUSD", 
    "AEUR", "USTC", "PAXG", "USD"
]);

function formatTrSymbol(symbol) {
    if (!symbol) return symbol;
    const sym = symbol.toUpperCase();
    if (sym.includes('_')) return sym;
    if (sym.endsWith('TRY')) {
        return sym.slice(0, -3) + '_TRY';
    }
    if (sym.endsWith('USDT')) {
        return sym.slice(0, -4) + '_USDT';
    }
    return sym;
}

function mapTrParams(params) {
    const newParams = { ...params };
    if (newParams.symbol) {
        newParams.symbol = formatTrSymbol(newParams.symbol);
    }
    if (newParams.side) {
        const sideUpper = String(newParams.side).toUpperCase();
        if (sideUpper === 'BUY' || sideUpper === 'LONG') {
            newParams.side = '0';
        } else if (sideUpper === 'SELL' || sideUpper === 'SHORT') {
            newParams.side = '1';
        }
    }
    if (newParams.type) {
        const typeUpper = String(newParams.type).toUpperCase();
        if (typeUpper === 'LIMIT') {
            newParams.type = '1';
        } else if (typeUpper === 'MARKET') {
            newParams.type = '2';
        }
    }
    if (newParams.quantity) {
        const qty = parseFloat(newParams.quantity);
        newParams.quantity = qty < 1 ? qty.toFixed(4) : qty.toFixed(3);
    }
    if (newParams.price) {
        const price = parseFloat(newParams.price);
        newParams.price = price.toFixed(4);
    }
    return newParams;
}

function binanceSign(params) {
    const qs = new URLSearchParams({ ...params, timestamp: Date.now() }).toString();
    const sig = crypto.createHmac('sha256', API_SECRET).update(qs).digest('hex');
    return qs + '&signature=' + sig;
}

async function fapi(endpoint, params = {}) {
    const mappedParams = {};
    for (const [k, v] of Object.entries(params)) {
        if (k === 'symbol') {
            mappedParams[k] = formatTrSymbol(v);
        } else {
            mappedParams[k] = v;
        }
    }
    const qs = binanceSign(mappedParams);
    const url = `${TR_API_BASE}${endpoint}?${qs}`;
    const res = await axios.get(url, { 
        headers: { 
            'X-MBX-APIKEY': API_KEY,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }, 
        timeout: 10000 
    });
    return res.data;
}

async function fapiPublic(endpoint, params = {}) {
    const url = `${TR_PUBLIC_BASE}${endpoint}`;
    const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    };
    if (API_KEY) {
        headers['X-MBX-APIKEY'] = API_KEY;
    }
    const res = await axios.get(url, { 
        params, 
        headers,
        timeout: 10000 
    });
    return res.data;
}

async function fapiPost(endpoint, params = {}) {
    const mappedParams = mapTrParams(params);
    const qs = binanceSign(mappedParams);
    const url = `${TR_API_BASE}${endpoint}`;
    
    // Parse the query string to send in the body
    const sigParams = new URLSearchParams(qs);
    const payload = {};
    for (const [key, value] of sigParams.entries()) {
        payload[key] = value;
    }
    
    const res = await axios.post(url, new URLSearchParams(payload).toString(), { 
        headers: { 
            'X-MBX-APIKEY': API_KEY,
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }, 
        timeout: 10000 
    });
    return res.data;
}


// ==================== CANLI BİNANCE VERİ CACHE SİSTEMİ ====================
// Binance IP banı (HTTP 418) önlemek için verileri kısa süreliğine önbelleğe alıyoruz.
const CACHE_TTL_MS = 2500;
const cache = {
    balance: { data: null, ts: 0 },
    positions: { data: null, ts: 0 },
    openOrders: { data: null, ts: 0 },
    income: { data: null, ts: 0 },
    allTickers: { data: null, ts: 0 },
    ticker: {},     // symbol -> { data, ts }
    orderbook: {},  // symbol -> { data, ts }
};

// ─── Birleşik Dashboard Veri Endpoint'i (Rate Limit & 418 Önleyici) ──────────
app.get('/api/dashboard/all-data', async (req, res) => {
    try {
        const symbol = req.query.symbol || ('BTC' + QUOTE_ASSET);
        const now = Date.now();
        let binanceApiError = null;
        
        // 1. Hesap Bakiyesi (Cache veya Sıralı İstek)
        let balanceData = cache.balance.data;
        if (!balanceData || (now - cache.balance.ts) > CACHE_TTL_MS) {
            try {
                const data = await fapi('/open/v1/account/spot');
                const balances = data.data?.accountAssets || data.data?.balances || data.balances || [];
                const quoteBal = balances.find(a => a.asset === QUOTE_ASSET) || {};
                balanceData = {
                    walletBalance:    parseFloat(quoteBal.free || 0) + parseFloat(quoteBal.locked || 0),
                    availableBalance: parseFloat(quoteBal.free || 0),
                    unrealizedPnl:    0,
                    marginBalance:    parseFloat(quoteBal.free || 0),
                    totalInitialMargin: 0,
                    quoteAsset:       QUOTE_ASSET,
                    maxBudget:        MAX_BUDGET_PER_TRADE,
                };
                cache.balance.data = balanceData;
                cache.balance.ts = now;
            } catch (e) {
                console.log("Balance fetch error:", e.message);
                if (e.response && e.response.data && e.response.data.msg) {
                    binanceApiError = `Binance Hata Kodu ${e.response.data.code || ''}: ${e.response.data.msg}`;
                } else if (e.response && e.response.status === 401) {
                    binanceApiError = "Binance API Hatası: Yetkilendirme Başarısız (HTTP 401). API Key veya Secret geçersiz.";
                } else {
                    binanceApiError = `Binance API Bağlantı Hatası: ${e.message}`;
                }
            }
            await new Promise(r => setTimeout(r, 200)); // 200ms stagger gecikmesi
        }
        
        // 2. Açık Pozisyonlar (Spot: Veritabanındaki OPEN işlemler ve anlık PnL)
        let positionsData = [];
        try {
            const openDbPos = await Position.find({ status: 'OPEN' });
            for (const p of openDbPos) {
                const sym = p.symbol;
                const tickerCache = cache.ticker[sym]?.data || {};
                const currentPrice = parseFloat(tickerCache.lastPrice || p.entry_price || 0);
                const entry = parseFloat(p.entry_price || 0);
                const qty = parseFloat(p.quantity || 0);
                const pnl = (currentPrice - entry) * qty;
                positionsData.push({
                    symbol: sym,
                    positionAmt: qty.toString(),
                    entryPrice: entry.toString(),
                    unRealizedProfit: pnl.toFixed(4),
                    pnlPct: entry > 0 ? ((currentPrice - entry) / entry * 100).toFixed(2) : '0',
                    marginType: 'spot',
                    leverage: '1',
                    liquidationPrice: '0',
                    positionSide: 'LONG',
                    markPrice: currentPrice.toString(),
                    stop_loss_price: p.stop_loss_price || null,
                    take_profit_price: p.take_profit_price || null,
                    stars: p.star_label || p.position_tier || '',
                    allocated_budget: (entry * qty).toFixed(2),
                    open_time: p.open_time || null,
                });
            }
        } catch (e) {
            console.log("DB positions fetch error:", e.message);
        }
        
        // 3. Açık Emirler
        let openOrdersData = [];
        try {
            // Binance TR requires symbol to query open orders
            const data = await fapi('/open/v1/orders', { symbol: symbol.toUpperCase() });
            const list = Array.isArray(data) ? data : (data?.orders || []);
            openOrdersData = list.filter(o => o.status === 'NEW' || o.status === 'PARTIALLY_FILLED').map(o => ({
                symbol: o.symbol,
                side: o.side,
                type: o.type,
                origQty: o.quantity || o.origQty,
                price: o.price,
                status: o.status,
                orderId: o.orderId || o.id
            }));
        } catch (e) {
            console.log("Open orders fetch error:", e.message);
        }
        
        // 4. Gelir/PnL Özeti (Lokal MongoDB Veritabanından)
        let incomeData = { items: [], totalPnl: 0 };
        try {
            const closedDbPos = await Position.find({ status: 'CLOSED' }).sort({ close_time: -1 }).limit(100);
            const total = closedDbPos.reduce((sum, p) => {
                const entry = parseFloat(p.entry_price || 0);
                const exit = parseFloat(p.exit_price || 0);
                const qty = parseFloat(p.quantity || 0);
                const pnl = (exit - entry) * qty;
                return sum + pnl;
            }, 0);
            incomeData = {
                items: closedDbPos.map(p => ({
                    symbol: p.symbol,
                    income: ((parseFloat(p.exit_price || 0) - parseFloat(p.entry_price || 0)) * parseFloat(p.quantity || 0)).toFixed(4),
                    time: new Date(p.close_time).getTime(),
                    info: p.close_reason
                })),
                totalPnl: parseFloat(total.toFixed(4))
            };
        } catch (e) {
            console.log("DB income fetch error:", e.message);
        }
        
        // 5. Seçili Parite Fiyatı (Ticker)
        let tickerData = cache.ticker[symbol]?.data;
        if (!tickerData || (now - (cache.ticker[symbol]?.ts || 0)) > CACHE_TTL_MS) {
            try {
                tickerData = await fapiPublic('/api/v3/ticker/24hr', { symbol: symbol.toUpperCase() });
                cache.ticker[symbol] = { data: tickerData, ts: now };
            } catch (e) {
                console.log("Ticker fetch error:", e.message);
            }
        }
        
        res.json({
            balance: balanceData,
            positions: positionsData || [],
            openOrders: openOrdersData || [],
            income: incomeData || { items: [], totalPnl: 0 },
            ticker: tickerData || null,
            binanceApiError: binanceApiError,
        });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});


// ─── Hesap Bakiyesi ───────────────────────────────────────────────────────
app.get('/api/binance/balance', async (req, res) => {
    const now = Date.now();
    if (cache.balance.data && (now - cache.balance.ts) < CACHE_TTL_MS) {
        return res.json(cache.balance.data);
    }
    try {
        const data = await fapi('/open/v1/account/spot');
        const balances = data.data?.accountAssets || data.data?.balances || data.balances || [];
        const quoteBal = balances.find(a => a.asset === QUOTE_ASSET) || {};
        const formatted = {
            walletBalance:    parseFloat(quoteBal.free || 0) + parseFloat(quoteBal.locked || 0),
            availableBalance: parseFloat(quoteBal.free || 0),
            unrealizedPnl:    0,
            marginBalance:    parseFloat(quoteBal.free || 0),
            totalInitialMargin: 0,
            quoteAsset:       QUOTE_ASSET,
            maxBudget:        MAX_BUDGET_PER_TRADE,
        };
        cache.balance.data = formatted;
        cache.balance.ts = now;
        res.json(formatted);
    } catch (e) {
        if (cache.balance.data) {
            console.log("⚠️ Balance API hatası! Eski önbellek verisi servis ediliyor...");
            return res.json(cache.balance.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Açık Futures Pozisyonları (Spot: Veritabanındaki OPEN işlemler ve anlık PnL)
app.get('/api/binance/positions', async (req, res) => {
    try {
        const openDbPos = await Position.find({ status: 'OPEN' });
        const positionsData = [];
        for (const p of openDbPos) {
            const sym = p.symbol;
            const tickerCache = cache.ticker[sym]?.data || {};
            const currentPrice = parseFloat(tickerCache.lastPrice || p.entry_price || 0);
            const entry = parseFloat(p.entry_price || 0);
            const qty = parseFloat(p.quantity || 0);
            const pnl = (currentPrice - entry) * qty;
            positionsData.push({
                symbol: sym,
                positionAmt: qty.toString(),
                entryPrice: entry.toString(),
                unRealizedProfit: pnl.toFixed(4),
                pnlPct: entry > 0 ? ((currentPrice - entry) / entry * 100).toFixed(2) : '0',
                marginType: 'spot',
                leverage: '1',
                liquidationPrice: '0',
                positionSide: 'LONG',
                markPrice: currentPrice.toString(),
                stop_loss_price: p.stop_loss_price || null,
                take_profit_price: p.take_profit_price || null,
                stars: p.star_label || p.position_tier || '',
                allocated_budget: (entry * qty).toFixed(2),
                open_time: p.open_time || null,
            });
        }
        res.json(positionsData);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Açık Emirler ─────────────────────────────────────────────────────────
app.get('/api/binance/open-orders', async (req, res) => {
    try {
        const symbol = req.query.symbol || 'BTCUSDT';
        const data = await fapi('/open/v1/orders', { symbol: symbol.toUpperCase() });
        const list = Array.isArray(data) ? data : (data?.orders || []);
        const formatted = list.filter(o => o.status === 'NEW' || o.status === 'PARTIALLY_FILLED').map(o => ({
            symbol: o.symbol,
            side: o.side,
            type: o.type,
            origQty: o.quantity || o.origQty,
            price: o.price,
            status: o.status,
            orderId: o.orderId || o.id
        }));
        res.json(formatted);
    } catch (e) {
        if (cache.openOrders.data) {
            return res.json(cache.openOrders.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Son İşlem Geçmişi (Spot) ─────────────────────────────────────────────
app.get('/api/binance/trade-history', async (req, res) => {
    try {
        const symbol = req.query.symbol || 'BTCUSDT';
        const limit  = parseInt(req.query.limit) || 20;
        const data   = await fapi('/open/v1/orders', { symbol, limit });
        const list = Array.isArray(data) ? data : (data?.orders || []);
        res.json(list.filter(o => o.status === 'FILLED'));
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── PnL Özeti (son 7 gün - Lokal Veritabanından) ──────────────────────────
app.get('/api/binance/income', async (req, res) => {
    const now = Date.now();
    if (cache.income.data && (now - cache.income.ts) < CACHE_TTL_MS) {
        return res.json(cache.income.data);
    }
    try {
        const closedDbPos = await Position.find({ status: 'CLOSED' }).sort({ close_time: -1 }).limit(100);
        const total = closedDbPos.reduce((sum, p) => {
            const entry = parseFloat(p.entry_price || 0);
            const exit = parseFloat(p.exit_price || 0);
            const qty = parseFloat(p.quantity || 0);
            const pnl = (exit - entry) * qty;
            return sum + pnl;
        }, 0);
        const formatted = {
            items: closedDbPos.map(p => ({
                symbol: p.symbol,
                income: ((parseFloat(p.exit_price || 0) - parseFloat(p.entry_price || 0)) * parseFloat(p.quantity || 0)).toFixed(4),
                time: new Date(p.close_time).getTime(),
                info: p.close_reason
            })),
            totalPnl: parseFloat(total.toFixed(4))
        };
        cache.income.data = formatted;
        cache.income.ts = now;
        res.json(formatted);
    } catch (e) {
        if (cache.income.data) {
            return res.json(cache.income.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Kline (Mum verisi) ───────────────────────────────────────────────────
app.get('/api/binance/klines', async (req, res) => {
    try {
        const { symbol = 'BTCUSDT', interval = '15m', limit = 100 } = req.query;
        const data = await fapiPublic('/api/v3/klines', { symbol: symbol.toUpperCase(), interval, limit });
        const formatted = data.map(k => ({
            time:   Math.floor(k[0] / 1000),
            open:   parseFloat(k[1]),
            high:   parseFloat(k[2]),
            low:    parseFloat(k[3]),
            close:  parseFloat(k[4]),
            volume: parseFloat(k[5]),
        }));
        res.json(formatted);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Order Book (Derinlik) ────────────────────────────────────────────────
app.get('/api/binance/orderbook', async (req, res) => {
    const symbol = req.query.symbol || 'BTCUSDT';
    const now = Date.now();
    const symbolCache = cache.orderbook[symbol];
    if (symbolCache && (now - symbolCache.ts) < CACHE_TTL_MS) {
        return res.json(symbolCache.data);
    }
    try {
        const limit  = 20; // Binance geçerli değer: 5,10,20,50,100
        const data = await fapiPublic('/api/v3/depth', { symbol: symbol.toUpperCase(), limit });
        const formatted = {
            bids: data.bids.slice(0, 10).map(([p, q]) => ({ price: parseFloat(p), qty: parseFloat(q) })),
            asks: data.asks.slice(0, 10).map(([p, q]) => ({ price: parseFloat(p), qty: parseFloat(q) })),
        };
        cache.orderbook[symbol] = { data: formatted, ts: now };
        res.json(formatted);
    } catch (e) {
        if (symbolCache) {
            return res.json(symbolCache.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Anlık Fiyat ──────────────────────────────────────────────────────────
app.get('/api/binance/ticker', async (req, res) => {
    const { symbol = 'BTCUSDT' } = req.query;
    const now = Date.now();
    const symbolCache = cache.ticker[symbol];
    if (symbolCache && (now - symbolCache.ts) < CACHE_TTL_MS) {
        return res.json(symbolCache.data);
    }
    try {
        const data = await fapiPublic('/api/v3/ticker/24hr', { symbol: symbol.toUpperCase() });
        cache.ticker[symbol] = { data: data, ts: now };
        res.json(data);
    } catch (e) {
        if (symbolCache) {
            return res.json(symbolCache.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Tüm Spot Coin'leri (QUOTE_ASSET bazlı) ──────────────────────────────
app.get('/api/binance/all-tickers', async (req, res) => {
    const now = Date.now();
    // all-tickers daha büyük bir veridir, 30 saniye cache uygulayalım
    if (cache.allTickers.data && (now - cache.allTickers.ts) < 30000) {
        return res.json(cache.allTickers.data);
    }
    try {
        const data = await fapiPublic('/api/v3/ticker/24hr');
        const usdt = data
            .filter(t => {
                if (!t.symbol.endsWith(QUOTE_ASSET)) return false;
                const base = t.symbol.slice(0, -QUOTE_ASSET.length);
                return !STABLECOIN_BASES.has(base);
            })
            .map(t => ({
                symbol:         t.symbol,
                lastPrice:      parseFloat(t.lastPrice),
                priceChange:    parseFloat(t.priceChange),
                priceChangePct: parseFloat(t.priceChangePercent),
                highPrice:      parseFloat(t.highPrice),
                lowPrice:       parseFloat(t.lowPrice),
                volume:         parseFloat(t.volume),
                quoteVolume:    parseFloat(t.quoteVolume),
                count:          parseInt(t.count || 0),
            }))
            .sort((a, b) => b.quoteVolume - a.quoteVolume);
        cache.allTickers.data = usdt;
        cache.allTickers.ts = now;
        res.json(usdt);
    } catch (e) {
        if (cache.allTickers.data) {
            return res.json(cache.allTickers.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ==================== MONGODB BAĞLANTISI ====================
mongoose.connect('mongodb://localhost:27017/trade_bot')
    .then(() => console.log('✅ Dashboard Backend MongoDB bağlantısı başarılı.'))
    .catch(err => console.error('❌ MongoDB bağlantı hatası:', err));

// Şemalar (strict: false → Python'un yazdığı her alanı okur)
const Position = mongoose.model('Position', new mongoose.Schema({}, { collection: 'positions', strict: false }));
const Signal   = mongoose.model('Signal',   new mongoose.Schema({}, { collection: 'signals',   strict: false }));

// ==================== REST API ====================

// Sağlık kontrolü
app.get('/api/health', (req, res) => res.json({ status: 'ok', ts: new Date() }));

// Açık pozisyonlar
app.get('/api/positions/open', async (req, res) => {
    try {
        const positions = await Position.find({ status: 'OPEN' }).sort({ entry_time: -1 });
        res.json(positions);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Kapalı işlem geçmişi (son 20)
app.get('/api/positions/history', async (req, res) => {
    try {
        const history = await Position.find({ status: 'CLOSED' }).sort({ exit_time: -1 }).limit(20);
        res.json(history);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Bekleyen sinyaller
app.get('/api/signals/pending', async (req, res) => {
    try {
        const signals = await Signal.find({ status: 'PENDING' }).sort({ timestamp: -1 });
        res.json(signals);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Son sinyaller (tüm statuslar, son 30)
app.get('/api/signals/recent', async (req, res) => {
    try {
        const signals = await Signal.find({}).sort({ timestamp: -1 }).limit(30);
        res.json(signals);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Genel istatistikler
app.get('/api/stats', async (req, res) => {
    try {
        const [totalSignals, executedSignals, pendingSignals, openPositions, closedPositions] = await Promise.all([
            Signal.countDocuments(),
            Signal.countDocuments({ status: 'EXECUTED' }),
            Signal.countDocuments({ status: 'PENDING' }),
            Position.countDocuments({ status: 'OPEN' }),
            Position.countDocuments({ status: 'CLOSED' }),
        ]);
        res.json({ totalSignals, executedSignals, pendingSignals, openPositions, closedPositions });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Pozisyon Kapat (Market Close) ─────────────────────────────────────────
app.post('/api/positions/close', async (req, res) => {
    try {
        const { symbol, quantity, side } = req.body;
        if (!symbol || !quantity) {
            return res.status(400).json({ error: 'Eksik parametre' });
        }
        
        const posSide = side || 'LONG';
        const orderSide = posSide === 'LONG' ? 'SELL' : 'BUY';
        
        // Binance'te kapatma emri gönder (Spot: positionSide parametresi kaldırılır)
        const order = await fapiPost('/open/v1/orders', {
            symbol: symbol.toUpperCase(),
            side: orderSide,
            type: 'MARKET',
            quantity: Math.abs(parseFloat(quantity)).toString(),
        });
        
        // Binance.TR yanıtı: {code:0, msg:'Success', data:{orderId:..., executedPrice:...}}
        const orderData = order && order.code === 0 ? (order.data || order) : null;
        
        if (orderData && orderData.orderId) {
            const exitPrice = parseFloat(orderData.executedPrice || orderData.avgPrice || 0);
            
            // MongoDB'deki ilgili açık pozisyonu bul ve güncelle
            const openPos = await Position.findOne({ symbol: symbol, status: 'OPEN' });
            if (openPos) {
                const entryPrice = parseFloat(openPos.entry_price || 0);
                let pnlPct = 0;
                if (entryPrice > 0 && exitPrice > 0) {
                    pnlPct = ((exitPrice - entryPrice) / entryPrice) * 100;
                    if (posSide === 'SHORT') pnlPct = -pnlPct;
                }
                
                await Position.updateOne(
                    { _id: openPos._id },
                    {
                        $set: {
                            status: 'CLOSED',
                            close_time: new Date(),
                            close_reason: 'MANUAL_CLOSE',
                            exit_price: exitPrice || null,
                            final_pnl_pct: parseFloat(pnlPct.toFixed(4)),
                        }
                    }
                );
            }
            res.json({ success: true, order: orderData });
        } else {
            console.error('Pozisyon kapatma hatası:', JSON.stringify(order));
            res.status(500).json({ error: `Binance pozisyon kapatma emri başarısız: ${order?.msg || 'Bilinmeyen hata'}` });
        }
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Sinyali Hemen İşleme Al (Force Execute) ─────────────────────────────────
app.post('/api/signals/execute', async (req, res) => {
    try {
        const { signalId } = req.body;
        if (!signalId) return res.status(400).json({ error: 'Eksik sinyal ID' });
        
        const sig = await Signal.findById(signalId);
        if (!sig) return res.status(404).json({ error: 'Sinyal bulunamadı' });
        if (sig.status !== 'PENDING') return res.status(400).json({ error: 'Sinyal beklemede değil' });
        
        // Fiyat al ve miktar hesapla
        const currentPrice = sig.price;
        const budget = 50.0; // max_budget_per_trade_usdt varsayılan
        const positionPct = sig.position_size_pct || 100;
        const allocated = budget * (positionPct / 100);
        
        // Kaldıraç 1x (Spot Trading)
        const rawQty = allocated / currentPrice;
        const quantity = Math.max(Math.round(rawQty * 1000) / 1000, 0.001);
        
        // Binance'te Spot alım emri aç (positionSide parametresi kaldırılır)
        const order = await fapiPost('/open/v1/orders', {
            symbol: sig.symbol,
            side: 'BUY',
            type: 'MARKET',
            quantity: quantity.toString(),
        });
        
        // Binance.TR yanıtı: {code:0, msg:'Success', data:{orderId:..., executedPrice:...}}
        const orderData = order && order.code === 0 ? (order.data || order) : null;
        
        if (orderData && orderData.orderId) {
            const fillPrice = parseFloat(orderData.executedPrice || orderData.avgPrice || currentPrice) || currentPrice;
            
            // Sinyali EXECUTED yap
            await Signal.updateOne(
                { _id: sig._id },
                {
                    $set: {
                        status: 'EXECUTED',
                        processed_at: new Date(),
                        note: 'Dashboard üzerinden manuel tetiklendi',
                    }
                }
            );
            
            // Yeni pozisyon belgesini MongoDB'ye kaydet
            const slPct = sig.stop_loss_pct || 3.0;
            const tpPct = sig.take_profit_pct || 6.0;
            
            const positionDoc = new Position({
                symbol: sig.symbol,
                side: 'LONG',
                entry_price: fillPrice,
                stop_loss_price: Math.round(fillPrice * (1 - slPct / 100) * 1000000) / 1000000,
                take_profit_price: Math.round(fillPrice * (1 + tpPct / 100) * 1000000) / 1000000,
                quantity: quantity,
                order_id: orderData.orderId,
                signal_id: sig._id,
                matched_pattern: sig.matched_pattern || '',
                total_score: sig.total_score || 0,
                status: 'OPEN',
                open_time: new Date(),
                close_time: null,
                close_reason: null,
                exit_price: null,
                final_pnl_pct: null,
            });
            await positionDoc.save();
            
            res.json({ success: true, order: orderData });
        } else {
            console.error('Sinyal tetikleme hatası:', JSON.stringify(order));
            res.status(500).json({ error: `Binance emri gönderilemedi: ${order?.msg || 'Bilinmeyen hata'}` });
        }
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Manuel Emir Gönderimi (Order Panel Entegrasyonu) ───────────────────────
app.post('/api/orders/place', async (req, res) => {
    try {
        const { symbol, side, type, quantity, price, stopLossPct, takeProfitPct } = req.body;
        if (!symbol || !side || !type || !quantity) {
            return res.status(400).json({ error: 'Eksik zorunlu parametreler' });
        }

        // 1. Spot trading has no leverage, skip leverage setting

        // 2. Emir Parametrelerini Hazırla (positionSide Spot'ta bulunmaz)
        const orderParams = {
            symbol: symbol.toUpperCase(),
            side: side.toUpperCase(),
            type: type.toUpperCase(),
            quantity: Math.abs(parseFloat(quantity)).toString(),
        };

        if (type.toUpperCase() === 'LIMIT') {
            if (!price) return res.status(400).json({ error: 'Limit emir için fiyat girilmelidir' });
            orderParams.price = price.toString();
            orderParams.timeInForce = 'GTC';
        }

        // 3. Binance'te İşlemi Aç (Spot orders endpoint)
        const order = await fapiPost('/open/v1/orders', orderParams);

        // Binance.TR yanıtı: {code:0, msg:'Success', data:{orderId:..., executedPrice:...}}
        const orderData = order && order.code === 0 ? (order.data || order) : null;
        
        if (orderData && orderData.orderId) {
            // 4. Eğer AÇILIŞ emri (BUY) ise MongoDB'ye kaydet
            const isOpening = side.toUpperCase() === 'BUY';
            
            if (isOpening) {
                const fillPrice = parseFloat(orderData.executedPrice || orderData.avgPrice || price || 0) || parseFloat(price || 0);
                const slPct = parseFloat(stopLossPct) || 0;
                const tpPct = parseFloat(takeProfitPct) || 0;
                
                let stopLossPrice = null;
                let takeProfitPrice = null;

                if (slPct > 0) {
                    stopLossPrice = Math.round(fillPrice * (1 - slPct / 100) * 1000000) / 1000000;
                }
                if (tpPct > 0) {
                    takeProfitPrice = Math.round(fillPrice * (1 + tpPct / 100) * 1000000) / 1000000;
                }

                const positionDoc = new Position({
                    symbol: symbol.toUpperCase(),
                    side: 'LONG',
                    entry_price: fillPrice,
                    stop_loss_price: stopLossPrice,
                    take_profit_price: takeProfitPrice,
                    quantity: Math.abs(parseFloat(quantity)),
                    order_id: orderData.orderId,
                    signal_id: null,
                    matched_pattern: 'MANUAL_TRADE',
                    total_score: 0,
                    status: 'OPEN',
                    open_time: new Date(),
                    close_time: null,
                    close_reason: null,
                    exit_price: null,
                    final_pnl_pct: null,
                });
                await positionDoc.save();
            }

            res.json({ success: true, order: orderData });
        } else {
            console.error('Manuel emir hatası:', JSON.stringify(order));
            res.status(500).json({ error: `Binance emri gönderilemedi: ${order?.msg || 'Bilinmeyen hata'}` });
        }
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Pozisyon Yönünü Anında Tersine Çevirme (Reverse) ────────────────────────
app.post('/api/positions/reverse', async (req, res) => {
    return res.status(400).json({ error: 'Spot piyasada kaldıraçlı işlemler veya açığa satış (SHORT) olmadığı için pozisyon yönünü tersine çevirme özelliği desteklenmemektedir.' });
});

// ─── Pozisyon Korumalarını Güncelle (SL/TP Ayarla) ───────────────────────────
app.post('/api/positions/update-protection', async (req, res) => {
    try {
        const { symbol, stopLossPrice, takeProfitPrice } = req.body;
        if (!symbol) {
            return res.status(400).json({ error: 'Eksik parite bilgisi' });
        }

        const openPos = await Position.findOne({ symbol: symbol.toUpperCase(), status: 'OPEN' });
        if (!openPos) {
            return res.status(404).json({ error: 'Açık pozisyon bulunamadı' });
        }

        const updates = {};
        if (stopLossPrice !== undefined) updates.stop_loss_price = stopLossPrice ? parseFloat(stopLossPrice) : null;
        if (takeProfitPrice !== undefined) updates.take_profit_price = takeProfitPrice ? parseFloat(takeProfitPrice) : null;

        await Position.updateOne({ _id: openPos._id }, { $set: updates });
        res.json({ success: true, updates });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});


// ==================== WEBSOCKET & CANLI LOG AKIŞI ====================
const LOG_FILE = path.join(__dirname, '../scanner.log');
const TAIL_LINES = 50; // İlk bağlantıda gönderilecek son satır sayısı

/**
 * Bir dosyanın son N satırını senkron okur.
 * Büyük dosyalarda tüm içeriği belleğe yüklemekten kaçınmak için
 * sondan geriye doğru chunk okur.
 */
function tailFile(filePath, lines = TAIL_LINES) {
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const all = content.split('\n');
        return all.slice(-lines).join('\n');
    } catch {
        return '';
    }
}

io.on('connection', (socket) => {
    console.log(`📡 Arayüz bağlandı: ${socket.id}`);

    if (!fs.existsSync(LOG_FILE)) {
        socket.emit('log_init', '[UYARI] scanner.log henüz oluşturulmadı. Scanner başlatılınca akış başlar.');
        return;
    }

    // İlk bağlantıda son 50 satırı gönder
    socket.emit('log_init', tailFile(LOG_FILE, TAIL_LINES));

    // Yeni satırları izle (tail -f mantığı)
    let fileSize = fs.statSync(LOG_FILE).size;

    const watcher = fs.watch(LOG_FILE, (event) => {
        if (event !== 'change') return;
        try {
            const stat = fs.statSync(LOG_FILE);
            if (stat.size <= fileSize) {
                // Dosya sıfırlandı (log rotate)
                fileSize = stat.size;
                return;
            }
            const stream = fs.createReadStream(LOG_FILE, { start: fileSize, end: stat.size });
            const chunks = [];
            stream.on('data', (chunk) => chunks.push(chunk));
            stream.on('end', () => {
                const newData = Buffer.concat(chunks).toString('utf-8');
                if (newData.trim()) socket.emit('log_stream', newData);
            });
            fileSize = stat.size;
        } catch (err) {
            console.error('Log izleme hatası:', err.message);
        }
    });

    socket.on('disconnect', () => {
        watcher.close();
        console.log(`🔌 Arayüz ayrıldı: ${socket.id}`);
    });
});

// ==================== FRONTEND STATIC SERVIS ====================
const FRONTEND_DIST = path.join(__dirname, '../dashboard_frontend/dist');
if (fs.existsSync(FRONTEND_DIST)) {
    app.use(express.static(FRONTEND_DIST));
    // React SPA için tüm bilinmeyen route'ları index.html'e yönlendir (Hata önleyici middleware)
    app.use((req, res, next) => {
        if (req.method === 'GET' && !req.url.startsWith('/api')) {
            return res.sendFile(path.join(FRONTEND_DIST, 'index.html'));
        }
        next();
    });
    console.log(`📦 Frontend static dosyaları servis ediliyor: ${FRONTEND_DIST}`);
} else {
    app.get('/', (req, res) => {
        res.json({ message: 'Jarvis API aktif. Dashboard için: cd dashboard_frontend && npm run build' });
    });
}

// ==================== SUNUCU BAŞLAT ====================
const PORT = process.env.PORT || 5001;
server.listen(PORT, () => {
    console.log(`🚀 Jarvis API & WebSocket Sunucusu → http://localhost:${PORT}`);
});
