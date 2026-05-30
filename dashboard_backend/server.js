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
    const res = await axios.get(url, { headers: { 'X-MBX-APIKEY': API_KEY }, timeout: 10000 });
    return res.data;
}

async function fapiPublic(endpoint, params = {}) {
    const url = `${FAPI_BASE}${endpoint}`;
    const res = await axios.get(url, { params, timeout: 10000 });
    return res.data;
}

// ─── Hesap Bakiyesi ───────────────────────────────────────────────────────
app.get('/api/binance/balance', async (req, res) => {
    try {
        const data = await fapi('/fapi/v2/account');
        const usdt = data.assets?.find(a => a.asset === 'USDT') || {};
        res.json({
            walletBalance:    parseFloat(usdt.walletBalance    || 0),
            availableBalance: parseFloat(usdt.availableBalance || 0),
            unrealizedPnl:    parseFloat(usdt.unrealizedProfit || 0),
            marginBalance:    parseFloat(usdt.marginBalance    || 0),
            totalInitialMargin: parseFloat(data.totalInitialMargin || 0),
        });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Açık Futures Pozisyonları ────────────────────────────────────────────
app.get('/api/binance/positions', async (req, res) => {
    try {
        const data = await fapi('/fapi/v2/positionRisk');
        const open = data.filter(p => parseFloat(p.positionAmt) !== 0);
        res.json(open);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Açık Emirler ─────────────────────────────────────────────────────────
app.get('/api/binance/open-orders', async (req, res) => {
    try {
        const data = await fapi('/fapi/v1/openOrders');
        res.json(data);
    } catch (e) {
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
    try {
        const startTime = Date.now() - 7 * 24 * 60 * 60 * 1000;
        const data = await fapi('/fapi/v1/income', {
            incomeType: 'REALIZED_PNL',
            startTime,
            limit: 100,
        });
        const totalPnl = data.reduce((s, x) => s + parseFloat(x.income), 0);
        res.json({ items: data, totalPnl: parseFloat(totalPnl.toFixed(4)) });
    } catch (e) {
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
    try {
        const symbol = req.query.symbol || 'BTCUSDT';
        const limit  = 20; // Binance geçerli değer: 5,10,20,50,100
        const data = await fapiPublic('/fapi/v1/depth', { symbol, limit });
        res.json({
            bids: data.bids.slice(0, 10).map(([p, q]) => ({ price: parseFloat(p), qty: parseFloat(q) })),
            asks: data.asks.slice(0, 10).map(([p, q]) => ({ price: parseFloat(p), qty: parseFloat(q) })),
        });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Anlık Fiyat ──────────────────────────────────────────────────────────
app.get('/api/binance/ticker', async (req, res) => {
    try {
        const { symbol = 'BTCUSDT' } = req.query;
        const data = await fapiPublic('/fapi/v1/ticker/24hr', { symbol });
        res.json(data);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Tüm USDT-P Coin'leri ─────────────────────────────────────────────────
app.get('/api/binance/all-tickers', async (req, res) => {
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
        res.json(usdt);
    } catch (e) {
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
    app.get('/{*path}', (req, res) => {
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
