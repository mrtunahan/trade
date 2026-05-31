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

// ==================== BINANCE FUTURES PROXY ====================
const FAPI_BASE   = 'https://fapi.binance.com';
const API_KEY     = process.env.BINANCE_API_KEY     || '';
const API_SECRET  = process.env.BINANCE_API_SECRET  || '';

function binanceSign(params) {
    const qs = new URLSearchParams({ ...params, timestamp: Date.now() }).toString();
    const sig = crypto.createHmac('sha256', API_SECRET).update(qs).digest('hex');
    return qs + '&signature=' + sig;
}

async function fapi(endpoint, params = {}) {
    const qs = binanceSign(params);
    const url = `${FAPI_BASE}${endpoint}?${qs}`;
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
    const url = `${FAPI_BASE}${endpoint}`;
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
    const qs = binanceSign(params);
    const url = `${FAPI_BASE}${endpoint}?${qs}`;
    const res = await axios.post(url, null, { 
        headers: { 
            'X-MBX-APIKEY': API_KEY,
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
        const symbol = req.query.symbol || 'BTCUSDT';
        const now = Date.now();
        
        // 1. Hesap Bakiyesi (Cache veya Sıralı İstek)
        let balanceData = cache.balance.data;
        if (!balanceData || (now - cache.balance.ts) > CACHE_TTL_MS) {
            try {
                const data = await fapi('/fapi/v2/account');
                const usdt = data.assets?.find(a => a.asset === 'USDT') || {};
                balanceData = {
                    walletBalance:    parseFloat(usdt.walletBalance    || 0),
                    availableBalance: parseFloat(usdt.availableBalance || 0),
                    unrealizedPnl:    parseFloat(usdt.unrealizedProfit || 0),
                    marginBalance:    parseFloat(usdt.marginBalance    || 0),
                    totalInitialMargin: parseFloat(data.totalInitialMargin || 0),
                };
                cache.balance.data = balanceData;
                cache.balance.ts = now;
            } catch (e) {
                console.log("Balance fetch error:", e.message);
            }
            await new Promise(r => setTimeout(r, 200)); // 200ms stagger gecikmesi
        }
        
        // 2. Açık Pozisyonlar
        let positionsData = cache.positions.data;
        if (!positionsData || (now - cache.positions.ts) > CACHE_TTL_MS) {
            try {
                const data = await fapi('/fapi/v2/positionRisk');
                positionsData = data.filter(p => parseFloat(p.positionAmt) !== 0);
                cache.positions.data = positionsData;
                cache.positions.ts = now;
            } catch (e) {
                console.log("Positions fetch error:", e.message);
            }
            await new Promise(r => setTimeout(r, 200)); // 200ms stagger gecikmesi
        }
        
        // 3. Açık Emirler
        let openOrdersData = cache.openOrders.data;
        if (!openOrdersData || (now - cache.openOrders.ts) > CACHE_TTL_MS) {
            try {
                openOrdersData = await fapi('/fapi/v1/openOrders');
                cache.openOrders.data = openOrdersData;
                cache.openOrders.ts = now;
            } catch (e) {
                console.log("Open orders fetch error:", e.message);
            }
            await new Promise(r => setTimeout(r, 200)); // 200ms stagger gecikmesi
        }
        
        // 4. Son 7 Günlük Gelir/PnL Özeti
        let incomeData = cache.income.data;
        if (!incomeData || (now - cache.income.ts) > 8000) { // Gelir verisi daha uzun kalabilir
            try {
                const startTime = Date.now() - 7 * 24 * 60 * 60 * 1000;
                const data = await fapi('/fapi/v1/income', {
                    incomeType: 'REALIZED_PNL',
                    startTime,
                    limit: 100,
                });
                const totalPnl = data.reduce((s, x) => s + parseFloat(x.income), 0);
                incomeData = { items: data, totalPnl: parseFloat(totalPnl.toFixed(4)) };
                cache.income.data = incomeData;
                cache.income.ts = now;
            } catch (e) {
                console.log("Income fetch error:", e.message);
            }
            await new Promise(r => setTimeout(r, 200));
        }
        
        // 5. Seçili Parite Fiyatı (Ticker)
        let tickerData = cache.ticker[symbol]?.data;
        if (!tickerData || (now - (cache.ticker[symbol]?.ts || 0)) > CACHE_TTL_MS) {
            try {
                tickerData = await fapiPublic('/fapi/v1/ticker/24hr', { symbol });
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
        const data = await fapi('/fapi/v2/account');
        const usdt = data.assets?.find(a => a.asset === 'USDT') || {};
        const formatted = {
            walletBalance:    parseFloat(usdt.walletBalance    || 0),
            availableBalance: parseFloat(usdt.availableBalance || 0),
            unrealizedPnl:    parseFloat(usdt.unrealizedProfit || 0),
            marginBalance:    parseFloat(usdt.marginBalance    || 0),
            totalInitialMargin: parseFloat(data.totalInitialMargin || 0),
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

// ─── Açık Futures Pozisyonları ────────────────────────────────────────────
app.get('/api/binance/positions', async (req, res) => {
    const now = Date.now();
    if (cache.positions.data && (now - cache.positions.ts) < CACHE_TTL_MS) {
        return res.json(cache.positions.data);
    }
    try {
        const data = await fapi('/fapi/v2/positionRisk');
        const open = data.filter(p => parseFloat(p.positionAmt) !== 0);
        cache.positions.data = open;
        cache.positions.ts = now;
        res.json(open);
    } catch (e) {
        if (cache.positions.data) {
            return res.json(cache.positions.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Açık Emirler ─────────────────────────────────────────────────────────
app.get('/api/binance/open-orders', async (req, res) => {
    const now = Date.now();
    if (cache.openOrders.data && (now - cache.openOrders.ts) < CACHE_TTL_MS) {
        return res.json(cache.openOrders.data);
    }
    try {
        const data = await fapi('/fapi/v1/openOrders');
        cache.openOrders.data = data;
        cache.openOrders.ts = now;
        res.json(data);
    } catch (e) {
        if (cache.openOrders.data) {
            return res.json(cache.openOrders.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Son İşlem Geçmişi ────────────────────────────────────────────────────
app.get('/api/binance/trade-history', async (req, res) => {
    try {
        const symbol = req.query.symbol || 'BTCUSDT';
        const limit  = parseInt(req.query.limit) || 20;
        const data   = await fapi('/fapi/v1/userTrades', { symbol, limit });
        res.json(data);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── PnL Özeti (son 7 gün) ────────────────────────────────────────────────
app.get('/api/binance/income', async (req, res) => {
    const now = Date.now();
    if (cache.income.data && (now - cache.income.ts) < CACHE_TTL_MS) {
        return res.json(cache.income.data);
    }
    try {
        const startTime = Date.now() - 7 * 24 * 60 * 60 * 1000;
        const data = await fapi('/fapi/v1/income', {
            incomeType: 'REALIZED_PNL',
            startTime,
            limit: 100,
        });
        const totalPnl = data.reduce((s, x) => s + parseFloat(x.income), 0);
        const formatted = { items: data, totalPnl: parseFloat(totalPnl.toFixed(4)) };
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
        const data = await fapiPublic('/fapi/v1/klines', { symbol, interval, limit });
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
        const data = await fapiPublic('/fapi/v1/depth', { symbol, limit });
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
        const data = await fapiPublic('/fapi/v1/ticker/24hr', { symbol });
        cache.ticker[symbol] = { data: data, ts: now };
        res.json(data);
    } catch (e) {
        if (symbolCache) {
            return res.json(symbolCache.data);
        }
        res.status(500).json({ error: e.message });
    }
});

// ─── Tüm USDT-P Coin'leri ─────────────────────────────────────────────────
app.get('/api/binance/all-tickers', async (req, res) => {
    const now = Date.now();
    // all-tickers daha büyük bir veridir, 30 saniye cache uygulayalım
    if (cache.allTickers.data && (now - cache.allTickers.ts) < 30000) {
        return res.json(cache.allTickers.data);
    }
    try {
        const data = await fapiPublic('/fapi/v1/ticker/24hr');
        const usdt = data
            .filter(t => t.symbol.endsWith('USDT'))
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
        
        // Binance'te kapatma emri gönder
        const order = await fapiPost('/fapi/v1/order', {
            symbol: symbol.toUpperCase(),
            side: orderSide,
            positionSide: posSide,
            type: 'MARKET',
            quantity: Math.abs(parseFloat(quantity)).toString(),
        });
        
        if (order && order.orderId) {
            const exitPrice = parseFloat(order.avgPrice || 0);
            
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
            res.json({ success: true, order });
        } else {
            res.status(500).json({ error: 'Binance pozisyon kapatma emri başarısız oldu' });
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
        
        // Kaldıraç 5x varsayılan
        const rawQty = (allocated * 5) / currentPrice;
        const quantity = Math.max(Math.round(rawQty * 1000) / 1000, 0.001);
        
        // Binance'te LONG pozisyon aç
        const order = await fapiPost('/fapi/v1/order', {
            symbol: sig.symbol,
            side: 'BUY',
            positionSide: 'LONG',
            type: 'MARKET',
            quantity: quantity.toString(),
        });
        
        if (order && order.orderId) {
            const fillPrice = parseFloat(order.avgPrice || currentPrice);
            
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
                order_id: order.orderId,
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
            
            res.json({ success: true, order });
        } else {
            res.status(500).json({ error: 'Binance emri gönderilemedi' });
        }
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
    // React SPA için tüm bilinmeyen route'ları index.html'e yönlendir (Express v5 uyumlu)
    app.get(/.*/, (req, res) => {
        res.sendFile(path.join(FRONTEND_DIST, 'index.html'));
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
