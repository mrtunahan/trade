// ============================================================================
// src/App.jsx - Jarvis Trading Dashboard v2 — Binance Futures Full Monitor
// ============================================================================
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { io } from 'socket.io-client';
import { AreaChart, Area, ResponsiveContainer, Tooltip as ReTooltip, XAxis } from 'recharts';
import {
  Terminal, Activity, Briefcase, History, TrendingUp, Wifi, WifiOff,
  Zap, DollarSign, BarChart2, BookOpen, RefreshCw, ChevronDown,
  Globe, Search, ArrowUp, ArrowDown,
} from 'lucide-react';

const API_URL = 'http://localhost:5001';
const socket  = io(API_URL, { transports: ['websocket'] });

const SYMBOLS = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','ADAUSDT'];
const INTERVALS = ['1m','5m','15m','1h','4h','1d'];

// ── Yardımcılar ──────────────────────────────────────────────────────────────
function fmt(v, d = 4) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return n.toFixed(d);
}
function fmtPct(v) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}
function splitSym(s = '') {
  if (s.endsWith('USDT')) return [s.replace('USDT', ''), 'USDT'];
  if (s.endsWith('TRY'))  return [s.replace('TRY', ''),  'TRY'];
  return [s, ''];
}

// ── Küçük bileşenler ─────────────────────────────────────────────────────────
function Badge({ label, color = 'cyan' }) {
  const map = { cyan:'border-cyan-700 text-cyan-400 bg-cyan-950', green:'border-green-700 text-green-400 bg-green-950', red:'border-red-800 text-red-400 bg-red-950', yellow:'border-yellow-700 text-yellow-400 bg-yellow-950', purple:'border-purple-700 text-purple-400 bg-purple-950', gray:'border-gray-700 text-gray-400 bg-gray-900' };
  return <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${map[color] || map.gray}`}>{label}</span>;
}
function SectionHeader({ icon: Icon, title, children }) {
  return (
    <div className="flex items-center justify-between mb-3 border-b border-cyan-900 pb-2">
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-cyan-500" />
        <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest">{title}</span>
      </div>
      {children}
    </div>
  );
}
function StatCard({ icon: Icon, label, value, sub, color = 'text-cyan-400' }) {
  return (
    <div className="bg-gray-900 border border-cyan-900 rounded-lg p-3 flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-[10px] text-gray-500 uppercase tracking-widest">
        <Icon size={12} />{label}
      </div>
      <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[10px] text-gray-500">{sub}</div>}
    </div>
  );
}

// ── TradingView Advanced Chart ───────────────────────────────────────────────
const TV_INTERVAL_MAP = { '1m':'1', '5m':'5', '15m':'15', '1h':'60', '4h':'240', '1d':'D' };

function TradingViewChart({ symbol, interval }) {
  const containerRef = useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.innerHTML = '';
    const tvSymbol   = `BINANCE:${symbol}.P`;
    const tvInterval = TV_INTERVAL_MAP[interval] || '15';

    const init = () => {
      if (!window.TradingView) return;
      new window.TradingView.widget({
        autosize:            true,
        symbol:              tvSymbol,
        interval:            tvInterval,
        timezone:            'Europe/Istanbul',
        theme:               'dark',
        style:               '1',
        locale:              'tr',
        enable_publishing:   false,
        withdateranges:      true,
        hide_side_toolbar:   false,
        allow_symbol_change: false,
        save_image:          true,
        container_id:        'tv_chart_main',
        studies: ['RSI@tv-basicstudies', 'MACD@tv-basicstudies'],
      });
    };

    if (window.TradingView) {
      init();
    } else {
      const script = document.createElement('script');
      script.src   = 'https://s3.tradingview.com/tv.js';
      script.async = true;
      script.onload = init;
      document.head.appendChild(script);
    }

    return () => { if (el) el.innerHTML = ''; };
  }, [symbol, interval]);

  return <div id="tv_chart_main" ref={containerRef} style={{ width:'100%', height:'100%' }} />;
}

// ── Symbol Search Dropdown ────────────────────────────────────────────────────
function SymbolSearch({ symbols, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [q,    setQ]    = useState('');
  const wrapRef = useRef(null);

  useEffect(() => {
    const h = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const base = value.replace('USDT','');
  const filtered = symbols
    .filter(s => s.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 100);

  return (
    <div ref={wrapRef} className="relative">
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 bg-gray-900 border border-cyan-800 text-cyan-200 text-xs font-bold rounded px-3 py-1.5 hover:border-cyan-500 transition-colors min-w-[140px]">
        <span>{base}<span className="text-gray-500 font-normal">/USDT</span></span>
        <ChevronDown size={11} className="text-cyan-600 ml-auto" />
      </button>
      {open && (
        <div className="absolute top-full left-0 z-50 mt-1 bg-gray-900 border border-cyan-900 rounded-lg w-52 shadow-2xl">
          <div className="p-2 border-b border-gray-800">
            <div className="relative">
              <Search size={11} className="absolute left-2 top-2 text-gray-500" />
              <input autoFocus type="text" value={q} onChange={e => setQ(e.target.value)}
                placeholder="Ara... BTC, ETH, SOL..."
                className="w-full bg-gray-800 border border-gray-700 text-cyan-300 text-xs rounded pl-6 pr-2 py-1.5 focus:border-cyan-600 outline-none" />
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {filtered.map(s => (
              <div key={s} onClick={() => { onChange(s); setOpen(false); setQ(''); }}
                className={`px-3 py-1.5 text-xs cursor-pointer hover:bg-gray-800 ${
                  s === value ? 'text-cyan-400 font-bold bg-cyan-950' : 'text-gray-300'
                }`}>
                <span className="text-white">{s.replace('USDT','')}</span>
                <span className="text-gray-600">/USDT</span>
              </div>
            ))}
            {filtered.length === 0 && <div className="px-3 py-4 text-xs text-gray-600 text-center">Sonuç yok</div>}
          </div>
          <div className="px-3 py-1.5 border-t border-gray-800 text-[10px] text-gray-600">{symbols.length} parite</div>
        </div>
      )}
    </div>
  );
}

// ── Order Book ────────────────────────────────────────────────────────────────
function OrderBook({ symbol }) {
  const [book, setBook] = useState({ bids: [], asks: [] });
  useEffect(() => {
    const load = () =>
      fetch(`${API_URL}/api/binance/orderbook?symbol=${symbol}&limit=15`)
        .then(r => r.json()).then(setBook).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [symbol]);

  const maxQ = Math.max(
    ...[...book.bids, ...book.asks].map(x => x.qty), 1
  );

  return (
    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
      <div>
        <div className="flex justify-between text-gray-500 mb-1 text-[10px]">
          <span>BİD (Alış)</span><span>MİKTAR</span>
        </div>
        {book.bids.map((b, i) => (
          <div key={i} className="relative flex justify-between py-0.5">
            <div className="absolute inset-0 right-auto bg-green-950 opacity-50 rounded"
              style={{ width: `${(b.qty / maxQ) * 100}%` }} />
            <span className="relative text-green-400">{fmt(b.price, 2)}</span>
            <span className="relative text-gray-400">{fmt(b.qty, 3)}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="flex justify-between text-gray-500 mb-1 text-[10px]">
          <span>ASK (Satış)</span><span>MİKTAR</span>
        </div>
        {book.asks.map((a, i) => (
          <div key={i} className="relative flex justify-between py-0.5">
            <div className="absolute inset-0 right-auto bg-red-950 opacity-50 rounded"
              style={{ width: `${(a.qty / maxQ) * 100}%` }} />
            <span className="relative text-red-400">{fmt(a.price, 2)}</span>
            <span className="relative text-gray-400">{fmt(a.qty, 3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TF Heatmap ────────────────────────────────────────────────────────────────
function TfHeatmap({ tfStatuses = [] }) {
  if (!tfStatuses.length) return null;
  const order = ['1w','1d','4h','1h','15m'];
  const sorted = [...tfStatuses].sort((a, b) => order.indexOf(a.timeframe) - order.indexOf(b.timeframe));
  return (
    <div className="flex gap-1 flex-wrap mt-1">
      {sorted.map(s => (
        <span key={s.timeframe}
          className={`text-[10px] px-1.5 py-0.5 rounded font-bold border ${s.is_green ? 'bg-green-950 border-green-700 text-green-400' : 'bg-red-950 border-red-800 text-red-400'} ${s.just_crossed ? 'ring-1 ring-yellow-400' : ''}`}>
          {s.is_green ? '●' : '○'} {s.timeframe}{s.weight > 0 ? ` [${s.weight}p]` : ' [tetik]'}{s.just_crossed ? ' ←' : ''}
        </span>
      ))}
    </div>
  );
}

// ── Sinyal Kartı ──────────────────────────────────────────────────────────────
function SignalCard({ sig }) {
  const [base, quote] = splitSym(sig.symbol);
  const sl  = sig.price * (1 - sig.stop_loss_pct  / 100);
  const tp  = sig.price * (1 + sig.take_profit_pct / 100);
  const rr  = sig.stop_loss_pct > 0 ? (sig.take_profit_pct / sig.stop_loss_pct).toFixed(1) : '—';
  const statusColor = { PENDING:'yellow', EXECUTED:'green', SKIPPED:'gray', EXPIRED:'red' }[sig.status] || 'gray';
  const ts = sig.timestamp ? new Date(sig.timestamp).toLocaleString('tr-TR',{dateStyle:'short',timeStyle:'short'}) : '—';
  return (
    <div className="bg-gray-900 border border-cyan-900 rounded-lg p-3 text-xs space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-base font-bold text-white">🔥 {base}/<span className="text-cyan-400">{quote}</span></div>
          <div className="text-[10px] text-gray-500 mt-0.5">{ts}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge label={sig.status} color={statusColor} />
          <span className="text-yellow-300 text-sm">{sig.stars || '⭐'}</span>
          <span className="text-[10px] text-gray-400">{sig.star_label || sig.matched_pattern || '—'}</span>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-1 text-center">
        <div className="bg-gray-800 rounded p-1.5">
          <div className="text-gray-500 text-[9px]">Giriş</div>
          <div className="text-white font-bold">{fmt(sig.price)}</div>
        </div>
        <div className="bg-red-950 border border-red-900 rounded p-1.5">
          <div className="text-red-400 text-[9px]">Stop-Loss</div>
          <div className="text-red-300 font-bold">{fmt(sl)}</div>
          <div className="text-red-500 text-[9px]">-{fmt(sig.stop_loss_pct,1)}%</div>
        </div>
        <div className="bg-green-950 border border-green-900 rounded p-1.5">
          <div className="text-green-400 text-[9px]">Hedef</div>
          <div className="text-green-300 font-bold">{fmt(tp)}</div>
          <div className="text-green-500 text-[9px]">+{fmt(sig.take_profit_pct,1)}%</div>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-gray-500">OCC:</span>
          <span className="text-cyan-300 font-bold">{sig.total_score}/{sig.max_score}p</span>
          <div className="h-1.5 w-16 bg-gray-800 rounded-full overflow-hidden ml-1">
            <div className="h-full bg-cyan-500 rounded-full" style={{width:`${Math.round((sig.total_score/sig.max_score)*100)}%`}} />
          </div>
        </div>
        <span className="text-gray-400">R:R <span className="text-white font-bold">1:{rr}</span></span>
      </div>
      <TfHeatmap tfStatuses={sig.tf_statuses} />
      <div className="flex gap-3 text-[10px] text-gray-400 border-t border-gray-800 pt-1.5">
        <span>RSI <span className={`font-bold ${sig.rsi_quality==='ideal'?'text-green-400':sig.rsi_quality==='caution'?'text-yellow-400':'text-cyan-300'}`}>{fmt(sig.rsi_value,1)}</span></span>
        <span>ADX <span className={`font-bold ${sig.adx_regime==='trending'?'text-green-400':sig.adx_regime==='ranging'?'text-yellow-400':'text-gray-400'}`}>{fmt(sig.adx_value,1)}</span></span>
        <span className="ml-auto">Poz <span className="text-purple-300 font-bold">{fmt(sig.position_size_pct,0)}%</span></span>
      </div>
    </div>
  );
}

// ── PnL Sparkline ─────────────────────────────────────────────────────────────
function PnlSparkline({ items }) {
  if (!items?.length) return null;
  const data = items.slice(-30).map((x, i) => ({ i, v: parseFloat(x.income) }));
  const cumul = [];
  let sum = 0;
  data.forEach(d => { sum += d.v; cumul.push({ i: d.i, v: parseFloat(sum.toFixed(4)) }); });
  const last = cumul[cumul.length - 1]?.v ?? 0;
  return (
    <div className="h-16">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={cumul}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={last >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0.3} />
              <stop offset="95%" stopColor={last >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0}   />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <ReTooltip formatter={v => [v + ' USDT', 'Kümülatif PnL']} contentStyle={{ background:'#111827', border:'1px solid #1e3a5f', fontSize:11 }} />
          <Area type="monotone" dataKey="v" stroke={last >= 0 ? '#22c55e' : '#ef4444'} fill="url(#pnlGrad)" strokeWidth={1.5} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ============================================================================
// ANA UYGULAMA
// ============================================================================
export default function App() {
  // ─ state ─────────────────────────────────────────────────────────────────
  const [logs,           setLogs]           = useState([]);
  const [connected,      setConnected]      = useState(false);
  const [activeTab,      setActiveTab]      = useState('overview');   // overview | chart | scanner | log
  const [chartSymbol,    setChartSymbol]    = useState('BTCUSDT');
  const [chartInterval,  setChartInterval]  = useState('15m');

  // Binance verisi
  const [balance,        setBalance]        = useState(null);
  const [binPositions,   setBinPositions]   = useState([]);
  const [openOrders,     setOpenOrders]     = useState([]);
  const [income,         setIncome]         = useState({ items: [], totalPnl: 0 });
  const [ticker,         setTicker]         = useState(null);

  // MongoDB verisi
  const [recentSignals,  setRecentSignals]  = useState([]);
  const [dbPositions,    setDbPositions]    = useState([]);
  const [history,        setHistory]        = useState([]);
  const [stats,          setStats]          = useState({ totalSignals:0, pendingSignals:0, executedSignals:0, openPositions:0, closedPositions:0 });

  // Piyasa sekmesi
  const [allTickers,     setAllTickers]     = useState([]);
  const [allSymbols,     setAllSymbols]     = useState(SYMBOLS);
  const [mkSearch,       setMkSearch]       = useState('');
  const [mkFilter,       setMkFilter]       = useState('all');  // all | gainers | losers
  const [mkSort,         setMkSort]         = useState({ col: 'quoteVolume', dir: -1 });
  const [latency,        setLatency]        = useState(null);

  const logEndRef = useRef(null);
  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior:'smooth' }); }, [logs]);

  // ─ Veri çekme ────────────────────────────────────────────────────────────
  const fetchAll = useCallback(() => {
    // Binance
    fetch(`${API_URL}/api/binance/balance`)      .then(r=>r.json()).then(setBalance).catch(()=>{});
    fetch(`${API_URL}/api/binance/positions`)     .then(r=>r.json()).then(d=>Array.isArray(d)?setBinPositions(d):[]).catch(()=>{});
    fetch(`${API_URL}/api/binance/open-orders`)   .then(r=>r.json()).then(d=>Array.isArray(d)?setOpenOrders(d):[]).catch(()=>{});
    fetch(`${API_URL}/api/binance/income`)        .then(r=>r.json()).then(setIncome).catch(()=>{});
    fetch(`${API_URL}/api/binance/ticker?symbol=${chartSymbol}`).then(r=>r.json()).then(setTicker).catch(()=>{});
    // MongoDB
    fetch(`${API_URL}/api/signals/recent`)       .then(r=>r.json()).then(d=>Array.isArray(d)?setRecentSignals(d):[]).catch(()=>{});
    fetch(`${API_URL}/api/positions/open`)        .then(r=>r.json()).then(d=>Array.isArray(d)?setDbPositions(d):[]).catch(()=>{});
    fetch(`${API_URL}/api/positions/history`)     .then(r=>r.json()).then(d=>Array.isArray(d)?setHistory(d):[]).catch(()=>{});
    fetch(`${API_URL}/api/stats`)                 .then(r=>r.json()).then(setStats).catch(()=>{});
  }, [chartSymbol]);

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, 5000);
    socket.on('connect',    () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));
    socket.on('log_init',   init => setLogs(init.split('\n').filter(Boolean)));
    socket.on('log_stream', chunk => setLogs(prev => [...prev, ...chunk.split('\n').filter(Boolean)].slice(-150)));
    return () => { clearInterval(t); ['connect','disconnect','log_init','log_stream'].forEach(e=>socket.off(e)); };
  }, [fetchAll]);

  // Tüm semboller — bir kez yükle
  useEffect(() => {
    fetch(`${API_URL}/api/binance/all-tickers`)
      .then(r => r.json())
      .then(d => Array.isArray(d) ? setAllSymbols(d.map(t => t.symbol)) : null)
      .catch(() => {});
  }, []);

  // Latency ölçümü — her 3 saniyede bir
  useEffect(() => {
    const measure = async () => {
      const t0 = Date.now();
      try {
        await fetch(`${API_URL}/api/health`);
        setLatency(Date.now() - t0);
      } catch { setLatency(null); }
    };
    measure();
    const t = setInterval(measure, 3000);
    return () => clearInterval(t);
  }, []);

  // Piyasa sekmesi polling — sadece market tabı aktifken
  useEffect(() => {
    if (activeTab !== 'market') return;
    const load = () =>
      fetch(`${API_URL}/api/binance/all-tickers`)
        .then(r => r.json())
        .then(d => Array.isArray(d) ? setAllTickers(d) : null)
        .catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [activeTab]);

  const logColor = l => {
    if (l.includes('ALIM') || l.includes('✅') || l.includes('💾')) return 'text-green-400';
    if (l.includes('ERROR') || l.includes('❌')) return 'text-red-400';
    if (l.includes('WARNING') || l.includes('⚠')) return 'text-yellow-400';
    if (l.includes('INFO')) return 'text-cyan-300';
    return 'text-gray-400';
  };

  // ─ Hesaplanan değerler ────────────────────────────────────────────────────
  const pnlColor = v => v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-gray-400';

  // ─ Piyasa yardımcıları ────────────────────────────────────────────────────
  const mkSortFn = (col) => {
    setMkSort(prev => ({ col, dir: prev.col === col ? -prev.dir : -1 }));
  };
  const mkFiltered = allTickers
    .filter(t => {
      if (mkSearch) return t.symbol.toLowerCase().includes(mkSearch.toLowerCase());
      if (mkFilter === 'gainers') return t.priceChangePct > 0;
      if (mkFilter === 'losers')  return t.priceChangePct < 0;
      return true;
    })
    .sort((a, b) => mkSort.dir * (b[mkSort.col] - a[mkSort.col]));
  const gainersCount = allTickers.filter(t => t.priceChangePct > 0).length;
  const losersCount  = allTickers.filter(t => t.priceChangePct < 0).length;

  // ─ Sekmeler ──────────────────────────────────────────────────────────────
  const TABS = [
    { id:'overview', label:'Genel Bakış',    icon: Activity  },
    { id:'market',   label:'Piyasa',         icon: Globe     },
    { id:'chart',    label:'Chart & Emir',   icon: BarChart2 },
    { id:'scanner',  label:'Sinyal Kartları',icon: Zap       },
    { id:'log',      label:'Canlı Log',      icon: Terminal  },
  ];

  return (
    <div className="min-h-screen bg-gray-950 text-cyan-300 font-mono p-3 space-y-3">

      {/* ── HEADER ── */}
      <header className="flex items-center justify-between border border-cyan-800 rounded-lg px-4 py-2.5 bg-gray-900">
        <div className="flex items-center gap-3">
          <TrendingUp size={18} className="text-cyan-400" />
          <div>
            <div className="text-xs font-bold tracking-widest text-cyan-300 uppercase">JARVIS // Binance Futures Monitor</div>
            <div className="text-[10px] text-gray-500">USDT-M Perpetual · fapi.binance.com</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {ticker && (
            <div className="text-xs text-right">
              <div className="text-white font-bold">{chartSymbol} <span className="text-cyan-400">{fmt(parseFloat(ticker.lastPrice),2)}</span></div>
              <div className={`text-[10px] ${parseFloat(ticker.priceChangePercent)>=0?'text-green-400':'text-red-400'}`}>{fmtPct(ticker.priceChangePercent)} 24s</div>
            </div>
          )}
          <button onClick={fetchAll} className="p-1.5 border border-cyan-900 rounded hover:border-cyan-600 transition-colors">
            <RefreshCw size={13} className="text-cyan-500" />
          </button>
          <div className={`flex items-center gap-1 text-[11px] px-2.5 py-1 rounded border font-mono ${
            latency === null ? 'border-gray-700 text-gray-500'
            : latency < 80  ? 'border-green-800 text-green-400'
            : latency < 200 ? 'border-yellow-700 text-yellow-400'
            : 'border-red-800 text-red-400'
          }`}>
            <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${
              latency === null ? 'bg-gray-600'
              : latency < 80  ? 'bg-green-400 animate-pulse'
              : latency < 200 ? 'bg-yellow-400 animate-pulse'
              : 'bg-red-400 animate-pulse'
            }`}/>
            {latency !== null ? `${latency}ms` : '—ms'}
          </div>
          <div className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded border ${connected?'border-green-700 text-green-400':'border-red-800 text-red-400'}`}>
            {connected ? <Wifi size={11}/> : <WifiOff size={11}/>}
            {connected ? 'ONLINE' : 'OFFLINE'}
          </div>
        </div>
      </header>

      {/* ── SEKME NAVİGASYONU ── */}
      <div className="flex gap-1 border-b border-cyan-900 pb-0">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-bold rounded-t transition-colors ${activeTab===t.id ? 'bg-gray-900 border border-cyan-800 border-b-gray-900 text-cyan-300' : 'text-gray-500 hover:text-cyan-400'}`}>
            <t.icon size={12} />{t.label}
          </button>
        ))}
      </div>

      {/* ════════════════ GENEL BAKIŞ SEKMESİ ════════════════ */}
      {activeTab === 'overview' && (
        <div className="space-y-3">

          {/* Bakiye Kartları */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <StatCard icon={DollarSign} label="Cüzdan Bakiyesi"    value={balance ? fmt(balance.walletBalance,2)+' $'    : '…'} color="text-cyan-400" />
            <StatCard icon={DollarSign} label="Kullanılabilir"      value={balance ? fmt(balance.availableBalance,2)+' $' : '…'} color="text-green-400" />
            <StatCard icon={TrendingUp} label="Gerçekleşmemiş PnL"  value={balance ? fmt(balance.unrealizedPnl,2)+' $'    : '…'} color={balance ? pnlColor(balance.unrealizedPnl) : 'text-gray-400'} />
            <StatCard icon={Activity}   label="7G Gerçekleşen PnL"  value={fmt(income.totalPnl,2)+' $'} color={pnlColor(income.totalPnl)} />
            <StatCard icon={Briefcase}  label="Açık Pozisyon"       value={binPositions.length} color="text-purple-400" />
          </div>

          {/* PnL Grafiği */}
          {income.items?.length > 0 && (
            <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
              <SectionHeader icon={TrendingUp} title="7 Günlük Kümülatif PnL (USDT)" />
              <PnlSparkline items={income.items} />
            </div>
          )}

          {/* Binance Açık Pozisyonlar */}
          <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
            <SectionHeader icon={Briefcase} title={`Binance Futures Açık Pozisyonlar (${binPositions.length})`} />
            {binPositions.length === 0
              ? <p className="text-xs text-gray-600 text-center py-4">Açık pozisyon yok.</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-gray-500 border-b border-gray-800 text-[10px]">
                      <th className="text-left py-1.5 pr-3">PARİTE</th>
                      <th className="text-right pr-3">YÖN</th>
                      <th className="text-right pr-3">MİKTAR</th>
                      <th className="text-right pr-3">GİRİŞ</th>
                      <th className="text-right pr-3">MARK</th>
                      <th className="text-right pr-3">LİK. FİYAT</th>
                      <th className="text-right pr-3">MARGIN</th>
                      <th className="text-right">UNREALIZED PNL</th>
                    </tr></thead>
                    <tbody>
                      {binPositions.map((p, i) => {
                        const qty  = parseFloat(p.positionAmt);
                        const upnl = parseFloat(p.unRealizedProfit);
                        const side = qty > 0 ? 'LONG' : 'SHORT';
                        return (
                          <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                            <td className="py-1.5 pr-3 text-white font-bold">{p.symbol}</td>
                            <td className="text-right pr-3"><Badge label={side} color={side==='LONG'?'green':'red'} /></td>
                            <td className="text-right pr-3 text-cyan-300">{Math.abs(qty)}</td>
                            <td className="text-right pr-3">{fmt(parseFloat(p.entryPrice),4)}</td>
                            <td className="text-right pr-3">{fmt(parseFloat(p.markPrice),4)}</td>
                            <td className="text-right pr-3 text-red-400">{fmt(parseFloat(p.liquidationPrice),4)}</td>
                            <td className="text-right pr-3">{fmt(parseFloat(p.isolatedMargin||p.positionInitialMargin),2)}</td>
                            <td className={`text-right font-bold ${pnlColor(upnl)}`}>{fmt(upnl,4)} $</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
          </div>

          {/* Açık Emirler */}
          <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
            <SectionHeader icon={BookOpen} title={`Açık Emirler (${openOrders.length})`} />
            {openOrders.length === 0
              ? <p className="text-xs text-gray-600 text-center py-4">Açık emir yok.</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-gray-500 border-b border-gray-800 text-[10px]">
                      <th className="text-left py-1.5 pr-3">PARİTE</th>
                      <th className="text-right pr-3">YÖN</th>
                      <th className="text-right pr-3">TÜR</th>
                      <th className="text-right pr-3">MİKTAR</th>
                      <th className="text-right pr-3">FİYAT</th>
                      <th className="text-right">DURUM</th>
                    </tr></thead>
                    <tbody>
                      {openOrders.map((o, i) => (
                        <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                          <td className="py-1.5 pr-3 text-white font-bold">{o.symbol}</td>
                          <td className="text-right pr-3"><Badge label={o.side} color={o.side==='BUY'?'green':'red'} /></td>
                          <td className="text-right pr-3 text-gray-400">{o.type}</td>
                          <td className="text-right pr-3 text-cyan-300">{o.origQty}</td>
                          <td className="text-right pr-3">{parseFloat(o.price) || 'MARKET'}</td>
                          <td className="text-right"><Badge label={o.status} color="yellow" /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </div>

          {/* MongoDB İşlem Geçmişi */}
          <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
            <SectionHeader icon={History} title="Bot İşlem Geçmişi (Kapalı)" />
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-gray-500 border-b border-gray-800 text-[10px]">
                  <th className="text-left py-1.5 pr-3">PARİTE</th>
                  <th className="text-right pr-3">GİRİŞ</th>
                  <th className="text-right pr-3">ÇIKIŞ</th>
                  <th className="text-right pr-3">SEBEP</th>
                  <th className="text-right">PNL</th>
                </tr></thead>
                <tbody>
                  {history.length === 0
                    ? <tr><td colSpan={5} className="text-center text-gray-600 py-4">Kapalı işlem yok.</td></tr>
                    : history.map((h,i) => (
                      <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                        <td className="py-1.5 pr-3 text-cyan-300 font-bold">{h.symbol}</td>
                        <td className="text-right pr-3">{fmt(h.entry_price,4)}</td>
                        <td className="text-right pr-3">{fmt(h.exit_price,4)}</td>
                        <td className="text-right pr-3 text-gray-400">{h.close_reason}</td>
                        <td className={`text-right font-bold ${pnlColor(h.final_pnl_pct)}`}>
                          {h.final_pnl_pct != null ? fmtPct(h.final_pnl_pct) : '—'}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Scanner İstatistikleri */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <StatCard icon={Zap}       label="Toplam Sinyal"  value={stats.totalSignals}    />
            <StatCard icon={Activity}  label="Bekleyen"       value={stats.pendingSignals}  color="text-yellow-400" />
            <StatCard icon={Activity}  label="İşleme Alınan"  value={stats.executedSignals} color="text-green-400"  />
            <StatCard icon={Briefcase} label="Bot Açık Poz."  value={stats.openPositions}   color="text-purple-400" />
            <StatCard icon={History}   label="Bot Kapatılan"  value={stats.closedPositions} color="text-gray-400"   />
          </div>
        </div>
      )}

      {/* ════════════════ CHART & EMİR DEFTERİ SEKMESİ ════════════════ */}
      {activeTab === 'chart' && (
        <div className="flex flex-col gap-2" style={{ height: 'calc(100vh - 130px)' }}>

          {/* Toolbar */}
          <div className="flex gap-2 flex-wrap items-center bg-gray-900 border border-cyan-900 rounded-lg px-3 py-2">
            <SymbolSearch symbols={allSymbols} value={chartSymbol} onChange={s => setChartSymbol(s)} />
            <div className="flex gap-1">
              {INTERVALS.map(iv => (
                <button key={iv} onClick={() => setChartInterval(iv)}
                  className={`px-2.5 py-1 text-[11px] rounded border transition-colors ${
                    chartInterval===iv ? 'bg-cyan-900 border-cyan-600 text-cyan-200 font-bold' : 'border-gray-700 text-gray-500 hover:border-cyan-800'
                  }`}>
                  {iv}
                </button>
              ))}
            </div>
            {ticker && (
              <div className="ml-auto flex items-center gap-4 text-xs">
                <span className="text-gray-500">Son: <span className="text-white font-bold text-sm">{fmt(parseFloat(ticker.lastPrice),4)}</span></span>
                <span className="text-gray-500">24s: <span className={parseFloat(ticker.priceChangePercent)>=0?'text-green-400 font-bold':'text-red-400 font-bold'}>{fmtPct(ticker.priceChangePercent)}</span></span>
                <span className="text-gray-500">Y: <span className="text-green-400">{fmt(parseFloat(ticker.highPrice),4)}</span></span>
                <span className="text-gray-500">D: <span className="text-red-400">{fmt(parseFloat(ticker.lowPrice),4)}</span></span>
                <span className="text-gray-500">Hacim: <span className="text-cyan-300">{fmt(parseFloat(ticker.quoteVolume)/1e6,1)}M</span></span>
              </div>
            )}
          </div>

          {/* Chart + Order Book */}
          <div className="flex gap-2 flex-1 min-h-0">
            {/* TradingView Chart */}
            <div className="flex-1 min-w-0 bg-gray-950 border border-cyan-900 rounded-lg overflow-hidden">
              <TradingViewChart symbol={chartSymbol} interval={chartInterval} />
            </div>

            {/* Order Book — sağ panel */}
            <div className="w-64 shrink-0 bg-gray-900 border border-cyan-900 rounded-lg p-3 overflow-y-auto">
              <SectionHeader icon={BookOpen} title={`Order Book`} />
              <OrderBook symbol={chartSymbol} />
            </div>
          </div>
        </div>
      )}

      {/* ════════════════ PİYASA SEKMESİ ════════════════ */}
      {activeTab === 'market' && (
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4 space-y-3">

          {/* Özet istatistikler */}
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Toplam Parite</div>
              <div className="text-xl font-bold text-cyan-300">{allTickers.length}</div>
              <div className="text-[10px] text-gray-500">USDT-M Perpetual</div>
            </div>
            <div className="bg-green-950 border border-green-900 rounded-lg p-3 text-center">
              <div className="text-[10px] text-green-600 uppercase tracking-widest mb-1">Yükselen</div>
              <div className="text-xl font-bold text-green-400">{gainersCount}</div>
              <div className="text-[10px] text-green-700">{allTickers.length ? Math.round(gainersCount/allTickers.length*100) : 0}% coin</div>
            </div>
            <div className="bg-red-950 border border-red-900 rounded-lg p-3 text-center">
              <div className="text-[10px] text-red-700 uppercase tracking-widest mb-1">Düşen</div>
              <div className="text-xl font-bold text-red-400">{losersCount}</div>
              <div className="text-[10px] text-red-800">{allTickers.length ? Math.round(losersCount/allTickers.length*100) : 0}% coin</div>
            </div>
          </div>

          {/* Arama + Filtre */}
          <div className="flex gap-2 flex-wrap items-center">
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-2 text-gray-500" />
              <input
                type="text"
                placeholder="BTC, ETH, SOL..."
                value={mkSearch}
                onChange={e => { setMkSearch(e.target.value); setMkFilter('all'); }}
                className="bg-gray-800 border border-gray-700 text-cyan-300 text-xs rounded pl-7 pr-3 py-1.5 w-44 focus:border-cyan-600 outline-none"
              />
            </div>
            {['all','gainers','losers'].map(f => (
              <button key={f} onClick={() => { setMkFilter(f); setMkSearch(''); }}
                className={`px-3 py-1.5 text-[11px] rounded border font-bold transition-colors ${
                  mkFilter===f && !mkSearch
                    ? f==='gainers' ? 'bg-green-950 border-green-700 text-green-400'
                      : f==='losers' ? 'bg-red-950 border-red-800 text-red-400'
                      : 'bg-cyan-950 border-cyan-700 text-cyan-300'
                    : 'border-gray-700 text-gray-500 hover:border-gray-600'
                }`}>
                {f==='all' ? 'Tümü' : f==='gainers' ? '▲ Yükselen' : '▼ Düşen'}
              </button>
            ))}
            <span className="ml-auto text-[10px] text-gray-600">{mkFiltered.length} sonuç · 3s güncelleme</span>
          </div>

          {/* Tablo */}
          {allTickers.length === 0
            ? <p className="text-xs text-gray-600 text-center py-10">Veriler yükleniyor…</p>
            : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-800 text-[10px] sticky top-0 bg-gray-900">
                      <th className="text-left py-2 pr-2 w-6">#</th>
                      <th className="text-left pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('symbol')}>
                        PARİTE {mkSort.col==='symbol' ? (mkSort.dir===1 ? <ArrowUp size={9} className="inline"/> : <ArrowDown size={9} className="inline"/>) : null}
                      </th>
                      <th className="text-right pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('lastPrice')}>
                        FİYAT {mkSort.col==='lastPrice' ? (mkSort.dir===1 ? <ArrowUp size={9} className="inline"/> : <ArrowDown size={9} className="inline"/>) : null}
                      </th>
                      <th className="text-right pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('priceChangePct')}>
                        24s % {mkSort.col==='priceChangePct' ? (mkSort.dir===1 ? <ArrowUp size={9} className="inline"/> : <ArrowDown size={9} className="inline"/>) : null}
                      </th>
                      <th className="text-right pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('highPrice')}>
                        24s YÜKSEK
                      </th>
                      <th className="text-right pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('lowPrice')}>
                        24s DÜŞÜK
                      </th>
                      <th className="text-right pr-3 cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('quoteVolume')}>
                        HACİM (M$) {mkSort.col==='quoteVolume' ? (mkSort.dir===1 ? <ArrowUp size={9} className="inline"/> : <ArrowDown size={9} className="inline"/>) : null}
                      </th>
                      <th className="text-right cursor-pointer hover:text-cyan-400 select-none" onClick={() => mkSortFn('count')}>
                        İŞLEM
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {mkFiltered.slice(0, 300).map((t, i) => {
                      const isPos = t.priceChangePct >= 0;
                      const priceDec = t.lastPrice >= 1000 ? 2 : t.lastPrice >= 1 ? 4 : 6;
                      return (
                        <tr key={t.symbol}
                          className="border-b border-gray-800 hover:bg-gray-800 cursor-pointer"
                          onClick={() => { setChartSymbol(t.symbol); setActiveTab('chart'); }}>
                          <td className="py-1.5 pr-2 text-gray-600">{i+1}</td>
                          <td className="pr-3 font-bold text-white">
                            {t.symbol.replace('USDT','')}
                            <span className="text-gray-600 font-normal">/USDT</span>
                          </td>
                          <td className="text-right pr-3 font-mono text-cyan-200">{t.lastPrice.toFixed(priceDec)}</td>
                          <td className={`text-right pr-3 font-bold ${isPos ? 'text-green-400' : 'text-red-400'}`}>
                            <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${isPos ? 'bg-green-950' : 'bg-red-950'}`}>
                              {isPos ? '+' : ''}{t.priceChangePct.toFixed(2)}%
                            </span>
                          </td>
                          <td className="text-right pr-3 text-green-600 font-mono">{t.highPrice.toFixed(priceDec)}</td>
                          <td className="text-right pr-3 text-red-700 font-mono">{t.lowPrice.toFixed(priceDec)}</td>
                          <td className="text-right pr-3 text-yellow-500">{(t.quoteVolume/1e6).toFixed(1)}M</td>
                          <td className="text-right text-gray-500">{t.count >= 1000 ? (t.count/1000).toFixed(0)+'K' : t.count}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
        </div>
      )}

      {/* ════════════════ SİNYAL KARTLARI SEKMESİ ════════════════ */}
      {activeTab === 'scanner' && (
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
          <SectionHeader icon={Zap} title={`Son Alım Sinyalleri (${recentSignals.length})`} />
          {recentSignals.length === 0
            ? <p className="text-xs text-gray-600 text-center py-10">Henüz sinyal üretilmedi. Scanner tarıyor…</p>
            : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {recentSignals.map((sig, i) => <SignalCard key={i} sig={sig} />)}
              </div>
            )}
        </div>
      )}

      {/* ════════════════ CANLI LOG SEKMESİ ════════════════ */}
      {activeTab === 'log' && (
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
          <SectionHeader icon={Terminal} title="Jarvis Live Core Log Stream" />
          <div className="h-[70vh] overflow-y-auto text-xs leading-5 space-y-0.5 pr-1 font-mono">
            {logs.length === 0
              ? <span className="text-gray-600">Log bekleniyor…</span>
              : logs.map((line, i) => (
                  <div key={i} className={`whitespace-pre-wrap break-all ${logColor(line)}`}>{line}</div>
                ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

    </div>
  );
}
