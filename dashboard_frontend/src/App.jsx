// ============================================================================
// src/App.jsx - Jarvis Trading Monitor Dashboard
// ============================================================================

import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { Terminal, Activity, Briefcase, History, TrendingUp, Wifi, WifiOff, Zap } from 'lucide-react';

const API_URL = 'http://localhost:5001';
const socket  = io(API_URL, { transports: ['websocket'] });

// ── Yardımcı: pariteden base/quote ayır ──
function splitSymbol(symbol = '') {
  if (symbol.endsWith('TRY'))  return [symbol.replace('TRY', ''),  'TRY'];
  if (symbol.endsWith('USDT')) return [symbol.replace('USDT', ''), 'USDT'];
  return [symbol, ''];
}

// ── Yardımcı: fiyatı formatla ──
function fmt(v, digits = 4) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(digits);
}

// ── İstatistik Kartı ──
function StatCard({ icon: Icon, label, value, color = 'text-cyan-400' }) {
  return (
    <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-gray-500 uppercase tracking-widest">
        <Icon size={14} />{label}
      </div>
      <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
    </div>
  );
}

// ── Bölüm Başlığı ──
function SectionHeader({ icon: Icon, title }) {
  return (
    <div className="flex items-center gap-2 mb-3 border-b border-cyan-900 pb-2">
      <Icon size={15} className="text-cyan-500" />
      <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest">{title}</span>
    </div>
  );
}

// ── TF Heatmap rozetleri ──
function TfHeatmap({ tfStatuses = [] }) {
  if (!tfStatuses.length) return null;
  const order = ['1w', '1d', '4h', '1h', '15m'];
  const sorted = [...tfStatuses].sort((a, b) => order.indexOf(a.timeframe) - order.indexOf(b.timeframe));
  return (
    <div className="flex gap-1 flex-wrap mt-1">
      {sorted.map((s) => (
        <span
          key={s.timeframe}
          className={`text-[10px] px-1.5 py-0.5 rounded font-bold border ${
            s.is_green
              ? 'bg-green-950 border-green-700 text-green-400'
              : 'bg-red-950 border-red-800 text-red-400'
          } ${s.just_crossed ? 'ring-1 ring-yellow-400' : ''}`}
          title={s.just_crossed ? 'Yeni geçiş!' : ''}
        >
          {s.is_green ? '●' : '○'} {s.timeframe}
          {s.weight > 0 ? ` [${s.weight}p]` : ' [tetik]'}
          {s.just_crossed ? ' ←' : ''}
        </span>
      ))}
    </div>
  );
}

// ── Sinyal Kartı (Telegram bildirimiyle aynı bilgiler) ──
function SignalCard({ sig }) {
  const [base, quote] = splitSymbol(sig.symbol);
  const sl  = sig.price * (1 - sig.stop_loss_pct  / 100);
  const tp  = sig.price * (1 + sig.take_profit_pct / 100);
  const rr  = sig.stop_loss_pct > 0 ? (sig.take_profit_pct / sig.stop_loss_pct).toFixed(1) : '—';

  const statusColor = {
    PENDING:  'border-yellow-600 text-yellow-400 bg-yellow-950',
    EXECUTED: 'border-green-700 text-green-400  bg-green-950',
    SKIPPED:  'border-gray-600  text-gray-400   bg-gray-900',
    EXPIRED:  'border-red-800   text-red-400    bg-red-950',
  }[sig.status] ?? 'border-gray-600 text-gray-400 bg-gray-900';

  const ts = sig.timestamp
    ? new Date(sig.timestamp).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' })
    : '—';

  return (
    <div className="bg-gray-900 border border-cyan-900 rounded-lg p-3 text-xs space-y-2">

      {/* Başlık satırı */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-base font-bold text-white">
            🔥 {base}/<span className="text-cyan-400">{quote}</span>
          </div>
          <div className="text-[10px] text-gray-500 mt-0.5">{ts}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${statusColor}`}>
            {sig.status}
          </span>
          <span className="text-yellow-300 text-sm">{sig.stars || '⭐'}</span>
          <span className="text-[10px] text-gray-400">{sig.star_label || sig.matched_pattern || '—'}</span>
        </div>
      </div>

      {/* Fiyat bilgileri */}
      <div className="grid grid-cols-3 gap-1 text-center">
        <div className="bg-gray-800 rounded p-1.5">
          <div className="text-gray-500 text-[9px] uppercase">Giriş</div>
          <div className="text-white font-bold">{fmt(sig.price)}</div>
        </div>
        <div className="bg-red-950 border border-red-900 rounded p-1.5">
          <div className="text-red-400 text-[9px] uppercase">Stop-Loss</div>
          <div className="text-red-300 font-bold">{fmt(sl)}</div>
          <div className="text-red-500 text-[9px]">-{fmt(sig.stop_loss_pct, 1)}%</div>
        </div>
        <div className="bg-green-950 border border-green-900 rounded p-1.5">
          <div className="text-green-400 text-[9px] uppercase">Hedef</div>
          <div className="text-green-300 font-bold">{fmt(tp)}</div>
          <div className="text-green-500 text-[9px]">+{fmt(sig.take_profit_pct, 1)}%</div>
        </div>
      </div>

      {/* OCC Skoru + R:R */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-gray-500">OCC:</span>
          <span className="text-cyan-300 font-bold">{sig.total_score}/{sig.max_score}p</span>
          <div className="h-1.5 w-16 bg-gray-800 rounded-full overflow-hidden ml-1">
            <div
              className="h-full bg-cyan-500 rounded-full"
              style={{ width: `${Math.round((sig.total_score / sig.max_score) * 100)}%` }}
            />
          </div>
        </div>
        <span className="text-gray-400">R:R <span className="text-white font-bold">1:{rr}</span></span>
      </div>

      {/* TF Heatmap */}
      <TfHeatmap tfStatuses={sig.tf_statuses} />

      {/* İndikatörler */}
      <div className="flex gap-3 text-[10px] text-gray-400 border-t border-gray-800 pt-1.5">
        <span>RSI <span className={`font-bold ${
          sig.rsi_quality === 'ideal' ? 'text-green-400' :
          sig.rsi_quality === 'caution' ? 'text-yellow-400' : 'text-cyan-300'
        }`}>{fmt(sig.rsi_value, 1)}</span></span>
        <span>ADX <span className={`font-bold ${
          sig.adx_regime === 'trending' ? 'text-green-400' :
          sig.adx_regime === 'ranging'  ? 'text-yellow-400' : 'text-gray-400'
        }`}>{fmt(sig.adx_value, 1)}</span></span>
        <span className="ml-auto">Pozisyon <span className="text-purple-300 font-bold">{fmt(sig.position_size_pct, 0)}%</span></span>
      </div>

    </div>
  );
}

// ==================== ANA UYGULAMA ====================

export default function App() {
  const [logs, setLogs]                   = useState([]);
  const [openPositions, setOpenPositions] = useState([]);
  const [history, setHistory]             = useState([]);
  const [recentSignals, setRecentSignals] = useState([]);
  const [stats, setStats]                 = useState({
    totalSignals: 0, executedSignals: 0, pendingSignals: 0, openPositions: 0, closedPositions: 0,
  });
  const [connected, setConnected]         = useState(false);
  const logEndRef                         = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const fetchApiData = () => {
    fetch(`${API_URL}/api/positions/open`).then(r => r.json()).then(setOpenPositions).catch(() => {});
    fetch(`${API_URL}/api/positions/history`).then(r => r.json()).then(setHistory).catch(() => {});
    fetch(`${API_URL}/api/stats`).then(r => r.json()).then(setStats).catch(() => {});
    fetch(`${API_URL}/api/signals/recent`).then(r => r.json()).then(setRecentSignals).catch(() => {});
  };

  useEffect(() => {
    fetchApiData();
    const interval = setInterval(fetchApiData, 5000);

    socket.on('connect',    () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));
    socket.on('log_init',   (init)  => setLogs(init.split('\n').filter(Boolean)));
    socket.on('log_stream', (chunk) =>
      setLogs(prev => [...prev, ...chunk.split('\n').filter(Boolean)].slice(-100)));

    return () => {
      clearInterval(interval);
      ['connect','disconnect','log_init','log_stream'].forEach(e => socket.off(e));
    };
  }, []);

  const logColor = (line) => {
    if (line.includes('ALIM SİNYALİ') || line.includes('✅') || line.includes('💾')) return 'text-green-400';
    if (line.includes('ERROR') || line.includes('❌'))  return 'text-red-400';
    if (line.includes('WARNING') || line.includes('⚠')) return 'text-yellow-400';
    if (line.includes('INFO'))                          return 'text-cyan-300';
    return 'text-gray-400';
  };

  return (
    <div className="min-h-screen bg-gray-950 text-cyan-300 font-mono p-4 space-y-4">

      {/* ── HEADER ── */}
      <header className="flex items-center justify-between border border-cyan-800 rounded-lg px-5 py-3 bg-gray-900">
        <div className="flex items-center gap-3">
          <TrendingUp size={20} className="text-cyan-400" />
          <div>
            <div className="text-sm font-bold tracking-widest text-cyan-300 uppercase">
              JARVIS // Trading Operational System
            </div>
            <div className="text-xs text-gray-500">Lokal PM2 &amp; MongoDB Altyapısı</div>
          </div>
        </div>
        <div className={`flex items-center gap-2 text-xs px-3 py-1 rounded border ${
          connected ? 'border-green-700 text-green-400' : 'border-red-800 text-red-400'
        }`}>
          {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
          {connected ? 'ONLINE' : 'OFFLINE'}
        </div>
      </header>

      {/* ── İSTATİSTİK KARTLARI ── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard icon={Activity}  label="Üretilen Sinyal"  value={stats.totalSignals}    />
        <StatCard icon={Activity}  label="Bekleyen"         value={stats.pendingSignals}  color="text-yellow-400" />
        <StatCard icon={Activity}  label="İşleme Alınan"    value={stats.executedSignals} color="text-green-400"  />
        <StatCard icon={Briefcase} label="Açık Pozisyon"    value={stats.openPositions}   color="text-purple-400" />
        <StatCard icon={History}   label="Kapatılan"        value={stats.closedPositions} color="text-gray-400"   />
      </div>

      {/* ── SINYAL KARTLARI ── */}
      <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
        <SectionHeader icon={Zap} title={`Son Alım Sinyalleri (${recentSignals.length})`} />
        {recentSignals.length === 0 ? (
          <p className="text-xs text-gray-600 text-center py-6">
            Henüz sinyal üretilmedi. Scanner tarıyor...
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 max-h-[600px] overflow-y-auto pr-1">
            {recentSignals.map((sig, i) => <SignalCard key={i} sig={sig} />)}
          </div>
        )}
      </div>

      {/* ── ORTA ALAN: POZİSYONLAR + LOG ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Açık Pozisyonlar */}
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
          <SectionHeader icon={Briefcase} title={`Canlı Açık Pozisyonlar (${openPositions.length})`} />
          {openPositions.length === 0 ? (
            <p className="text-xs text-gray-600 text-center py-8">
              Açık pozisyon yok. Scanner tarıyor...
            </p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {openPositions.map((pos, i) => (
                <div key={i} className="flex items-center justify-between border border-gray-800 rounded p-2 text-xs">
                  <div>
                    <div className="text-cyan-300 font-bold">{pos.symbol}</div>
                    <div className="text-gray-500">{pos.matched_pattern || 'Normal Giriş'}</div>
                  </div>
                  <div className="text-right">
                    <div>Giriş: <span className="text-white">{pos.entry_price}</span></div>
                    <div className="text-red-400">SL: {pos.stop_loss_price?.toFixed?.(4) ?? '—'}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Canlı Log Akışı */}
        <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
          <SectionHeader icon={Terminal} title="Jarvis Live Core Log Stream" />
          <div className="h-72 overflow-y-auto text-xs leading-5 space-y-0.5 pr-1">
            {logs.length === 0 ? (
              <span className="text-gray-600">Log bekleniyor...</span>
            ) : (
              logs.map((line, i) => (
                <div key={i} className={`whitespace-pre-wrap break-all ${logColor(line)}`}>{line}</div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>

      </div>

      {/* ── İŞLEM GEÇMİŞİ ── */}
      <div className="bg-gray-900 border border-cyan-900 rounded-lg p-4">
        <SectionHeader icon={History} title="Son Kapalı İşlemler (Geçmiş)" />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-4">PARİTE</th>
                <th className="text-left py-2 pr-4">GİRİŞ</th>
                <th className="text-left py-2 pr-4">ÇIKIŞ</th>
                <th className="text-left py-2 pr-4">SEBEP</th>
                <th className="text-right py-2">NET PNL</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-gray-600 py-6">
                    Henüz kapatılmış işlem yok.
                  </td>
                </tr>
              ) : (
                history.map((h, i) => (
                  <tr key={i} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                    <td className="py-1.5 pr-4 text-cyan-300 font-bold">{h.symbol}</td>
                    <td className="py-1.5 pr-4">{h.entry_price}</td>
                    <td className="py-1.5 pr-4">{h.exit_price}</td>
                    <td className="py-1.5 pr-4 text-gray-400">{h.close_reason}</td>
                    <td className={`py-1.5 text-right font-bold ${
                      (h.final_pnl_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {h.final_pnl_pct != null ? `${h.final_pnl_pct.toFixed(2)}%` : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
