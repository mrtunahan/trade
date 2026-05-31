// ============================================================================
// src/App.jsx - Jarvis Trading Dashboard v2 — Binance Futures Full Monitor
// ============================================================================
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { io } from 'socket.io-client';
import { AreaChart, Area, ResponsiveContainer, Tooltip as ReTooltip, XAxis } from 'recharts';
import {
  Terminal, Activity, Briefcase, History, TrendingUp, Wifi, WifiOff,
  Zap, DollarSign, BarChart2, BookOpen, RefreshCw, ChevronDown,
  Globe, Search, ArrowUp, ArrowDown, Volume2, VolumeX, AlertTriangle,
  Play, ArrowRightLeft, Shield, Sliders, Info, Percent, Eye, Wallet, Coins
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
function playFuturisticChime() {
  try {
    const isMuted = localStorage.getItem('jarvis_sound_muted') === 'true';
    if (isMuted) return;
    const volSetting = parseFloat(localStorage.getItem('jarvis_sound_volume') ?? '80');
    const volumeMultiplier = volSetting / 100;

    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const playTone = (freq, startTime, duration, vol) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(vol * volumeMultiplier, startTime + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + duration);
    };
    const now = ctx.currentTime;
    playTone(523.25, now, 0.4, 0.08);
    playTone(659.25, now + 0.08, 0.4, 0.08);
    playTone(783.99, now + 0.16, 0.4, 0.08);
    playTone(1046.50, now + 0.24, 0.8, 0.12);
  } catch (e) {
    console.log('Audio error:', e);
  }
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
  const widgetRef = useRef(null);

  // Sembol veya interval değiştiğinde
  useEffect(() => {
    const tvSymbol   = `BINANCE:${symbol}`;
    const tvInterval = TV_INTERVAL_MAP[interval] || '15';

    if (widgetRef.current) {
      // Eğer widget zaten varsa, yok etmeden sadece sembol/interval güncelle!
      try {
        if (typeof widgetRef.current.setSymbol === 'function') {
          widgetRef.current.setSymbol(tvSymbol, tvInterval);
          return;
        }
      } catch (err) {
        console.error("TradingView setSymbol error:", err);
      }
    }

    // Widget yoksa veya hata oluştuysa sıfırdan oluştur
    const el = containerRef.current;
    if (!el) return;
    el.innerHTML = '';

    const init = () => {
      if (!window.TradingView) return;
      try {
        widgetRef.current = new window.TradingView.widget({
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
      } catch (e) {
        console.error("TradingView widget init error:", e);
      }
    };

    // Flexbox ve yükseklik yerleşimi için 200ms gecikme (Göstergeler popup scroll/kesilme hatasını önler)
    const timer = setTimeout(() => {
      if (window.TradingView) {
        init();
      } else {
        const script = document.createElement('script');
        script.src   = 'https://s3.tradingview.com/tv.js';
        script.async = true;
        script.onload = init;
        document.head.appendChild(script);
      }
    }, 200);

    return () => {
      clearTimeout(timer);
    };
  }, [symbol, interval]);

  // Tab değişimi / unmount durumunda widget'ı temizle
  useEffect(() => {
    return () => {
      widgetRef.current = null;
      const el = containerRef.current;
      if (el) el.innerHTML = '';
    };
  }, []);

  return <div id="tv_chart_main" ref={containerRef} style={{ width:'100%', height:'100%' }} />;
}

// ── Symbol Search Dropdown ────────────────────────────────────────────────────
function SymbolSearch({ symbols, value, onChange, quoteAsset = 'USDT' }) {
  const [open, setOpen] = useState(false);
  const [q,    setQ]    = useState('');
  const wrapRef = useRef(null);

  useEffect(() => {
    const h = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const base = value.endsWith(quoteAsset) ? value.slice(0, -quoteAsset.length) : value.replace('USDT','');
  const filtered = symbols
    .filter(s => s.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 100);

  return (
    <div ref={wrapRef} className="relative">
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 bg-gray-900 border border-cyan-800 text-cyan-200 text-xs font-bold rounded px-3 py-1.5 hover:border-cyan-500 transition-colors min-w-[140px]">
        <span>{base}<span className="text-gray-500 font-normal">/{quoteAsset}</span></span>
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
            {filtered.map(s => {
              const displayBase = s.endsWith(quoteAsset) ? s.slice(0, -quoteAsset.length) : s.replace('USDT','');
              return (
                <div key={s} onClick={() => { onChange(s); setOpen(false); setQ(''); }}
                  className={`px-3 py-1.5 text-xs cursor-pointer hover:bg-gray-800 ${
                    s === value ? 'text-cyan-400 font-bold bg-cyan-950' : 'text-gray-300'
                  }`}>
                  <span className="text-white">{displayBase}</span>
                  <span className="text-gray-600">/{quoteAsset}</span>
                </div>
              );
            })}
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
        .then(r => r.json())
        .then(d => {
          if (d && Array.isArray(d.bids) && Array.isArray(d.asks)) {
            setBook(d);
          }
        })
        .catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [symbol]);

  const bids = Array.isArray(book.bids) ? book.bids : [];
  const asks = Array.isArray(book.asks) ? book.asks : [];

  const maxQ = Math.max(
    ...[...bids, ...asks].map(x => x.qty || 0), 1
  );

  return (
    <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
      <div>
        <div className="flex justify-between text-gray-500 mb-1 text-[10px]">
          <span>BİD (Alış)</span><span>MİKTAR</span>
        </div>
        {bids.map((b, i) => (
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
        {asks.map((a, i) => (
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
    <div className="flex items-center gap-1.5 mt-1 border border-cyan-950/40 rounded p-1.5 bg-gray-950/40">
      <span className="text-[9px] text-gray-500 uppercase font-bold tracking-wider mr-1">OCC TF:</span>
      {sorted.map(s => {
        const title = `${s.timeframe} - ${s.is_green ? 'Yükseliş (Yeşil)' : 'Düşüş (Kırmızı)'} [${s.weight}p]${s.just_crossed ? ' (Yeni Geçiş!)' : ''}`;
        return (
          <div key={s.timeframe} 
            title={title}
            className={`relative w-7 h-7 flex flex-col items-center justify-center rounded text-[8px] font-bold select-none border transition-all ${
              s.is_green 
                ? 'bg-green-950 border-green-600 text-green-300 shadow-[inset_0_0_6px_rgba(34,197,94,0.15)]' 
                : 'bg-red-950 border-red-800 text-red-400 shadow-[inset_0_0_6px_rgba(239,68,68,0.15)]'
            } ${s.just_crossed ? 'animate-pulse ring-1 ring-yellow-400 border-yellow-400' : ''}`}
          >
            {s.just_crossed && (
              <span className="absolute -top-1 -right-1 w-2 h-2 bg-yellow-400 rounded-full shadow-[0_0_4px_#facc15] animate-ping" />
            )}
            <span>{s.timeframe}</span>
            <span className={`text-[7px] leading-none mt-0.5 ${s.is_green ? 'text-green-400' : 'text-red-500'}`}>
              {s.is_green ? '▲' : '▼'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Sinyal Kartı ──────────────────────────────────────────────────────────────
function SignalCard({ sig, onSelect, onExecute, onOpenDetails }) {
  const [base, quote] = splitSym(sig.symbol);
  const sl  = sig.price * (1 - sig.stop_loss_pct  / 100);
  const tp  = sig.price * (1 + sig.take_profit_pct / 100);
  const rr  = sig.stop_loss_pct > 0 ? (sig.take_profit_pct / sig.stop_loss_pct).toFixed(1) : '—';
  
  const statusColor = { PENDING:'yellow', EXECUTED:'green', SKIPPED:'gray', EXPIRED:'red' }[sig.status] || 'gray';
  const ts = sig.timestamp ? new Date(sig.timestamp).toLocaleString('tr-TR',{dateStyle:'short',timeStyle:'short'}) : '—';
  
  // Full Sniper (Tüm zaman dilimleri yeşil) tespiti ve özel ışıma efekti
  const isFullSniper = Array.isArray(sig.tf_statuses) && sig.tf_statuses.length > 0 && sig.tf_statuses.every(t => t.is_green);
  
  let cardClass = "border-cyan-950/60 bg-gray-900/80 hover:border-cyan-500/80 hover:shadow-[0_0_15px_rgba(6,182,212,0.15)]";
  let badgeStarsColor = "text-yellow-400";
  
  if (isFullSniper) {
    cardClass = "border-amber-500/80 bg-gray-900/90 shadow-[0_0_20px_rgba(245,158,11,0.2)] hover:border-amber-400 hover:shadow-[0_0_25px_rgba(245,158,11,0.3)] border-2";
    badgeStarsColor = "text-amber-300";
  } else if (sig.stars === "⭐⭐⭐") {
    cardClass = "border-emerald-500/80 bg-gray-900/80 shadow-[0_0_15px_rgba(16,185,129,0.15)] hover:border-emerald-400 hover:shadow-[0_0_20px_rgba(16,185,129,0.25)]";
  } else if (sig.stars === "⭐⭐") {
    cardClass = "border-cyan-500/80 bg-gray-900/80 shadow-[0_0_15px_rgba(6,182,212,0.1)] hover:border-cyan-400 hover:shadow-[0_0_20px_rgba(6,182,212,0.2)]";
  }

  // RSI status and colors
  const rsiColor = sig.rsi_quality === 'ideal' ? 'text-green-400' : sig.rsi_quality === 'caution' ? 'text-red-400' : 'text-yellow-400';
  const rsiDot = sig.rsi_quality === 'ideal' ? 'bg-green-500' : sig.rsi_quality === 'caution' ? 'bg-red-500' : 'bg-yellow-500';

  // ADX status and colors
  const adxColor = sig.adx_regime === 'trending' ? 'text-green-400' : sig.adx_regime === 'ranging' ? 'text-yellow-400' : 'text-gray-400';
  const adxDot = sig.adx_regime === 'trending' ? 'bg-green-500' : 'bg-yellow-500';

  return (
    <div 
      className={`relative backdrop-blur-md rounded-xl p-4.5 flex flex-col justify-between gap-3 transition-all duration-300 cursor-pointer border ${cardClass}`}
      onClick={() => onOpenDetails && onOpenDetails(sig)}
    >
      {/* Üst Kısım: Başlık, Status ve Yıldızlar */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="flex h-2.5 w-2.5 relative">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isFullSniper ? 'bg-amber-400' : 'bg-cyan-400'}`}></span>
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isFullSniper ? 'bg-amber-500' : 'bg-cyan-500'}`}></span>
            </span>
            <span className="text-base font-bold text-white tracking-wide">
              {base}<span className="text-cyan-400 font-semibold">/{quote}</span>
            </span>
          </div>
          <div className="text-[10px] text-gray-500 font-medium font-mono">{ts}</div>
        </div>

        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-1.5">
            <Badge label={sig.status} color={statusColor} />
            <span className={`text-xs font-bold font-mono tracking-wider ${badgeStarsColor}`}>
              {sig.stars || '⭐'}
            </span>
          </div>
          <span className="text-[9px] font-bold text-cyan-400 uppercase tracking-widest text-right mt-0.5">
            {sig.star_label || sig.matched_pattern || 'GİRİŞ FIRSATI'}
          </span>
        </div>
      </div>

      {/* Sinyal Kalitesi & Mum Formasyonu Özel Rozeti */}
      <div className="flex flex-wrap gap-1.5 items-center justify-between border-t border-cyan-950/40 pt-2 pb-1">
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-gray-400">Güven Puanı:</span>
          <span className="text-cyan-300 font-extrabold font-mono text-xs">{sig.total_score}/{sig.max_score}p</span>
          <div className="h-1.5 w-14 bg-gray-800/80 rounded-full overflow-hidden ml-1 border border-cyan-950/30">
            <div 
              className={`h-full rounded-full ${isFullSniper ? 'bg-amber-500' : 'bg-cyan-500'}`} 
              style={{width:`${Math.round((sig.total_score/sig.max_score)*100)}%`}} 
            />
          </div>
        </div>

        {/* Dynamic Pattern / Sniper Badge */}
        {sig.candlestick_pattern ? (
          <div className="bg-amber-955/40 border border-amber-800/60 rounded px-2 py-0.5 text-[9px] font-bold text-amber-400 flex items-center gap-1 shadow-sm">
            ✨ {sig.candlestick_pattern}
          </div>
        ) : isFullSniper ? (
          <div className="bg-amber-500 border border-amber-400 text-gray-950 rounded px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-widest flex items-center gap-0.5 shadow-sm shadow-amber-500/20">
            👑 FULL SNIPER
          </div>
        ) : null}
      </div>

      {/* Görsel Risk:Reward (R:R) İlerleme Cetveli */}
      <div className="space-y-1 bg-gray-950/40 border border-cyan-950/20 rounded-lg p-2">
        <div className="flex justify-between text-[9px] text-gray-400 font-semibold font-mono">
          <span className="text-red-400">SL (-{sig.stop_loss_pct.toFixed(1)}%)</span>
          <span className="text-cyan-400">R:R 1:{rr}</span>
          <span className="text-green-400">Hedef (+{sig.take_profit_pct.toFixed(1)}%)</span>
        </div>
        <div className="relative h-2 bg-gray-800 rounded-full border border-cyan-950/30 overflow-hidden flex">
          <div className="h-full bg-red-500/40 border-r border-red-500/70" style={{ width: '25%' }} />
          <div className="h-full bg-cyan-500/20" style={{ width: '35%' }} />
          <div className="h-full bg-green-500/40 border-l border-green-500/70" style={{ width: '40%' }} />
          {/* Giriş Noktası Göstergesi */}
          <div className="absolute top-0 bottom-0 bg-white w-0.5 shadow-[0_0_4px_#fff]" style={{ left: '25%' }} />
        </div>
      </div>

      {/* Sayısal Fiyat Değerleri Tablosu */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-cyan-950/20 border border-cyan-900/30 rounded-lg p-2 text-center hover:bg-cyan-950/30 transition-colors">
          <div className="text-cyan-400 text-[9px] font-semibold uppercase tracking-wider">GİRİŞ</div>
          <div className="text-white font-extrabold font-mono text-sm mt-0.5">{fmt(sig.price)}</div>
        </div>
        <div className="bg-red-950/20 border border-red-900/30 rounded-lg p-2 text-center hover:bg-red-950/30 transition-colors">
          <div className="text-red-400 text-[9px] font-semibold uppercase tracking-wider">STOP-LOSS</div>
          <div className="text-red-300 font-extrabold font-mono text-sm mt-0.5">{fmt(sl)}</div>
        </div>
        <div className="bg-green-950/20 border border-green-900/30 rounded-lg p-2 text-center hover:bg-green-950/30 transition-colors">
          <div className="text-green-400 text-[9px] font-semibold uppercase tracking-wider">HEDEF (TP)</div>
          <div className="text-green-300 font-extrabold font-mono text-sm mt-0.5">{fmt(tp)}</div>
        </div>
      </div>

      {/* Çoklu Zaman Dilimi OCC Isı Haritası */}
      <TfHeatmap tfStatuses={sig.tf_statuses} />

      {/* Alt Göstergeler & Hızlı Aksiyon */}
      <div className="flex gap-2.5 text-[10px] text-gray-400 border-t border-cyan-950/40 pt-2 items-center flex-wrap">
        <div className="flex items-center gap-1">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${rsiDot}`} />
          <span>RSI: <span className={`font-bold font-mono ${rsiColor}`}>{fmt(sig.rsi_value, 1)}</span></span>
        </div>
        <div className="flex items-center gap-1">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${adxDot}`} />
          <span>ADX: <span className={`font-bold font-mono ${adxColor}`}>{fmt(sig.adx_value, 1)}</span></span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-purple-500" />
          <span>Pay: <span className="text-purple-300 font-bold font-mono">{fmt(sig.position_size_pct, 0)}%</span></span>
        </div>

        {sig.status === 'PENDING' && (
          <button 
            onClick={(e) => {
              e.stopPropagation();
              if (confirm(`${sig.symbol} sinyalini hemen manuel işleme almak istediğinize emin misiniz?`)) {
                onExecute && onExecute(sig._id);
              }
            }}
            className="ml-auto bg-cyan-950 hover:bg-cyan-900 border border-cyan-500/80 text-cyan-300 hover:text-white px-2.5 py-1 rounded-md transition-all text-[9px] font-bold tracking-wide shadow-sm active:scale-95 animate-pulse"
          >
            🚀 Hemen İşle
          </button>
        )}
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
  const [chartSymbol,    setChartSymbol]    = useState('BTCTRY');
  const [chartInterval,  setChartInterval]  = useState('15m');
  
  // Premium Ses / Bildirim Ayarları State'leri
  const [soundMuted, setSoundMuted] = useState(() => localStorage.getItem('jarvis_sound_muted') === 'true');
  const [soundVolume, setSoundVolume] = useState(() => parseInt(localStorage.getItem('jarvis_sound_volume') ?? '80'));
  const [soundPanelOpen, setSoundPanelOpen] = useState(false);

  // Açık Pozisyon Koruma (SL/TP) Güncelleme State'leri
  const [editingProtectionPos, setEditingProtectionPos] = useState(null);
  const [tempSlPrice, setTempSlPrice] = useState('');
  const [tempTpPrice, setTempTpPrice] = useState('');

  // Detay Analiz Modalı İçin Seçili Sinyal
  const [selectedSignalForModal, setSelectedSignalForModal] = useState(null);
  
  // Emir Gönderim Terminali (Order Panel) State'leri
  const [orderSide, setOrderSide] = useState('LONG'); // LONG | SHORT
  const [orderType, setOrderType] = useState('MARKET'); // MARKET | LIMIT
  const [orderPrice, setOrderPrice] = useState('');
  const [orderQty, setOrderQty] = useState('');
  const [orderLeverage, setOrderLeverage] = useState(1);
  const [orderSlPct, setOrderSlPct] = useState('2.0');
  const [orderTpPct, setOrderTpPct] = useState('4.0');
  
  // Canlı Log Arama ve Seviye Filtreleme
  const [logSearch,      setLogSearch]      = useState('');
  const [logLevelFilter, setLogLevelFilter] = useState('ALL');

  // Binance verisi
  const [balance,        setBalance]        = useState(null);
  const [binPositions,   setBinPositions]   = useState([]);
  const [openOrders,     setOpenOrders]     = useState([]);
  const [income,         setIncome]         = useState({ items: [], totalPnl: 0 });
  const [ticker,         setTicker]         = useState(null);
  const [binanceApiError, setBinanceApiError] = useState(null);
  const [quoteAsset,     setQuoteAsset]     = useState('TRY');
  const [maxBudget,      setMaxBudget]      = useState(500);

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
  const prevSignalsLengthRef = useRef(0);

  // Ses ayar panelinin dışına tıklandığında kapanması için click-outside hook'u
  useEffect(() => {
    const clickOutside = (e) => {
      if (soundPanelOpen && !e.target.closest('.sound-panel-container')) {
        setSoundPanelOpen(false);
      }
    };
    document.addEventListener('mousedown', clickOutside);
    return () => document.removeEventListener('mousedown', clickOutside);
  }, [soundPanelOpen]);

  // Premium fütüristik stil enjeksiyonu (Glassmorphism & Neon Borders)
  useEffect(() => {
    const styleEl = document.createElement('style');
    styleEl.innerHTML = `
      .glass-panel {
        background: rgba(17, 24, 39, 0.75) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(6, 182, 212, 0.1) !important;
      }
      .glass-panel:hover {
        border-color: rgba(6, 182, 212, 0.25) !important;
        box-shadow: 0 0 15px rgba(6, 182, 212, 0.05) !important;
      }
    `;
    document.head.appendChild(styleEl);
    return () => {
      try { document.head.removeChild(styleEl); } catch(e) {}
    };
  }, []);

  // Yeni Sinyal Geldiğinde Sesli Uyarı Çal (Futuristic Synth Chime)
  useEffect(() => {
    if (recentSignals.length > prevSignalsLengthRef.current) {
      if (prevSignalsLengthRef.current > 0) {
        playFuturisticChime();
      }
      prevSignalsLengthRef.current = recentSignals.length;
    }
  }, [recentSignals]);

  // Sinyal Kartına Tıklandığında Grafiği Yükle ve Sekmeyi Değiştir
  const handleSelectSignal = (symbol) => {
    let sym = symbol;
    if (symbol.endsWith('TRY')) {
      sym = symbol.replace('TRY', 'USDT');
    }
    setChartSymbol(sym);
    setActiveTab('chart');
    playFuturisticChime();
  };

  // Bekleyen Sinyali Manuel Olarak Hemen İşleme Al (Force Execute)
  const handleForceExecute = (signalId) => {
    fetch(`${API_URL}/api/signals/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signalId })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        playFuturisticChime();
        alert('🎯 Sinyal başarıyla manuel tetiklendi, LONG pozisyon açıldı!');
        fetchAll();
      } else {
        alert('Hata: ' + (data.error || 'İşlem başarısız oldu.'));
      }
    })
    .catch(err => {
      alert('Bağlantı hatası: ' + err.message);
    });
  };

  // Açık Pozisyonu Arayüzden Tek Tıkla Borsada Kapat (Market Close)
  const handleClosePosition = (symbol, quantity, side) => {
    if (!confirm(`🚨 ${symbol} pozisyonunu piyasa fiyatından kapatmak istediğinize emin misiniz?`)) return;
    
    fetch(`${API_URL}/api/positions/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, quantity, side })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        playFuturisticChime();
        alert('✅ Pozisyon başarıyla kapatıldı!');
        fetchAll();
      } else {
        alert('Hata: ' + (data.error || 'Pozisyon kapatılamadı.'));
      }
    })
    .catch(err => {
      alert('Bağlantı hatası: ' + err.message);
    });
  };

  // Açık Pozisyon Yönünü Borsada Anında Market Emirle Tersine Çevir (Reverse)
  const handleReversePosition = (symbol, quantity, side) => {
    if (!confirm(`🚨 ${symbol} pozisyonunu piyasa fiyatından kapatıp, ters yönde (${side === 'LONG' ? 'SHORT' : 'LONG'}) aynı büyüklükte yeni işlem açmak istediğinize emin misiniz?`)) return;
    
    fetch(`${API_URL}/api/positions/reverse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, quantity, side })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        playFuturisticChime();
        alert(`🔄 Yön başarıyla tersine çevrildi!`);
        fetchAll();
      } else {
        alert('Hata: ' + (data.error || 'Pozisyon yönü çevrilemedi.'));
      }
    })
    .catch(err => {
      alert('Bağlantı hatası: ' + err.message);
    });
  };

  // Açık Pozisyon Koruma (SL/TP) Seviyelerini Veritabanında Güncelle
  const handleUpdateProtection = () => {
    if (!editingProtectionPos) return;
    
    fetch(`${API_URL}/api/positions/update-protection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        symbol: editingProtectionPos.symbol,
        stopLossPrice: tempSlPrice || null,
        takeProfitPrice: tempTpPrice || null
      })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        playFuturisticChime();
        alert('🛡️ Koruma (SL/TP) seviyeleri başarıyla güncellendi!');
        setEditingProtectionPos(null);
        fetchAll();
      } else {
        alert('Hata: ' + (data.error || 'Koruma güncellenemedi.'));
      }
    })
    .catch(err => {
      alert('Bağlantı hatası: ' + err.message);
    });
  };

  // Manuel Emir Gönder (Borsa Terminali Entegrasyonu)
  const handlePlaceManualOrder = () => {
    if (!orderQty || parseFloat(orderQty) <= 0) {
      alert('Lütfen geçerli bir miktar girin.');
      return;
    }
    if (orderType === 'LIMIT' && (!orderPrice || parseFloat(orderPrice) <= 0)) {
      alert('Limit emir için lütfen geçerli bir fiyat girin.');
      return;
    }

    const side = orderSide === 'LONG' ? 'BUY' : 'SELL';
    const positionSide = orderSide;

    const confirmMsg = `🚨 ${chartSymbol} paritesinde SPOT (1x) ile ${orderQty} miktarında ${orderType} ${orderSide === 'LONG' ? 'ALIM (BUY)' : 'SATIM (SELL)'} emri göndermek istediğinize emin misiniz?`;
    if (!confirm(confirmMsg)) return;

    fetch(`${API_URL}/api/orders/place`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: chartSymbol,
        side,
        positionSide,
        type: orderType,
        quantity: orderQty,
        price: orderType === 'LIMIT' ? orderPrice : undefined,
        leverage: orderLeverage,
        stopLossPct: orderSlPct || '0',
        takeProfitPct: orderTpPct || '0'
      })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        playFuturisticChime();
        alert('🎯 Manuel emir başarıyla borsaya iletildi!');
        setOrderQty('');
        if (orderType === 'LIMIT') setOrderPrice('');
        fetchAll();
      } else {
        alert('Hata: ' + (data.error || 'Emir gönderilemedi.'));
      }
    })
    .catch(err => {
      alert('Bağlantı hatası: ' + err.message);
    });
  };

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior:'smooth' }); }, [logs]);

  // ─ Veri çekme ────────────────────────────────────────────────────────────
  const fetchAll = useCallback(() => {
    // 1. Canlı Binance Verileri (Tek Birleşik Staggered İstek - 418 Önleyici)
    fetch(`${API_URL}/api/dashboard/all-data?symbol=${chartSymbol}`)
      .then(r => r.json())
      .then(d => {
        if (d) {
          setBalance(d.balance || null);
          if (d.balance && d.balance.quoteAsset) {
            setQuoteAsset(d.balance.quoteAsset);
          }
          if (d.balance && d.balance.maxBudget) {
            setMaxBudget(d.balance.maxBudget);
          }
          if (d.positions) setBinPositions(d.positions);
          if (d.openOrders) setOpenOrders(d.openOrders);
          if (d.income) setIncome(d.income);
          if (d.ticker) setTicker(d.ticker);
          setBinanceApiError(d.binanceApiError || null);
        }
      })
      .catch(err => console.error("Dashboard fetch error:", err));

    // 2. Lokal MongoDB Verileri (Hızlı & Limitsiz)
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

  // Performans İstatistikleri Hesaplama
  const totalClosed = history.length;
  const winningTrades = history.filter(h => h.final_pnl_pct > 0);
  const losingTrades = history.filter(h => h.final_pnl_pct <= 0);
  const winRate = totalClosed > 0 ? (winningTrades.length / totalClosed) * 100 : 0;
  
  const totalProfitPct = winningTrades.reduce((sum, h) => sum + (h.final_pnl_pct || 0), 0);
  const totalLossPct = Math.abs(losingTrades.reduce((sum, h) => sum + (h.final_pnl_pct || 0), 0));
  const profitFactor = totalLossPct > 0 ? (totalProfitPct / totalLossPct) : totalProfitPct > 0 ? 99.9 : 0;
  const avgPnl = totalClosed > 0 ? history.reduce((sum, h) => sum + (h.final_pnl_pct || 0), 0) / totalClosed : 0;

  // Canlı Log filtreleme mantığı
  const filteredLogs = logs.filter(l => {
    if (logSearch && !l.toLowerCase().includes(logSearch.toLowerCase())) return false;
    if (logLevelFilter === 'INFO' && !l.includes('INFO')) return false;
    if (logLevelFilter === 'WARNING' && !l.includes('WARNING')) return false;
    if (logLevelFilter === 'ERROR' && !l.includes('ERROR')) return false;
    if (logLevelFilter === 'SIGNAL' && !(l.includes('ALIM') || l.includes('🔔') || l.includes('Pozisyon') || l.includes('sinyali'))) return false;
    return true;
  });

  // ─ Piyasa yardımcıları ────────────────────────────────────────────────────
  const mkSortFn = (col) => {
    setMkSort(prev => ({ col, dir: prev.col === col ? -prev.dir : -1 }));
  };
  const mkFiltered = allTickers
    .filter(t => {
      if (mkSearch) return t.symbol.toLowerCase().includes(mkSearch.toLowerCase());
      if (mkFilter === 'gainers') return t.priceChangePct > 0;
      if (mkFilter === 'losers')  return t.priceChangePct < 0;
      if (mkFilter === 'high_vol') return t.quoteVolume >= 1000000;
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
            <div className="text-xs font-bold tracking-widest text-cyan-300 uppercase">JARVIS // Binance.TR Spot Terminal</div>
            <div className="text-[10px] text-gray-500">{quoteAsset} Spot · www.binance.tr</div>
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
          {/* Fütüristik Ses Kontrol Dropdown */}
          <div className="relative sound-panel-container flex items-center">
            <button 
              onClick={() => setSoundPanelOpen(o => !o)} 
              className={`p-1.5 border rounded hover:border-cyan-500 transition-colors flex items-center justify-center cursor-pointer ${
                soundMuted ? 'border-red-950 text-red-400 bg-red-950/20' : 'border-cyan-900 text-cyan-400'
              }`}
              title="Ses Efektleri Ayarı"
            >
              {soundMuted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            
            {soundPanelOpen && (
              <div className="absolute right-0 top-full mt-2 z-50 p-3 bg-gray-900 border border-cyan-800 rounded-lg shadow-2xl w-48 glass-panel font-mono text-[10px] space-y-3">
                <div className="flex items-center justify-between border-b border-cyan-950 pb-1.5">
                  <span className="font-bold text-cyan-300 uppercase tracking-wider">BİLDİRİM SESİ</span>
                  <button 
                    onClick={() => {
                      const next = !soundMuted;
                      setSoundMuted(next);
                      localStorage.setItem('jarvis_sound_muted', next.toString());
                    }}
                    className={`px-1.5 py-0.5 rounded border text-[9px] font-bold cursor-pointer ${
                      soundMuted ? 'bg-red-950 border-red-800 text-red-400' : 'bg-green-950 border-green-800 text-green-400'
                    }`}
                  >
                    {soundMuted ? 'KAPALI' : 'AÇIK'}
                  </button>
                </div>
                
                <div className="space-y-1">
                  <div className="flex justify-between text-gray-500">
                    <span>SES DÜZEYİ</span>
                    <span className="text-white font-bold">{soundVolume}%</span>
                  </div>
                  <input 
                    type="range" 
                    min="0" 
                    max="100" 
                    value={soundVolume}
                    disabled={soundMuted}
                    onChange={(e) => {
                      const val = parseInt(e.target.value);
                      setSoundVolume(val);
                      localStorage.setItem('jarvis_sound_volume', val.toString());
                    }}
                    className="w-full accent-cyan-400 h-1 bg-gray-800 rounded outline-none cursor-pointer"
                  />
                </div>

                <button 
                  onClick={() => {
                    playFuturisticChime();
                  }}
                  className="w-full py-1 border border-cyan-800 rounded hover:bg-cyan-950 text-cyan-300 font-bold hover:border-cyan-500 transition-colors uppercase text-[9px] cursor-pointer"
                >
                  🔊 TEST SESİ ÇAL
                </button>
              </div>
            )}
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

          {binanceApiError && (
            <div className="bg-red-950/20 border border-red-500 rounded-lg p-4 font-mono text-xs space-y-2 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.15)] animate-pulse">
              <div className="flex items-center gap-2 text-red-400 font-bold uppercase tracking-wider text-sm">
                <span>⚠️ BİNANCE.TR API BAĞLANTI HATASI</span>
              </div>
              <p className="text-gray-300">
                Binance.TR borsasından canlı cüzdan bakiyeniz, açık pozisyonlarınız ve aktif emirleriniz çekilemedi.
              </p>
              <div className="bg-black/50 border border-red-950 p-2.5 rounded font-mono text-[11px] text-red-300 select-all whitespace-pre-wrap">
                {binanceApiError}
              </div>
              <div className="text-[10px] text-gray-500 pt-1 leading-relaxed">
                <strong>Olası Sebepler & Çözüm Adımları:</strong>
                <ol className="list-decimal pl-4 space-y-1 mt-1">
                  <li>API Anahtarlarınız yanlış veya eksik olabilir. Lütfen <code>.env</code> dosyanızdaki <strong>BINANCE_API_KEY</strong> ve <strong>BINANCE_API_SECRET</strong> alanlarını kontrol edin.</li>
                  <li>Binance.TR API anahtarınızda <strong>"Enable Spot Trading" (Spot Alım Satımı Etkinleştir)</strong> yetkisinin açık olduğundan emin olun.</li>
                  <li>API anahtarınızda IP kısıtlaması aktifse, borsa isteklerinin engellenmemesi için sunucunun dış IP adresinin Binance.TR üzerinde beyaz listeye (whitelist) eklenmesi gerekir.</li>
                </ol>
              </div>
            </div>
          )}

          {/* Bakiye Kartları */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <StatCard icon={Wallet} label={`Cüzdan Bakiyesi (${quoteAsset})`}    value={balance ? fmt(balance.walletBalance,2) + (quoteAsset === 'TRY' ? ' ₺' : ' $') : '…'} color="text-cyan-400" />
            <StatCard icon={Coins} label={`Kullanılabilir (${quoteAsset})`}      value={balance ? fmt(balance.availableBalance,2) + (quoteAsset === 'TRY' ? ' ₺' : ' $') : '…'} color="text-green-400" />
            <StatCard icon={TrendingUp} label="Gerçekleşmemiş PnL"  value={balance ? fmt(balance.unrealizedPnl,2) + (quoteAsset === 'TRY' ? ' ₺' : ' $') : '…'} color={balance ? pnlColor(balance.unrealizedPnl) : 'text-gray-400'} />
            <StatCard icon={Activity}   label="7G Gerçekleşen PnL"  value={fmt(income.totalPnl,2) + (quoteAsset === 'TRY' ? ' ₺' : ' $')} color={pnlColor(income.totalPnl)} />
            <StatCard icon={Briefcase}  label="Açık Pozisyon"       value={binPositions.length} color="text-purple-400" />
          </div>

          {/* Performans İstatistikleri */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <StatCard icon={Zap} label="Kazanma Oranı (Win Rate)" value={winRate.toFixed(1) + ' %'} color={winRate >= 50 ? 'text-green-400' : 'text-yellow-400'} sub={`${winningTrades.length} Başarılı / ${totalClosed} Toplam`} />
            <StatCard icon={TrendingUp} label="Kâr Faktörü (Profit Factor)" value={profitFactor === 99.9 ? '∞' : profitFactor.toFixed(2)} color={profitFactor >= 1.5 ? 'text-green-400' : profitFactor >= 1.0 ? 'text-yellow-400' : 'text-red-400'} sub="Toplam Kâr / Toplam Zarar" />
            <StatCard icon={Activity} label="Ortalama İşlem PnL" value={fmtPct(avgPnl)} color={pnlColor(avgPnl)} sub="İşlem başına ortalama getiri" />
            <StatCard icon={History} label="Toplam Kapatılan İşlem" value={totalClosed} color="text-gray-400" sub="Tüm bot işlem geçmişi" />
          </div>

          {/* PnL Grafiği */}
          {income.items?.length > 0 && (
            <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
              <SectionHeader icon={TrendingUp} title={`7 Günlük Kümülatif PnL (${quoteAsset})`} />
              <PnlSparkline items={income.items} />
            </div>
          )}

          {/* Binance Açık Pozisyonlar */}
          <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
            <SectionHeader icon={Briefcase} title={`Açık Pozisyonlar (${binPositions.length})`} />
            {binPositions.length === 0
              ? <p className="text-xs text-gray-600 text-center py-4">Açık pozisyon yok.</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-gray-500 border-b border-gray-800 text-[10px]">
                      <th className="text-left py-1.5 pr-3">PARİTE</th>
                      <th className="text-right pr-3">YILDIZ</th>
                      <th className="text-right pr-3">MİKTAR</th>
                      <th className="text-right pr-3">ALIM FİYATI</th>
                      <th className="text-right pr-3">GÜNCEL FİYAT</th>
                      <th className="text-right pr-3">ALINAN DEĞER</th>
                      <th className="text-right pr-3">PNL (TL)</th>
                      <th className="text-right pr-3">PNL %</th>
                      <th className="text-right pr-3">STOP-LOSS</th>
                      <th className="text-right pr-3">HEDEF (TP)</th>
                      <th className="text-right">İŞLEMLER</th>
                    </tr></thead>
                    <tbody>
                      {binPositions.map((p, i) => {
                        const qty   = parseFloat(p.positionAmt);
                        const upnl  = parseFloat(p.unRealizedProfit);
                        const pnlP  = parseFloat(p.pnlPct || 0);
                        const side  = qty > 0 ? 'LONG' : 'SHORT';
                        const sl    = p.stop_loss_price;
                        const tp    = p.take_profit_price;
                        const entry = parseFloat(p.entryPrice);
                        const mark  = parseFloat(p.markPrice);

                        return (
                          <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                            <td className="py-1.5 pr-3 text-white font-bold">{p.symbol}</td>
                            <td className="text-right pr-3 text-yellow-400 text-[11px]">{p.stars || '—'}</td>
                            <td className="text-right pr-3 text-cyan-300">{Math.abs(qty)}</td>
                            <td className="text-right pr-3 text-blue-300 font-mono">{fmt(entry, 4)}</td>
                            <td className="text-right pr-3 font-mono font-bold">{fmt(mark, 4)}</td>
                            <td className="text-right pr-3 text-cyan-100">{fmt(parseFloat(p.allocated_budget || 0), 2)} {quoteAsset === 'TRY' ? '₺' : '$'}</td>
                            <td className={`text-right font-bold pr-3 ${pnlColor(upnl)}`}>{upnl >= 0 ? '+' : ''}{fmt(upnl, 2)} {quoteAsset === 'TRY' ? '₺' : '$'}</td>
                            <td className={`text-right font-bold pr-3 ${pnlColor(pnlP)}`}>{pnlP >= 0 ? '+' : ''}{pnlP}%</td>
                            <td className="text-right pr-3 font-mono">
                              {sl ? <span className="text-red-400">{fmt(sl, 4)}</span> : <span className="text-gray-600">—</span>}
                            </td>
                            <td className="text-right pr-3 font-mono">
                              {tp ? <span className="text-green-400">{fmt(tp, 4)}</span> : <span className="text-gray-600">—</span>}
                            </td>
                            <td className="text-right space-x-1 py-1">
                              <button onClick={() => {
                                setEditingProtectionPos(p);
                                const dbPos = dbPositions.find(x => x.symbol === p.symbol && x.status === 'OPEN');
                                setTempSlPrice(sl || dbPos?.stop_loss_price || '');
                                setTempTpPrice(tp || dbPos?.take_profit_price || '');
                              }}
                              className="bg-cyan-950 border border-cyan-800 text-cyan-300 px-2 py-0.5 rounded hover:bg-cyan-900 transition-colors text-[10px] font-bold cursor-pointer inline-flex items-center gap-0.5">
                                <Shield size={10} /> Koruma
                              </button>
                              <button onClick={() => handleClosePosition(p.symbol, Math.abs(qty), side)}
                                      className="bg-red-950 border border-red-800 text-red-400 px-2 py-0.5 rounded hover:bg-red-900 transition-colors text-[10px] font-bold cursor-pointer inline-flex items-center gap-0.5">
                                Kapat
                              </button>
                            </td>
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
      <div 
        className={activeTab === 'chart' ? "flex flex-col gap-2" : "flex flex-col gap-2 absolute pointer-events-none"} 
        style={activeTab === 'chart' 
          ? { height: 'calc(100vh - 130px)' } 
          : { height: 'calc(100vh - 130px)', width: 'calc(100vw - 24px)', left: '-99999px', top: '-99999px', opacity: 0 }
        }
      >

          {/* Toolbar */}
          <div className="flex gap-2 flex-wrap items-center bg-gray-900 border border-cyan-900 rounded-lg px-3 py-2">
            <SymbolSearch symbols={allSymbols} value={chartSymbol} onChange={s => setChartSymbol(s)} quoteAsset={quoteAsset} />
            <div className="flex gap-1">
              {INTERVALS.map(iv => (
                <button key={iv} onClick={() => setChartInterval(iv)}
                  className={`px-2.5 py-1 text-[11px] rounded border transition-colors cursor-pointer ${
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

          {/* Chart + Order Book + Emir Terminali */}
          <div className="flex gap-2 flex-1 min-h-0">
            {/* TradingView Chart */}
            <div className="flex-1 min-w-0 bg-gray-950 border border-cyan-900 rounded-lg overflow-hidden">
              <TradingViewChart symbol={chartSymbol} interval={chartInterval} />
            </div>

            {/* Order Book — orta panel */}
            <div className="w-56 shrink-0 bg-gray-900 border border-cyan-900 rounded-lg p-3 overflow-y-auto">
              <SectionHeader icon={BookOpen} title={`Order Book`} />
              <OrderBook symbol={chartSymbol} />
            </div>

            {/* Emir Gönderim Terminali — Sağ Panel */}
            <div className="w-72 shrink-0 bg-gray-900 border border-cyan-900 rounded-lg p-3 overflow-y-auto space-y-4 flex flex-col justify-between h-full font-mono text-xs">
              <div className="space-y-4">
                <SectionHeader icon={Sliders} title="Emir Terminali" />
                
                {/* Yön Seçimi LONG/SHORT -> SPOT ALIM/SATIM */}
                <div className="grid grid-cols-2 gap-2">
                  <button 
                    onClick={() => setOrderSide('LONG')}
                    className={`py-2 rounded border font-bold text-center transition-all cursor-pointer ${
                      orderSide === 'LONG' 
                        ? 'bg-green-950 border-green-500 text-green-400 shadow-[0_0_10px_rgba(34,197,94,0.25)] border-2' 
                        : 'border-gray-800 text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    🟢 SPOT BUY (ALIM)
                  </button>
                  <button 
                    onClick={() => setOrderSide('SHORT')}
                    className={`py-2 rounded border font-bold text-center transition-all cursor-pointer ${
                      orderSide === 'SHORT' 
                        ? 'bg-red-950 border-red-500 text-red-400 shadow-[0_0_10px_rgba(239,68,68,0.25)] border-2' 
                        : 'border-gray-800 text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    🔴 SPOT SELL (SATIM)
                  </button>
                </div>

                {/* Emir Türü MARKET/LIMIT */}
                <div className="flex bg-gray-950 border border-cyan-950 rounded p-0.5">
                  <button 
                    onClick={() => setOrderType('MARKET')}
                    className={`flex-1 py-1 rounded text-[10px] font-bold text-center transition-colors cursor-pointer ${
                      orderType === 'MARKET' ? 'bg-cyan-955 text-cyan-300' : 'text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    PIYASA (MARKET)
                  </button>
                  <button 
                    onClick={() => setOrderType('LIMIT')}
                    className={`flex-1 py-1 rounded text-[10px] font-bold text-center transition-colors cursor-pointer ${
                      orderType === 'LIMIT' ? 'bg-cyan-955 text-cyan-300' : 'text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    LIMIT EMIR
                  </button>
                </div>

                {/* Limit Fiyatı (Sadece LIMIT için aktif) */}
                {orderType === 'LIMIT' && (
                  <div className="space-y-1">
                    <label className="text-[10px] text-gray-500 uppercase tracking-wider">LIMIT FİYAT ({quoteAsset})</label>
                    <input 
                      type="number" 
                      step="any"
                      value={orderPrice}
                      onChange={(e) => setOrderPrice(e.target.value)}
                      placeholder={ticker ? parseFloat(ticker.lastPrice).toString() : "Fiyat girin..."}
                      className="w-full bg-gray-955 border border-cyan-950 text-cyan-200 text-xs rounded px-2.5 py-1.5 focus:border-cyan-600 outline-none font-mono font-bold"
                    />
                  </div>
                )}

                {/* Miktar */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <label className="text-[10px] text-gray-500 uppercase tracking-wider">MİKTAR ({chartSymbol.replace(quoteAsset,'')})</label>
                    {balance && (
                      <span className="text-[9px] text-gray-500">Bakiye: <span className="text-white font-bold">{fmt(balance.availableBalance,2)} {quoteAsset === 'TRY' ? '₺' : '$'}</span></span>
                    )}
                  </div>
                  <input 
                    type="number" 
                    step="any"
                    value={orderQty}
                    onChange={(e) => setOrderQty(e.target.value)}
                    placeholder="Miktar girin..."
                    className="w-full bg-gray-955 border border-cyan-950 text-cyan-200 text-xs rounded px-2.5 py-1.5 focus:border-cyan-600 outline-none font-mono font-bold"
                  />
                  
                  {/* Yüzdelik Bakiye Seçiciler */}
                  <div className="grid grid-cols-4 gap-1 pt-1">
                    {[10, 25, 50, 100].map(pct => (
                      <button 
                        key={pct}
                        onClick={() => {
                          if (!balance || !ticker) return;
                          const budget = balance.availableBalance * (pct / 100);
                          const lastPrice = parseFloat(ticker.lastPrice || 1);
                          const rawQty = budget / lastPrice;
                          const formattedQty = Math.max(Math.round(rawQty * 1000) / 1000, 0.001);
                          setOrderQty(formattedQty.toString());
                        }}
                        className="py-1 bg-gray-950 border border-gray-800 rounded text-gray-400 hover:border-cyan-800 hover:text-cyan-300 text-[9px] font-bold transition-all cursor-pointer"
                      >
                        %{pct}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Kaldıraç Göstergesi (Spot Modu) */}
                <div className="space-y-1 bg-gray-950/40 border border-cyan-950/20 p-2 rounded text-center">
                  <div className="flex justify-between text-[10px] text-gray-500">
                    <span className="uppercase tracking-wider">İşlem Tipi</span>
                    <span className="text-cyan-400 font-bold">SPOT (1x Kaldıraçsız)</span>
                  </div>
                </div>

                {/* SL/TP Koruma Ayarları */}
                <div className="border-t border-cyan-950/40 pt-3 space-y-2.5">
                  <div className="text-[10px] text-gray-400 font-bold uppercase tracking-wider flex items-center gap-1">
                    <Shield size={11} className="text-cyan-500" /> KORUMA (%)
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <label className="text-[8px] text-gray-500">STOP LOSS (SL %)</label>
                      <input 
                        type="number" 
                        step="0.1"
                        value={orderSlPct}
                        onChange={(e) => setOrderSlPct(e.target.value)}
                        placeholder="Örn: 2.0"
                        className="w-full bg-gray-955 border border-cyan-950 text-red-400 text-xs rounded px-2.5 py-1.5 focus:border-red-800 outline-none text-center font-bold"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[8px] text-gray-500">TAKE PROFIT (TP %)</label>
                      <input 
                        type="number" 
                        step="0.1"
                        value={orderTpPct}
                        onChange={(e) => setOrderTpPct(e.target.value)}
                        placeholder="Örn: 4.0"
                        className="w-full bg-gray-955 border border-cyan-950 text-green-400 text-xs rounded px-2.5 py-1.5 focus:border-green-800 outline-none text-center font-bold"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Harekete Geçiren Büyük Neon Aksiyon Butonu */}
              <button 
                onClick={handlePlaceManualOrder}
                className={`w-full py-2.5 rounded font-bold uppercase text-xs tracking-widest transition-all cursor-pointer ${
                  orderSide === 'LONG' 
                    ? 'bg-green-950 border border-green-500 text-green-400 shadow-[0_0_15px_rgba(34,197,94,0.3)] hover:bg-green-900' 
                    : 'bg-red-950 border border-red-500 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.3)] hover:bg-red-900'
                }`}
              >
                {orderSide === 'LONG' ? '🚀 SPOT BUY EMİR GÖNDER' : '💥 SPOT SELL EMİR GÖNDER'}
              </button>
            </div>
          </div>
      </div>
      {/* ════════════════ PİYASA SEKMESİ ════════════════ */}
      {activeTab === 'market' && (() => {
        const maxVol = Math.max(...mkFiltered.map(t => t.quoteVolume), 1);
        return (
          <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4 space-y-3">

            {/* Özet istatistikler */}
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-gray-800 rounded-lg p-3 text-center">
                <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Toplam Parite</div>
                <div className="text-xl font-bold text-cyan-300">{allTickers.length}</div>
                <div className="text-[10px] text-gray-500">{quoteAsset} Spot</div>
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
              {['all','gainers','losers','high_vol'].map(f => (
                <button key={f} onClick={() => { setMkFilter(f); setMkSearch(''); }}
                  className={`px-3 py-1.5 text-[11px] rounded border font-bold transition-colors cursor-pointer ${
                    mkFilter===f && !mkSearch
                      ? f==='gainers' ? 'bg-green-950 border-green-700 text-green-400 font-bold'
                        : f==='losers' ? 'bg-red-950 border-red-800 text-red-400 font-bold'
                        : f==='high_vol' ? 'bg-yellow-950 border-yellow-700 text-yellow-450 font-bold bg-yellow-950/20'
                        : 'bg-cyan-950 border-cyan-700 text-cyan-300 font-bold'
                      : 'border-gray-700 text-gray-500 hover:border-gray-600'
                  }`}>
                  {f==='all' ? 'Tümü' : f==='gainers' ? '▲ Yükselen' : f==='losers' ? '▼ Düşen' : `🔥 Hacimli (>1M ${quoteAsset})`}
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
                          HACİM (M{quoteAsset === 'TRY' ? '₺' : '$'}) {mkSort.col==='quoteVolume' ? (mkSort.dir===1 ? <ArrowUp size={9} className="inline"/> : <ArrowDown size={9} className="inline"/>) : null}
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
                        const volPercent = (t.quoteVolume / maxVol) * 100;
                        return (
                          <tr key={t.symbol}
                            className="border-b border-gray-800 hover:bg-gray-800 cursor-pointer"
                            onClick={() => { setChartSymbol(t.symbol); setActiveTab('chart'); }}>
                            <td className="py-1.5 pr-2 text-gray-600">{i+1}</td>
                            <td className="pr-3 font-bold text-white">
                              {t.symbol.replace(quoteAsset,'')}
                              <span className="text-gray-600 font-normal">/{quoteAsset}</span>
                            </td>
                            <td className="text-right pr-3 font-mono text-cyan-200">{t.lastPrice.toFixed(priceDec)}</td>
                            <td className={`text-right pr-3 font-bold ${isPos ? 'text-green-400' : 'text-red-400'}`}>
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${isPos ? 'bg-green-950' : 'bg-red-950'}`}>
                                {isPos ? '+' : ''}{t.priceChangePct.toFixed(2)}%
                              </span>
                            </td>
                            <td className="text-right pr-3 text-green-600 font-mono">{t.highPrice.toFixed(priceDec)}</td>
                            <td className="text-right pr-3 text-red-700 font-mono">{t.lowPrice.toFixed(priceDec)}</td>
                            
                            {/* Bağıl Hacim Neon Barı */}
                            <td className="text-right pr-3 font-bold text-yellow-500 relative min-w-[100px] font-mono">
                              <div 
                                className="absolute right-0 top-0 bottom-0 bg-yellow-500/10 border-r border-yellow-500/35"
                                style={{ width: `${Math.min(volPercent, 100)}%`, pointerEvents: 'none' }}
                              />
                              <span className="relative z-10">{(t.quoteVolume/1e6).toFixed(1)}M</span>
                            </td>
                            
                            <td className="text-right text-gray-500">{t.count >= 1000 ? (t.count/1000).toFixed(0)+'K' : t.count}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        );
      })()}

      {/* ════════════════ SİNYAL KARTLARI SEKMESİ ════════════════ */}
      {activeTab === 'scanner' && (
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
          <SectionHeader icon={Zap} title={`Son Alım Sinyalleri (${recentSignals.length})`} />
          {recentSignals.length === 0
            ? <p className="text-xs text-gray-600 text-center py-10">Henüz sinyal üretilmedi. Scanner tarıyor…</p>
            : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {recentSignals.map((sig, i) => (
                  <SignalCard key={i} sig={sig} onSelect={handleSelectSignal} onExecute={handleForceExecute} onOpenDetails={setSelectedSignalForModal} />
                ))}
              </div>
            )}
        </div>
      )}

      {/* ════════════════ CANLI LOG SEKMESİ ════════════════ */}
      {activeTab === 'log' && (
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2 border-b border-cyan-900 pb-2">
            <div className="flex items-center gap-2">
              <Terminal size={14} className="text-cyan-500" />
              <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest">Jarvis Live Core Log Stream</span>
            </div>
            
            {/* Canlı Log Arama ve Filtreleme */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={11} className="absolute left-2 top-2 text-gray-500" />
                <input type="text" value={logSearch} onChange={e => setLogSearch(e.target.value)}
                  placeholder="Loglarda ara..."
                  className="bg-gray-800 border border-gray-700 text-cyan-300 text-xs rounded pl-6 pr-2 py-1 w-36 focus:border-cyan-600 outline-none" />
              </div>
              <div className="flex gap-0.5">
                {['ALL', 'INFO', 'WARNING', 'ERROR', 'SIGNAL'].map(lvl => (
                  <button key={lvl} onClick={() => setLogLevelFilter(lvl)}
                    className={`px-2 py-0.5 text-[9px] font-bold rounded border transition-colors ${
                      logLevelFilter === lvl ? 'bg-cyan-950 border-cyan-500 text-cyan-300' : 'border-gray-800 text-gray-500 hover:text-gray-400'
                    }`}>
                    {lvl === 'ALL' ? 'Tümü' : lvl === 'SIGNAL' ? 'Sinyal' : lvl}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="h-[68vh] overflow-y-auto text-xs leading-5 space-y-0.5 pr-1 font-mono">
            {filteredLogs.length === 0
              ? <span className="text-gray-600">Log bulunamadı veya log bekleniyor…</span>
              : filteredLogs.map((line, i) => (
                  <div key={i} className={`whitespace-pre-wrap break-all ${logColor(line)}`}>{line}</div>
                ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {editingProtectionPos && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-900 border border-cyan-800 rounded-lg p-4 w-80 glass-panel font-mono text-xs space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-cyan-900 pb-2">
              <span className="font-bold text-cyan-300 uppercase tracking-widest flex items-center gap-1.5">
                <Shield size={14} className="text-cyan-500" />
                {editingProtectionPos.symbol} KORUMA AYARI
              </span>
              <button onClick={() => setEditingProtectionPos(null)} className="text-gray-500 hover:text-white transition-colors cursor-pointer text-sm font-bold">✕</button>
            </div>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wider">STOP LOSS (SL) FİYATI</label>
                <input type="number" step="any" value={tempSlPrice} onChange={e => setTempSlPrice(e.target.value)} placeholder="Örn: 72400 (Boş ise iptal)" className="w-full bg-gray-800 border border-gray-700 text-cyan-200 text-xs rounded px-2.5 py-1.5 focus:border-cyan-600 outline-none font-mono" />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wider">TAKE PROFIT (TP) FİYATI</label>
                <input type="number" step="any" value={tempTpPrice} onChange={e => setTempTpPrice(e.target.value)} placeholder="Örn: 76500 (Boş ise iptal)" className="w-full bg-gray-800 border border-gray-700 text-cyan-200 text-xs rounded px-2.5 py-1.5 focus:border-cyan-600 outline-none font-mono" />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setEditingProtectionPos(null)} className="flex-1 py-1.5 border border-gray-700 rounded hover:bg-gray-800 text-gray-400 font-bold transition-colors uppercase text-[10px] cursor-pointer">Vazgeç</button>
              <button onClick={handleUpdateProtection} className="flex-1 py-1.5 bg-cyan-950 border border-cyan-500 text-cyan-300 rounded hover:bg-cyan-900 font-bold transition-colors uppercase text-[10px] cursor-pointer">Güncelle</button>
            </div>
          </div>
        </div>
      )}

      {selectedSignalForModal && (() => {
        const sig = selectedSignalForModal;
        const sl = sig.price * (1 - sig.stop_loss_pct / 100);
        const tp = sig.price * (1 + sig.take_profit_pct / 100);
        const totalDist = tp - sl;
        const entryPercent = totalDist > 0 ? ((sig.price - sl) / totalDist) * 100 : 50;
        const statusColor = { PENDING:'yellow', EXECUTED:'green', SKIPPED:'gray', EXPIRED:'red' }[sig.status] || 'gray';
        const rsiPct = Math.min(Math.max(sig.rsi_value || 50, 0), 100);
        const adxPct = Math.min(Math.max(sig.adx_value || 25, 0), 100);
        
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm font-mono text-xs">
            <div className="bg-gray-900 border border-cyan-800 rounded-lg p-5 w-[420px] glass-panel space-y-4 shadow-2xl text-cyan-300">
              <div className="flex items-center justify-between border-b border-cyan-900 pb-2">
                <span className="font-bold text-white uppercase tracking-widest text-sm flex items-center gap-1.5">
                  🔔 SİNYAL DETAY ANALİZİ
                </span>
                <button onClick={() => setSelectedSignalForModal(null)} className="text-gray-500 hover:text-white transition-colors cursor-pointer text-sm font-bold">✕</button>
              </div>
              
              {/* Card Info Header */}
              <div className="flex justify-between items-start bg-gray-950/40 p-2.5 rounded border border-cyan-950/50">
                <div>
                  <div className="text-base font-bold text-white">{sig.symbol}</div>
                  <div className="text-[10px] text-gray-500">{sig.matched_pattern || sig.star_label || 'OCC Sinyali'}</div>
                </div>
                <div className="text-right">
                  <Badge label={sig.status} color={statusColor} />
                  <div className="text-yellow-300 text-sm mt-0.5">{sig.stars || '⭐'}</div>
                </div>
              </div>

              {/* RSI / ADX Gauges */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-950/40 border border-cyan-950/40 p-2.5 rounded text-center space-y-2">
                  <div className="text-[9px] text-gray-500 uppercase">RSI GÖSTERGESİ</div>
                  <div className="relative flex justify-center items-center h-12 w-full">
                    <div className="absolute w-24 h-12 border-t-8 border-l-8 border-r-8 border-cyan-950 rounded-t-full" />
                    <div 
                      className="absolute w-24 h-12 border-t-8 border-l-8 border-r-8 border-cyan-500 rounded-t-full origin-bottom transition-transform"
                      style={{ transform: `rotate(${(rsiPct/100)*180 - 90}deg)` }}
                    />
                    <span className="absolute bottom-0 text-white font-bold text-sm">{fmt(sig.rsi_value,1)}</span>
                  </div>
                  <span className="text-[9px] text-gray-400 capitalize">{sig.rsi_quality} Bölgesi</span>
                </div>

                <div className="bg-gray-950/40 border border-cyan-950/40 p-2.5 rounded text-center space-y-2">
                  <div className="text-[9px] text-gray-500 uppercase">TREND GÜCÜ (ADX)</div>
                  <div className="relative flex justify-center items-center h-12 w-full">
                    <div className="absolute w-24 h-12 border-t-8 border-l-8 border-r-8 border-cyan-950 rounded-t-full" />
                    <div 
                      className="absolute w-24 h-12 border-t-8 border-l-8 border-r-8 border-yellow-500 rounded-t-full origin-bottom transition-transform"
                      style={{ transform: `rotate(${(adxPct/100)*180 - 90}deg)` }}
                    />
                    <span className="absolute bottom-0 text-white font-bold text-sm">{fmt(sig.adx_value,1)}</span>
                  </div>
                  <span className="text-[9px] text-gray-400 capitalize">{sig.adx_regime} Rejimi</span>
                </div>
              </div>

              {/* Risk/Reward yatay visual bar */}
              <div className="space-y-2 bg-gray-950/40 p-3 rounded border border-cyan-950/30">
                <div className="text-[9px] text-gray-500 uppercase flex justify-between">
                  <span>R:R ORANI (1:{(sig.take_profit_pct/sig.stop_loss_pct).toFixed(1)})</span>
                  <span className="text-white font-bold">Risk/Reward Çizelgesi</span>
                </div>
                
                {/* Progress line */}
                <div className="relative h-2 w-full bg-gray-800 rounded-full my-4">
                  {/* Stop loss label */}
                  <span className="absolute -top-3 left-0 text-[8px] text-red-500 font-bold">SL ({fmt(sl)})</span>
                  {/* Take profit label */}
                  <span className="absolute -top-3 right-0 text-[8px] text-green-400 font-bold">TP ({fmt(tp)})</span>
                  
                  {/* Entry marker */}
                  <div 
                    className="absolute -top-1 w-4 h-4 bg-cyan-400 border-2 border-gray-900 rounded-full shadow-[0_0_6px_#22d3ee] flex items-center justify-center -ml-2"
                    style={{ left: `${entryPercent}%` }}
                    title={`Giriş: ${fmt(sig.price)}`}
                  />
                  <span 
                    className="absolute -bottom-3 text-[8px] text-cyan-300 font-bold -ml-4"
                    style={{ left: `${entryPercent}%` }}
                  >
                    Giriş ({fmt(sig.price)})
                  </span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 pt-2 border-t border-cyan-950/30">
                <button 
                  onClick={() => {
                    handleSelectSignal(sig.symbol);
                    setSelectedSignalForModal(null);
                  }}
                  className="flex-1 py-2 bg-cyan-950 border border-cyan-500 text-cyan-300 rounded hover:bg-cyan-900 font-bold transition-all uppercase text-[10px] cursor-pointer inline-flex items-center justify-center gap-1"
                >
                  <Eye size={12} /> Grafikte Göster
                </button>
                <button 
                  onClick={() => {
                    setSelectedSignalForModal(null);
                  }}
                  className="py-2 px-4 border border-gray-700 text-gray-400 rounded hover:bg-gray-800 font-bold transition-all uppercase text-[10px] cursor-pointer"
                >
                  Kapat
                </button>
              </div>
            </div>
          </div>
        );
      })()}

    </div>
  );
}
