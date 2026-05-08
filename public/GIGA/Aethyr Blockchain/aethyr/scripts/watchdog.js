'use strict';
// ================================================================
// AETHYR ONE — watchdog.js
// Autonomous self-repair: runs every 30s.
// New rules vs previous: disk_space + memory_pressure.
// Always preserves chain state before acting.
// ================================================================
const fs     = require('fs');
const { execSync } = require('child_process');
const { spawn }    = require('child_process');
const { BASE_DIR } = require('./config');
const { audit, recentLogs } = require('./audit');
const {
  RPC_POOLS, RPC_FALLBACKS, rpcState, chainState,
  saveCursors, saveChainRegistry,
} = require('./rpc');

let _cs          = null;
let _ipfsPin     = async () => null;
let _syncNonce   = async () => {};
let _tgNow       = () => {};
let _record      = () => {};
let _sandboxExec = async () => {};
let _spawnNode   = () => {};

function init({ consensusState, ipfsPin, syncNonce, tgNow, record, sandboxExec, spawnNode }) {
  _cs          = consensusState;
  _ipfsPin     = ipfsPin;
  _syncNonce   = syncNonce;
  _tgNow       = tgNow;
  _record      = record;
  _sandboxExec = sandboxExec;
  _spawnNode   = spawnNode;
}

const watchdog_fired    = new Map();
const watchdogHeartbeat = { lastBlock: 0, lastBlockTime: Date.now() };

// ── Disk space helper ────────────────────────────────────────────
function getDiskUsage(dir) {
  try {
    // df outputs: Filesystem 1K-blocks Used Available Use% Mounted
    const out = execSync(`df -k "${dir}" 2>/dev/null | tail -1`, { timeout: 3000 }).toString().trim();
    const parts = out.split(/\s+/);
    const usedPct = parseInt(parts[4]); // e.g. "87%"
    const availKb = parseInt(parts[3]);
    return { usedPct: isNaN(usedPct) ? 0 : usedPct, availMb: Math.round(availKb / 1024) };
  } catch { return { usedPct: 0, availMb: Infinity }; }
}

// ── Memory helper ────────────────────────────────────────────────
function getMemUsage() {
  const mem = process.memoryUsage();
  return {
    heapUsedMb:  Math.round(mem.heapUsed  / 1024 / 1024),
    heapTotalMb: Math.round(mem.heapTotal / 1024 / 1024),
    rssMb:       Math.round(mem.rss       / 1024 / 1024),
  };
}

// ── Rules ────────────────────────────────────────────────────────
const WATCHDOG_RULES = [
  // ── Disk space ─────────────────────────────────────────────────
  {
    name: 'disk_space',
    detect: () => {
      const { usedPct, availMb } = getDiskUsage(BASE_DIR);
      return usedPct >= 85 || availMb < 512; // warn at 85% or < 512 MB free
    },
    severity: 'HIGH',
    fix: async () => {
      const { usedPct, availMb } = getDiskUsage(BASE_DIR);
      const steps = [`Disk at ${usedPct}% — ${availMb} MB free`];

      // 1. Prune old evolution backups (*.bak.*)
      try {
        const baks = fs.readdirSync(BASE_DIR)
          .filter(f => f.includes('.bak.'))
          .sort()
          .slice(0, -2); // keep 2 newest
        for (const f of baks) { fs.unlinkSync(require('path').join(BASE_DIR, f)); }
        if (baks.length) steps.push(`Pruned ${baks.length} backup(s)`);
      } catch {}

      // 2. Rotate audit log if > 50 MB
      try {
        const { AUDIT_FILE } = require('./config');
        const sz = fs.statSync(AUDIT_FILE).size;
        if (sz > 50 * 1024 * 1024) {
          fs.renameSync(AUDIT_FILE, `${AUDIT_FILE}.${Date.now()}.old`);
          steps.push(`Rotated audit.log (was ${Math.round(sz/1024/1024)} MB)`);
        }
      } catch {}

      // 3. Prune CID history if > 5 MB
      try {
        const { CID_HIST } = require('./config');
        const sz = fs.statSync(CID_HIST).size;
        if (sz > 5 * 1024 * 1024) {
          const lines = fs.readFileSync(CID_HIST, 'utf8').split('\n');
          fs.writeFileSync(CID_HIST, lines.slice(-500).join('\n'));
          steps.push(`Pruned cid-history.txt to last 500 entries`);
        }
      } catch {}

      const after = getDiskUsage(BASE_DIR);
      steps.push(`Disk now: ${after.usedPct}% used, ${after.availMb} MB free`);
      if (after.usedPct >= 90) {
        _tgNow(`🚨 *DISK CRITICAL*\n${after.usedPct}% used — ${after.availMb} MB free\nChaindata growth may need manual pruning.`);
      }
      audit('DISK_CLEANUP', steps.join('|'));
      return steps.join(' → ');
    },
  },

  // ── Memory pressure ────────────────────────────────────────────
  {
    name: 'memory_pressure',
    detect: () => {
      const { heapUsedMb, rssMb } = getMemUsage();
      return heapUsedMb > 800 || rssMb > 1500; // alert at >800MB heap or >1.5GB RSS
    },
    severity: 'MEDIUM',
    fix: async () => {
      const before = getMemUsage();
      // Force GC if available (node --expose-gc)
      if (global.gc) { global.gc(); }
      // Trim blockSigs map — keep only last 100 signatures
      try {
        const { blockSigs } = require('./consensus');
        if (blockSigs.size > 100) {
          const keys = [...blockSigs.keys()];
          keys.slice(0, keys.length - 100).forEach(k => blockSigs.delete(k));
        }
      } catch {}
      const after = getMemUsage();
      return `Heap: ${before.heapUsedMb}→${after.heapUsedMb} MB | RSS: ${before.rssMb}→${after.rssMb} MB`;
    },
  },

  // ── Clock skew ─────────────────────────────────────────────────
  {
    name: 'clock_skew',
    detect: () => recentLogs.some(l => l.includes('invalid timestamp') && l.includes('given')),
    severity: 'HIGH',
    fix: async () => {
      _cs.engineLocked = false;
      try { await _sandboxExec('timedatectl', ['set-ntp', 'true']); } catch {}
      return `Clock skew: chainTs=${_cs.headTimestamp} wallTs=${Math.floor(Date.now()/1000)} — NTP sync attempted`;
    },
  },

  // ── Node not running ───────────────────────────────────────────
  {
    name: 'node_not_running',
    detect: () => !_cs.nodeProc || _cs.nodeProc.killed,
    severity: 'CRITICAL',
    fix: async () => {
      saveCursors(); saveChainRegistry();
      _cs.nodeProc = _spawnNode();
      return 'Node respawned — chain state preserved';
    },
  },

  // ── Engine unlocked ────────────────────────────────────────────
  {
    name: 'engine_unlocked',
    detect: () => !_cs.engineLocked && _cs.latestBlock > 0,
    severity: 'HIGH',
    fix: async () => {
      _cs.engineFcuVer = 'V3'; _cs.enginePayVer = 'V3';
      return 'Engine version reset — will re-detect on next tick';
    },
  },

  // ── Consensus stalled ──────────────────────────────────────────
  {
    name: 'consensus_stalled',
    detect: () => {
      const stalled = _cs.latestBlock === watchdogHeartbeat.lastBlock && _cs.latestBlock > 0;
      if (!stalled) watchdogHeartbeat.lastBlock = _cs.latestBlock;
      return stalled && (Date.now() - watchdogHeartbeat.lastBlockTime > 180_000);
    },
    severity: 'CRITICAL',
    fix: async () => {
      saveCursors();
      try {
        const r = await require('./rpc').rpcCall('eth_getBlockByNumber', ['latest', false]);
        if (r?.hash) { _cs.headHash = _cs.safeHash = _cs.finalHash = r.hash; _cs.headNumber = parseInt(r.number, 16); }
      } catch {}
      _cs.engineLocked = false;
      watchdogHeartbeat.lastBlockTime = Date.now();
      return `Consensus reset — head re-seeded at #${_cs.headNumber}`;
    },
  },

  // ── Dead RPCs ──────────────────────────────────────────────────
  {
    name: 'dead_rpcs',
    detect: () => Object.keys(RPC_POOLS).some(c => {
      const pool = RPC_POOLS[c];
      const now  = Date.now();
      return pool.length > 0 && pool.every(u => (rpcState[c]?.failures[u] || 0) > now);
    }),
    severity: 'HIGH',
    fix: async () => {
      const now        = Date.now();
      const allChains  = Object.keys(RPC_POOLS);
      const deadChains = allChains.filter(c => RPC_POOLS[c].every(u => (rpcState[c]?.failures[u] || 0) > now));
      const isMassOutage = deadChains.length >= 3;

      if (isMassOutage) {
        console.log(`[WATCHDOG] Mass outage (${deadChains.length}/${allChains.length} chains dead) — clearing all backoffs`);
        for (const chain of allChains) {
          if (rpcState[chain]) { rpcState[chain].failures = {}; rpcState[chain].idx = 0; }
        }
        await new Promise(r => setTimeout(r, 3000));
      }

      const repaired = [];
      for (const chain of deadChains) {
        const pool = RPC_POOLS[chain];
        if (!isMassOutage) rpcState[chain].failures = {};
        let recovered = false;
        for (const url of pool) {
          try {
            const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({jsonrpc:'2.0',id:1,method:'eth_blockNumber',params:[]}), signal: AbortSignal.timeout(6000) });
            const d   = await res.json();
            if (d.result) { rpcState[chain].idx = pool.indexOf(url); recovered = true; break; }
          } catch {}
        }
        if (recovered) { repaired.push(`${chain}:recovered`); continue; }
        const fallbacks = RPC_FALLBACKS[chain] || [];
        let added = 0;
        for (const url of fallbacks) {
          if (RPC_POOLS[chain].includes(url)) continue;
          try {
            const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({jsonrpc:'2.0',id:1,method:'eth_blockNumber',params:[]}), signal: AbortSignal.timeout(6000) });
            const d   = await res.json();
            if (d.result) {
              RPC_POOLS[chain].unshift(url); rpcState[chain].failures = {}; rpcState[chain].idx = 0;
              added++; audit('RPC_FALLBACK_INJECTED', `chain=${chain} url=${url}`);
              if (added >= 2) break;
            }
          } catch {}
        }
        if (added > 0) { saveChainRegistry(); repaired.push(`${chain}:+${added}fallbacks`); }
        else repaired.push(`${chain}:all_dead`);
      }
      return (isMassOutage ? `[mass-outage ${deadChains.length}ch] ` : '') +
        (repaired.length ? repaired.join(' ') : 'no chains needed repair');
    },
  },

  // ── Nonce desync ───────────────────────────────────────────────
  {
    name: 'nonce_desync',
    detect: () => recentLogs.slice(-10).some(l => l.includes('nonce too low') || l.includes('nonce too high')),
    severity: 'MEDIUM',
    fix: async () => { await _syncNonce(); return 'Nonce reset and resynced from chain'; },
  },

  // ── IPFS offline ───────────────────────────────────────────────
  {
    name: 'ipfs_offline',
    detect: () => !_cs.ipfsOnline && _cs.latestBlock > 10,
    severity: 'MEDIUM',
    fix: async () => {
      const steps = [];

      // Step 0: flag may be stale — check before doing anything
      try {
        const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method:'POST', signal: AbortSignal.timeout(4000) });
        if (r.ok) {
          _cs.ipfsOnline = true;
          steps.push('IPFS already running — flag was stale ✅');
          if (_cs.latestBlock > 0) { const cid = await _ipfsPin(_cs.latestBlock); if (cid) steps.push(`Pinned #${_cs.latestBlock} → ${cid}`); }
          audit('IPFS_REPAIR', steps.join('|'));
          return steps.join(' → ');
        }
      } catch {}

      // Step 1: try systemctl restart for known service names
      for (const svcName of ['ipfs', 'ipfs-daemon', 'kubo']) {
        try {
          await _sandboxExec('/bin/systemctl', ['status', svcName]);
          await _sandboxExec('/bin/systemctl', ['restart', svcName]);
          steps.push(`systemctl restart ${svcName}: OK`);
          await new Promise(r => setTimeout(r, 3000));
          break;
        } catch (e) {
          const msg = e.message || '';
          if (!msg.includes('could not be found') && !msg.includes('no such') &&
              !msg.includes('not-found') && !msg.includes('exit code 4')) {
            steps.push(`restart ${svcName}: ${msg.slice(0, 50)}`);
          }
        }
      }

      // Step 2: re-check API
      for (let i = 0; i < 3; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
          const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method:'POST', signal: AbortSignal.timeout(4000) });
          if (r.ok) {
            _cs.ipfsOnline = true; steps.push('IPFS API responding ✅');
            if (_cs.latestBlock > 0) { const cid = await _ipfsPin(_cs.latestBlock); if (cid) steps.push(`Pinned #${_cs.latestBlock} → ${cid}`); }
            audit('IPFS_REPAIR', steps.join('|'));
            return steps.join(' → ');
          }
        } catch {}
      }

      // Step 3: direct launch
      for (const bin of ['/usr/local/bin/ipfs', '/usr/bin/ipfs']) {
        if (!fs.existsSync(bin)) continue;
        try {
          const p = spawn(bin, ['daemon', '--init'], { detached: true, stdio: 'ignore', cwd: BASE_DIR });
          p.unref(); steps.push(`launched ${bin} directly`);
          await new Promise(r => setTimeout(r, 6000));
          try {
            const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method:'POST', signal: AbortSignal.timeout(4000) });
            if (r.ok) { _cs.ipfsOnline = true; steps.push('IPFS online ✅'); }
          } catch {}
          break;
        } catch (e) { steps.push(`direct launch ${bin}: ${e.message.slice(0, 60)}`); }
      }

      audit('IPFS_REPAIR', steps.join('|'));
      return steps.join(' → ') || 'IPFS unreachable';
    },
  },
];

// ── Runner ────────────────────────────────────────────────────────
async function watchdog() {
  if (!_cs || _cs.shuttingDown) return;
  const triggered = [];
  for (const rule of WATCHDOG_RULES) {
    try {
      if (!rule.detect()) continue;
      const lastFired = watchdog_fired.get(rule.name) || 0;
      if (Date.now() - lastFired < 300_000) continue; // 5-min debounce
      watchdog_fired.set(rule.name, Date.now());
      saveCursors(); saveChainRegistry();
      audit('WATCHDOG_TRIGGER', `rule=${rule.name} severity=${rule.severity}`);
      const result = await rule.fix();
      triggered.push({ name: rule.name, severity: rule.severity, result });
      console.log(`[WATCHDOG] ✅ ${rule.name}: ${result}`);
    } catch (e) {
      console.error(`[WATCHDOG] ❌ ${rule.name}: ${e.message}`);
      triggered.push({ name: rule.name, severity: rule.severity, result: `FAILED: ${e.message.slice(0, 80)}` });
    }
  }
  if (triggered.length > 0) {
    const lines = triggered.map(t =>
      `${t.severity === 'CRITICAL' ? '🚨' : t.severity === 'HIGH' ? '⚠️' : 'ℹ️'} *${t.name.replace(/_/g, '\\_')}*\n${t.result.replace(/_/g, '\\_')}`
    ).join('\n\n');
    _tgNow(`🔧 *CORTEX Auto-Repair*\n\n${lines}\n\nState preserved ✅`);
    audit('WATCHDOG_REPAIRED', triggered.map(t => t.name).join(','));
  }
}

function startWatchdog() {
  setInterval(watchdog, 30_000);
  setTimeout(watchdog, 15_000);
  console.log('[WATCHDOG] Autonomous repair engine armed');
}

function updateHeartbeat(blockNum) {
  watchdogHeartbeat.lastBlock     = blockNum;
  watchdogHeartbeat.lastBlockTime = Date.now();
}

module.exports = { init, startWatchdog, updateHeartbeat };
