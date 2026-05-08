'use strict';
// ================================================================
// AETHYR ONE — consensus.js
// Chain 210078 · PoS+PoA · Bitcoin Containment Protocol
//
// KEY CHANGE from v1:
//   Every AYR block header now contains a BITCOIN CHAIN COMMITMENT
//   embedded in extraData. This commitment is a rolling sha256 fold
//   of Bitcoin's entire chain from genesis to tip.
//
//   Meaning: From AYR block #1 onward, Bitcoin's chain state is
//   cryptographically sealed into AYR's canonical history.
//   Bitcoin cannot exist without being inside AYR.
//
//   extraData format (18 bytes):
//     [0..13]  First 14 bytes of btcChainCommitment
//     [14..17] Bitcoin tip height (uint32 big-endian)
// ================================================================
const fs     = require('fs');
const crypto = require('crypto');
const path   = require('path');
const { spawn } = require('child_process');
const {
  VAULT, AUTHORITY, ENGINE_URL, RPC_URL,
  CHAIN_ID, BLOCK_TIME, DATA_DIR, JWT_FILE,
  CLIENT_BIN, BASE_DIR, CID_FILE, CID_HIST, sanitize,
} = require('./config');
const { audit }               = require('./audit');
const { engineCall, rpcCall } = require('./rpc');
const signer                  = require('./signer');
const auxpow                  = require('./auxpow');
const { getChainCommitment, getBtcTipHeight } = require('./bitcoin_absorber');

// ── Injected deps ─────────────────────────────────────────────────
let _tg          = () => {};
let _tgNow       = () => {};
let _tgBuffer    = () => {};
let _record      = () => {};
let _appendLog   = () => {};
let _processFees = async () => {};
let _syncNonce   = async () => {};
let _getNonce    = () => null;

function init({ tg, tgNow, tgBuffer, record, appendBtorLog, processFees, syncNonce, getNonce }) {
  _tg          = tg;
  _tgNow       = tgNow;
  _tgBuffer    = tgBuffer;
  _record      = record;
  _appendLog   = appendBtorLog;
  _processFees = processFees;
  _syncNonce   = syncNonce;
  _getNonce    = getNonce;
}

// ── Shared state ──────────────────────────────────────────────────
const state = {
  latestBlock:    0,
  blockCount:     0,
  headHash:       '0x' + '00'.repeat(32),
  safeHash:       '0x' + '00'.repeat(32),
  finalHash:      '0x' + '00'.repeat(32),
  headNumber:     0,
  headTimestamp:  0,
  payloadId:      null,
  engineFcuVer:   'V3',
  enginePayVer:   'V3',
  engineLocked:   false,
  ipfsOnline:     false,
  shuttingDown:   false,
  nodeProc:       null,
  // Bitcoin Containment state — updated by bitcoin_absorber.js
  btcChainCommitment: '00'.repeat(32),
  btcTipHeight:       0,
  btcAbsorbedCount:   0,
  lastAuxPoWBlock:    0,
};

const validators = new Map();
const blockSigs  = new Map();

// ── Bitcoin chain commitment handler ─────────────────────────────
// Called by bitcoin_absorber.js every time a new BTC block is absorbed.
// Updates our state so the next AYR block includes this commitment.
async function onChainCommitmentUpdate({ btcHeight, btcHash, commitment,
                                         verifiedDepth, sources, absorbedCount }) {
  state.btcChainCommitment = commitment;
  state.btcTipHeight       = btcHeight;
  state.btcAbsorbedCount   = absorbedCount;
  _record(`[CONSENSUS] BTC commitment updated: #${btcHeight} depth=${verifiedDepth} sources=${sources}`);
}

// ── AuxPoW handler ────────────────────────────────────────────────
// Called by bitcoin_absorber.js when a Bitcoin block is found
// that contains an AYR block hash in its coinbase.
async function onAuxPoWFound(auxpowEvent) {
  const result = await auxpow.verifyAuxPoW(auxpowEvent);
  if (!result.valid) {
    _record(`[CONSENSUS] AuxPoW rejected: ${result.reason}`);
    return;
  }
  state.lastAuxPoWBlock = auxpowEvent.btcHeight;
  _record(`[CONSENSUS] AuxPoW certified AYR block ${result.ayrBlockHash.slice(0, 14)}`);
}

// ── Build extraData with BTC commitment ──────────────────────────
// Embeds Bitcoin chain commitment into every AYR block.
// This is the SEAL that makes Bitcoin's chain part of AYR's state.
function buildExtraData() {
  return auxpow.buildAuxPoWExtraData(
    state.btcChainCommitment || '00'.repeat(32),
    state.btcTipHeight || getBtcTipHeight() || 0
  );
}

// ── JWT ───────────────────────────────────────────────────────────
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

// ── Node spawn ────────────────────────────────────────────────────
const NOISE = ['INFO ', 'WARN ', 'DEBUG', 'TRACE', 'Imported new', 'Chain head'];

function spawnNode() {
  const proc = spawn(CLIENT_BIN, [
    '--datadir',           DATA_DIR,
    '--networkid',         CHAIN_ID,
    '--syncmode',          'full',
    '--gcmode',            'archive',
    '--port',              '30303',
    '--maxpeers',          '50',
    '--http',
    '--http.addr',         '127.0.0.1',
    '--http.port',         '8545',
    '--http.corsdomain',   '*',
    '--http.api',          'eth,net,web3,txpool,debug',
    '--authrpc.addr',      '127.0.0.1',
    '--authrpc.port',      '8551',
    '--authrpc.jwtsecret', JWT_FILE,
    '--cache',             '2048',
    '--unlock',            AUTHORITY,
    '--password',          path.join(BASE_DIR, '.signerpass'),
    '--allow-insecure-unlock',
  ], { cwd: BASE_DIR });

  proc.stdout.on('data', d => d.toString().split('\n').forEach(l => {
    const line = sanitize(l.trim()); if (!line) return;
    if (!NOISE.some(n => line.includes(n))) console.log(`[NODE] ${line}`);
    _record(`[NODE] ${line}`);
  }));
  proc.stderr.on('data', d => d.toString().split('\n').forEach(l => {
    const line = sanitize(l.trim()); if (!line) return;
    if (!NOISE.some(n => line.includes(n))) console.error(`[NODE ERR] ${line}`);
    _record(`[NODE ERR] ${line}`);
  }));
  proc.on('error', err => {
    console.error(`[SPAWN] ${err.message}`);
    _tgNow(`Node spawn error: \`${err.message}\``);
  });
  proc.on('exit', code => {
    if (state.shuttingDown) return;
    _tgNow(`AETHYR node crashed (exit ${code ?? '?'}) — restarting in 10s`);
    audit('NODE_CRASH', `exit=${code}`);
    setTimeout(() => { state.nodeProc = spawnNode(); }, 10_000);
  });
  return proc;
}

// ── Engine version detection ──────────────────────────────────────
async function detectEngineVersion() {
  for (const ver of ['V3', 'V2', 'V1']) {
    try {
      const ts    = state.headTimestamp > 0
        ? Math.max(Math.floor(Date.now() / 1000), state.headTimestamp + 1)
        : Math.floor(Date.now() / 1000);
      const attrs = {
        timestamp:             '0x' + ts.toString(16),
        prevRandao:            '0x' + crypto.randomBytes(32).toString('hex'),
        suggestedFeeRecipient: AUTHORITY,
        extraData:             buildExtraData(), // BTC commitment
      };
      if (ver !== 'V1') attrs.withdrawals = [];
      if (ver === 'V3') attrs.parentBeaconBlockRoot = '0x' + '00'.repeat(32);
      const r = await engineCall(`engine_forkchoiceUpdated${ver}`, [
        { headBlockHash: state.headHash, safeBlockHash: state.safeHash, finalizedBlockHash: state.finalHash },
        attrs,
      ]);
      state.engineFcuVer = state.enginePayVer = ver;
      state.engineLocked = true;
      console.log(`[CONSENSUS] Engine API locked: ${ver}`);
      _tg(`Engine API: *${ver}* | BTC containment: ✅`);
      if (r?.payloadId) state.payloadId = r.payloadId;
      return ver;
    } catch (e) {
      if (/unsupported|unknown method|not supported|invalid params/i.test(e.message)) {
        console.log(`[CONSENSUS] engine_forkchoiceUpdated${ver} not supported`); continue;
      }
      console.error(`[CONSENSUS] detect: ${e.message}`); return null;
    }
  }
  return null;
}

// ── Consensus tick ────────────────────────────────────────────────
async function consensusTick() {
  if (state.shuttingDown) return;
  try {
    if (!state.engineLocked) { const v = await detectEngineVersion(); if (!v) return; }

    const wallTs = Math.floor(Date.now() / 1000);
    const ts     = state.headTimestamp > 0 ? Math.max(wallTs, state.headTimestamp + 1) : wallTs;
    if (state.headTimestamp > wallTs + 60 && !consensusTick._skewLogged) {
      consensusTick._skewLogged = true;
      console.log(`[CONSENSUS] Chain ts ahead of wall by ${state.headTimestamp - wallTs}s`);
    }

    // Bitcoin chain commitment is embedded in every AYR block
    const extraData = buildExtraData();

    const attrs = {
      timestamp:             '0x' + ts.toString(16),
      prevRandao:            '0x' + crypto.randomBytes(32).toString('hex'),
      suggestedFeeRecipient: AUTHORITY,
      extraData,  // ← Bitcoin's chain state sealed here
    };
    if (state.engineFcuVer !== 'V1') attrs.withdrawals = [];
    if (state.engineFcuVer === 'V3')  attrs.parentBeaconBlockRoot = '0x' + '00'.repeat(32);

    const fcr = await engineCall(`engine_forkchoiceUpdated${state.engineFcuVer}`, [
      { headBlockHash: state.headHash, safeBlockHash: state.safeHash, finalizedBlockHash: state.finalHash },
      attrs,
    ]);
    if (!fcr?.payloadId) return;
    state.payloadId = fcr.payloadId;
    await new Promise(r => setTimeout(r, 2000));

    const pr = await engineCall(`engine_getPayload${state.enginePayVer}`, [state.payloadId]);
    const ep = pr?.executionPayload || pr;
    if (!ep?.blockHash) return;

    const newNum  = parseInt(ep.blockNumber, 16);
    const newHash = ep.blockHash;

    // Sign block
    const sig = signer.signBlock(newHash);
    if (!sig.sig && !blockSigs.has(newHash)) {
      if (!consensusTick._signWarn) {
        consensusTick._signWarn = true;
        console.log('[SIGN] Running unsigned — set SIGNER_PRIVKEY in .env');
        _tgBuffer('[SIGN] Blocks unsigned — add SIGNER_PRIVKEY to .env');
      }
    }
    blockSigs.set(newHash, sig);

    // Announce new AYR block to AuxPoW system
    // (Bitcoin miners can now mine this hash into their coinbase)
    const challenge = auxpow.setChallenge(newHash, newNum);

    const npResult = await engineCall(
      `engine_newPayload${state.enginePayVer}`,
      state.enginePayVer === 'V3'
        ? [ep, pr?.blobsBundle?.commitments || [], ep.parentBeaconBlockRoot || '0x' + '00'.repeat(32)]
        : [ep]
    );
    if (!npResult?.status || npResult.status === 'INVALID') return;

    state.headHash = state.safeHash = state.finalHash = newHash;
    state.headNumber = state.latestBlock = newNum;
    state.headTimestamp = parseInt(ep.timestamp, 16) || state.headTimestamp;
    state.blockCount++;

    await engineCall(`engine_forkchoiceUpdated${state.engineFcuVer}`, [
      { headBlockHash: state.headHash, safeBlockHash: state.safeHash, finalizedBlockHash: state.finalHash },
      null,
    ]);

    const txCount    = ep.transactions?.length || 0;
    const sigInfo    = sig.sig ? sig.method : 'unsigned';
    const btcInfo    = state.btcTipHeight ? `BTC #${state.btcTipHeight}` : 'BTC absorbing...';
    const commitStr  = state.btcChainCommitment
      ? state.btcChainCommitment.slice(0, 8) + '...'
      : 'pending';

    _record(`[CONSENSUS] Block #${newNum} txs=${txCount} sig=${sigInfo} btc=${btcInfo} commit=${commitStr}`);
    _appendLog(`BLOCK #${newNum} hash=${newHash.slice(0, 14)} txs=${txCount} btc=#${state.btcTipHeight}`);
    console.log(`[CONSENSUS] Block #${newNum} | txs=${txCount} | ${btcInfo} | ${sigInfo}`);

    _tgNow(
      `*Block #${newNum}*\n\`${newHash.slice(0, 22)}...\`\n` +
      `txs=${txCount} | ${btcInfo}\n` +
      `BCP: \`${commitStr}\` | ${sigInfo.replace(/_/g, '\\_')}`
    );

    // Show latest CID 4s after block
    setTimeout(() => {
      if (fs.existsSync(CID_FILE)) {
        const cid = fs.readFileSync(CID_FILE, 'utf8').trim();
        if (cid) _tg(`\`${cid}\``);
      }
    }, 4000);

    // Fee engine
    const { getFeeStats } = require('./relayer');
    if (getFeeStats().feeEngineActive && txCount > 0) {
      if (_getNonce() === null) _syncNonce().then(() => _processFees(newNum)).catch(() => {});
      else _processFees(newNum).catch(() => {});
    }
  } catch (err) {
    console.error(`[CONSENSUS] ${err.message}`);
    _tgBuffer(`[CONSENSUS] ${err.message.slice(0, 150)}`);
  }
}

// ── Outbound network probe ────────────────────────────────────────
async function testOutboundNetwork() {
  const probes = [
    { url: 'https://cloudflare-eth.com',      body: { jsonrpc:'2.0',id:1,method:'eth_blockNumber',params:[] } },
    { url: 'https://ethereum.publicnode.com', body: { jsonrpc:'2.0',id:1,method:'eth_blockNumber',params:[] } },
    { url: 'https://bsc.publicnode.com',      body: { jsonrpc:'2.0',id:1,method:'eth_blockNumber',params:[] } },
  ];
  for (const p of probes) {
    try {
      const res  = await fetch(p.url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(p.body), signal: AbortSignal.timeout(8000) });
      const text = await res.text();
      if (text.trimStart().startsWith('<')) continue;
      const data = JSON.parse(text);
      if (data.result) { console.log(`[NETWORK] Outbound OK — ${p.url.split('/')[2]}`); return true; }
    } catch (e) { console.log(`[NETWORK] ${p.url.split('/')[2]}: ${e.message.slice(0, 60)}`); }
  }
  _tgBuffer('⚠ Cross-chain outbound may be filtered');
  return false;
}

// ── IPFS sync — pin compact header JSON + BTC commitment ─────────
let lastSyncedBlock = 0;

async function ipfsPin(blockNum) {
  try {
    const blk = await rpcCall('eth_getBlockByNumber', ['0x' + blockNum.toString(16), false]);
    if (!blk) return null;
    const record = JSON.stringify({
      number:             blockNum,
      hash:               blk.hash,
      parentHash:         blk.parentHash,
      timestamp:          parseInt(blk.timestamp, 16),
      txCount:            blk.transactions?.length || 0,
      gasUsed:            parseInt(blk.gasUsed, 16),
      gasLimit:           parseInt(blk.gasLimit, 16),
      miner:              blk.miner,
      sig:                blockSigs.get(blk.hash)?.sig?.slice(0, 20) || 'unsigned',
      // Bitcoin Containment Protocol fields
      btcChainCommitment: state.btcChainCommitment?.slice(0, 16) || null,
      btcTipHeight:       state.btcTipHeight,
      btcAbsorbedCount:   state.btcAbsorbedCount,
      containsChainId:    '210078',
    });
    const form = new FormData();
    form.append('file', new Blob([record], { type: 'application/json' }), `block-${blockNum}.json`);
    const res = await fetch('http://127.0.0.1:5001/api/v0/add?quieter=true', {
      method: 'POST', body: form, signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const cid  = data.Hash || data.hash;
    if (!cid) return null;
    fs.writeFileSync(CID_FILE, cid);
    fs.appendFileSync(CID_HIST, `${new Date().toISOString()} block=#${blockNum} btc=#${state.btcTipHeight} CID=${cid}\n`);
    return cid;
  } catch { return null; }
}

function startIpfsSync() {
  setInterval(async () => {
    try {
      const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method:'POST', signal: AbortSignal.timeout(3000) });
      state.ipfsOnline = r.ok;
    } catch { state.ipfsOnline = false; }
  }, 30_000);

  setInterval(async () => {
    if (!state.ipfsOnline || state.latestBlock <= lastSyncedBlock) return;
    lastSyncedBlock = state.latestBlock;
    const cid = await ipfsPin(state.latestBlock);
    if (cid) _tgBuffer(`[SYNC] #${state.latestBlock} BTC:#${state.btcTipHeight} → \`${cid}\``);
  }, 35_000);

  setTimeout(async () => {
    try {
      const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method:'POST', signal: AbortSignal.timeout(3000) });
      state.ipfsOnline = r.ok;
      console.log(`[IPFS] ${state.ipfsOnline ? 'Online ✅' : 'Offline ❌'}`);
    } catch { state.ipfsOnline = false; console.log('[IPFS] Offline ❌'); }
  }, 5000);
}

// ── Boot ──────────────────────────────────────────────────────────
async function initConsensus() {
  console.log('[AETHYR] Consensus engine starting — Bitcoin Containment Protocol active');
  if (signer.isAvailable()) {
    console.log(`[SIGNER] ecdsa-secp256k1 active | pubkey: ${signer.getPublicKey()?.slice(0, 18)}...`);
  } else {
    console.log('[SIGNER] ⚠ No SIGNER_PRIVKEY — blocks will be unsigned');
    _tgBuffer('[SIGNER] ⚠ SIGNER_PRIVKEY not set — blocks unsigned');
  }
  try {
    const latest = await rpcCall('eth_getBlockByNumber', ['latest', false]);
    if (latest?.hash) {
      state.headHash = state.safeHash = state.finalHash = latest.hash;
      state.headNumber = state.latestBlock = parseInt(latest.number, 16);
      state.headTimestamp = parseInt(latest.timestamp, 16) || 0;
      console.log(`[CONSENSUS] Head seeded: #${state.headNumber}`);
      _tg(`AETHYR online\nHead: #${state.headNumber} | PoS+PoA | BTC Containment: active`);
    }
  } catch (e) { console.error('[CONSENSUS] Head init failed:', e.message); }
  setInterval(consensusTick, BLOCK_TIME);
  consensusTick();
}

function startConsensus() {
  state.nodeProc = spawnNode();
  startIpfsSync();
  setTimeout(async () => {
    await testOutboundNetwork();
    await initConsensus();
  }, 8000);
}

// ── Graceful shutdown ─────────────────────────────────────────────
const { saveCursors, saveChainRegistry } = require('./rpc');

async function gracefulShutdown(signal, tgNowFn) {
  if (state.shuttingDown) return;
  state.shuttingDown = true;
  console.log(`[AETHYR] ${signal} — shutting down`);
  tgNowFn(`AETHYR shutting down (${signal})...`);
  saveCursors();
  saveChainRegistry();
  audit('SHUTDOWN', signal);
  await new Promise(r => setTimeout(r, 3000));
  if (state.nodeProc && !state.nodeProc.killed) {
    state.nodeProc.kill('SIGTERM');
    await new Promise(r => state.nodeProc.on('exit', r));
  }
  process.exit(0);
}

module.exports = {
  init, startConsensus, gracefulShutdown,
  onChainCommitmentUpdate, onAuxPoWFound,
  state, validators, blockSigs, spawnNode, ipfsPin,
};
