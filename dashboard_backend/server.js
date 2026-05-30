// ============================================================================
// dashboard_backend/server.js - Jarvis Monitor API & WebSocket Sunucusu
// ============================================================================
// MongoDB'deki sinyal/pozisyon verilerini REST API ile sunar.
// scanner.log dosyasını tail -f mantığıyla WebSocket üzerinden arayüze basar.
// ============================================================================

const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const mongoose = require('mongoose');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: '*', methods: ['GET', 'POST'] }
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
    // React SPA için tüm bilinmeyen route'ları index.html'e yönlendir
    app.use((req, res) => {
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
