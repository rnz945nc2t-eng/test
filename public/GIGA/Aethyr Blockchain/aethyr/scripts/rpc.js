'use strict';
// ================================================================
// AETHYR ONE — rpc.js
// Multi-RPC pools with backoff/fallback, local rpcCall,
// Engine API (JWT), cursor persistence, chain-registry.
// ================================================================
const fs     = require('fs');
const crypto = require('crypto');
const {
  VAULT, ENGINE_URL, RPC_URL,
  CURSOR_FILE, CHAIN_REG, JWT_FILE, DATA_DIR,
} = require('./config');
const { audit } = require('./audit');

// ── JWT (Engine API auth) ────────────────────────────────────────
function ensureJwt() {
  if (!fs.existsSync(JWT_FILE)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(JWT_FILE, '0x' + crypto.randomBytes(32).toString('hex'));
  }
  return fs.readFileSync(JWT_FILE, 'utf8').trim().replace(/^0x/, '');
}
function makeJwtToken(secret) {
  const h   = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const p   = Buffer.from(JSON.stringify({ iat: Math.floor(Date.now() / 1000) })).toString('base64url');
  const sig = crypto.createHmac('sha256', Buffer.from(secret, 'hex')).update(`${h}.${p}`).digest('base64url');
  return `${h}.${p}.${sig}`;
}
ensureJwt();

// ── Local chain RPC (via nginx → ayrnode) ───────────────────────
async function rpcCall(method, params = []) {
  try {
    const res = await fetch(RPC_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
    });
    return (await res.json()).result;
  } catch { return null; }
}

// ── Engine API (authenticated) ───────────────────────────────────
async function engineCall(method, params) {
  const jwt = makeJwtToken(ensureJwt());
  const res  = await fetch(ENGINE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${jwt}` },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  const data = await res.json();
  if (data.error) throw new Error(`${method}: ${data.error.message}`);
  return data.result;
}

// ── Chain Registry (persists dynamic chains added via /integrate) ─
function loadChainRegistry() {
  try { if (fs.existsSync(CHAIN_REG)) return JSON.parse(fs.readFileSync(CHAIN_REG, 'utf8')); } catch {}
  return {};
}
function saveChainRegistry() {
  try { fs.writeFileSync(CHAIN_REG, JSON.stringify(RPC_POOLS, null, 2)); } catch {}
}

// ── RPC Pools ────────────────────────────────────────────────────
const RPC_FALLBACKS = {
  ETH:   ['https://eth-mainnet.public.blastapi.io','https://virginia.rpc.blxrbdn.com','https://eth.drpc.org','https://rpc.payload.de'],
  BSC:   ['https://bsc-mainnet.public.blastapi.io','https://bsc.drpc.org','https://binance.llamarpc.com','https://bsc-rpc.publicnode.com'],
  MATIC: ['https://polygon-bor-rpc.publicnode.com','https://polygon.meowrpc.com','https://polygon.drpc.org','https://polygon-mainnet.public.blastapi.io'],
  ARB:   ['https://arbitrum.drpc.org','https://arb-mainnet.public.blastapi.io','https://arbitrum.meowrpc.com','https://arb.meowrpc.com'],
  OP:    ['https://optimism.drpc.org','https://op-mainnet.public.blastapi.io','https://optimism.meowrpc.com','https://optimism-rpc.publicnode.com'],
  BASE:  ['https://base.llamarpc.com', 'https://base-rpc.publicnode.com'],
  AVAX:  ['https://avalanche.public-rpc.com', 'https://avax.meowrpc.com'],
  FTM:   ['https://rpc.ftm.tools', 'https://fantom-rpc.publicnode.com'],
  CELO:  ['https://forno.celo.org', 'https://celo-rpc.publicnode.com'],
  CRO:   ['https://evm.cronos.org', 'https://cronos-evm-rpc.publicnode.com'],
  BLAST: ['https://rpc.blast.io', 'https://blast-rpc.publicnode.com'],
  LINEA: ['https://rpc.linea.build', 'https://linea-rpc.publicnode.com'],
  MANTLE:['https://rpc.mantle.xyz', 'https://mantle-rpc.publicnode.com'],
  SCROLL:['https://rpc.scroll.io', 'https://scroll-rpc.publicnode.com'],
  ZKSYNC:['https://mainnet.era.zksync.io', 'https://zksync-era-rpc.publicnode.com'],
};

const RPC_POOLS = {
  ETH:   ['https://eth.llamarpc.com','https://cloudflare-eth.com','https://ethereum.publicnode.com','https://eth-mainnet.public.blastapi.io'],
  BSC:   ['https://bsc-dataseed.binance.org','https://bsc-dataseed1.defibit.io','https://bsc-dataseed2.ninicoin.io','https://bsc.publicnode.com'],
  MATIC: ['https://polygon-bor-rpc.publicnode.com','https://polygon.meowrpc.com','https://rpc-mainnet.matic.quiknode.pro','https://polygon.publicnode.com'],
  ARB:   ['https://arb1.arbitrum.io/rpc','https://arbitrum.llamarpc.com','https://arbitrum-one.publicnode.com','https://arb-mainnet.public.blastapi.io'],
  OP:    ['https://mainnet.optimism.io','https://optimism.llamarpc.com','https://optimism.publicnode.com','https://op-mainnet.public.blastapi.io'],
  BASE:  ['https://mainnet.base.org', 'https://base.drpc.org'],
  AVAX:  ['https://api.avax.network/ext/bc/C/rpc', 'https://avalanche.drpc.org'],
  FTM:   ['https://rpc.ftm.tools', 'https://fantom.drpc.org'],
  CELO:  ['https://forno.celo.org', 'https://celo.drpc.org'],
  CRO:   ['https://evm.cronos.org', 'https://cronos.drpc.org'],
  BLAST: ['https://rpc.blast.io', 'https://blast.drpc.org'],
  LINEA: ['https://rpc.linea.build', 'https://linea.drpc.org'],
  MANTLE:['https://rpc.mantle.xyz', 'https://mantle.drpc.org'],
  SCROLL:['https://rpc.scroll.io', 'https://scroll.drpc.org'],
  ZKSYNC:['https://mainnet.era.zksync.io', 'https://zksync.drpc.org'],
  ...loadChainRegistry(),
};

let BRIDGE_CONTRACTS = {
  ETH:   VAULT.BRIDGE_ETH,
  BSC:   VAULT.BRIDGE_BSC,
  MATIC: VAULT.BRIDGE_MATIC,
  ARB:   VAULT.BRIDGE_ARB,
  OP:    VAULT.BRIDGE_OP,
  BASE:  VAULT.BRIDGE_BASE,
  AVAX:  VAULT.BRIDGE_AVAX,
  FTM:   VAULT.BRIDGE_FTM,
  CELO:  VAULT.BRIDGE_CELO,
  CRO:   VAULT.BRIDGE_CRO,
  BLAST: VAULT.BRIDGE_BLAST,
  LINEA: VAULT.BRIDGE_LINEA,
  MANTLE:VAULT.BRIDGE_MANTLE,
  SCROLL:VAULT.BRIDGE_SCROLL,
  ZKSYNC:VAULT.BRIDGE_ZKSYNC,
};

const SAFE_DEPTH = { ETH: 64, BSC: 15, MATIC: 128, ARB: 1, OP: 1, BASE: 1, AVAX: 2, FTM: 2, CELO: 1, CRO: 5, BLAST: 1, LINEA: 1, MANTLE: 1, SCROLL: 1, ZKSYNC: 1 };
const BRIDGE_LOCK_TOPIC = '0x9f1ec8c880f76798e7b793325d625e9b60e4082a553c98f42b6cda368dd60008';

// ── Per-chain state ──────────────────────────────────────────────
function loadCursors() {
  try { if (fs.existsSync(CURSOR_FILE)) return JSON.parse(fs.readFileSync(CURSOR_FILE, 'utf8')); } catch {}
  return {};
}
function saveCursors() {
  try {
    const c = {};
    Object.keys(rpcState).forEach(k => { c[k] = rpcState[k].lastBlock; });
    fs.writeFileSync(CURSOR_FILE, JSON.stringify(c, null, 2));
  } catch (e) { console.error('[CURSOR]', e.message); }
}
setInterval(saveCursors, 60_000);

const savedCursors = loadCursors();
const rpcState   = {};
const chainState = {};

function initChainState(c) {
  const saved  = savedCursors[c] || '0x0';
  rpcState[c]  = { idx: 0, failures: {}, lastErr: {}, lastBlock: saved };
  chainState[c]= { block: 0, latency: 0, events: 0, errors: 0, online: false };
  if (saved !== '0x0') console.log(`[CURSOR] ${c} resumed from #${parseInt(saved, 16)}`);
}
Object.keys(RPC_POOLS).forEach(initChainState);

// ── Round-robin chainRpc with backoff ────────────────────────────
async function chainRpc(chain, method, params = []) {
  const pool  = RPC_POOLS[chain];
  const state = rpcState[chain];
  const now   = Date.now();
  for (let attempt = 0; attempt < pool.length; attempt++) {
    const i   = (state.idx + attempt) % pool.length;
    const url = pool[i];
    if ((state.failures[url] || 0) > now) continue;
    try {
      const res  = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
        signal: AbortSignal.timeout(7000),
      });
      if (res.status === 429) { state.failures[url] = now + 300_000; continue; }
      const data = await res.json();
      if (data.error) throw new Error(data.error.message);
      state.idx = i;
      delete state.failures[url];
      chainState[chain].online = true;
      return data.result;
    } catch (e) {
      const host = url.split('/')[2];
      if (!state.lastErr[url] || now - state.lastErr[url] > 120_000) {
        console.log(`[RPC] ${chain} ${host}: ${e.message?.slice(0, 80)}`);
        state.lastErr[url] = now;
      }
      state.failures[url] = now + 60_000;
    }
  }
  chainState[chain].online = false;
  throw new Error(`${chain}: all ${pool.length} RPCs unavailable`);
}

module.exports = {
  rpcCall, engineCall, ensureJwt, makeJwtToken,
  RPC_POOLS, RPC_FALLBACKS, BRIDGE_CONTRACTS, SAFE_DEPTH, BRIDGE_LOCK_TOPIC,
  rpcState, chainState,
  initChainState, chainRpc,
  saveCursors, saveChainRegistry,
};
