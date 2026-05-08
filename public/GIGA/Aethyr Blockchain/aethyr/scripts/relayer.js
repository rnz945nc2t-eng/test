'use strict';
// ================================================================
// AETHYR ONE — relayer.js
// Mint queue (5-min delay), fee engine (50% burn / 50% AYR buyback),
// nonce management.
//
// ARCHITECTURE CHANGE:
//   Bitcoin is no longer wrapped into an ERC-20 token (wBTC removed).
//   Bitcoin UTXOs are native AYR objects via utxo_native.js.
//   relayMint() still handles EVM chain bridges (ETH, BSC, etc.)
//   for their wrapped tokens — Bitcoin is the exception, not the rule.
// ================================================================
const { VAULT, CONTRACTS, AUTHORITY, ZERO_ADDR } = require('./config');
const { audit } = require('./audit');
const { rpcCall } = require('./rpc');

let _tgNow   = () => {};
let _tgBuffer= () => {};
let _record  = () => {};

function init({ tgNow, tgBuffer, record }) {
  _tgNow    = tgNow;
  _tgBuffer = tgBuffer;
  _record   = record;
  loadQueue();
}

// ── Nonce ─────────────────────────────────────────────────────────
let localNonce = null;

async function syncNonce() {
  const r  = await rpcCall('eth_getTransactionCount', [AUTHORITY, 'latest']);
  localNonce = r ? parseInt(r, 16) : 0;
  console.log(`[RELAYER] Nonce synced: ${localNonce}`);
}
function getNonce()   { return localNonce; }
function resetNonce() { localNonce = null; }

// ── ABI encode mint(address,uint256) ──────────────────────────────
function encodeMint(recipient, amountHex) {
  const sel  = '40c10f19';
  const addr = recipient.replace(/^0x/, '').toLowerCase().padStart(64, '0');
  const amt  = amountHex.replace(/^0x/, '').padStart(64, '0');
  return '0x' + sel + addr + amt;
}

// Add a helper to read prices from your Oracle contract
async function getOraclePrice(symbol) {
  const sel = '98d5fdca'; // getPrice(string)
  const offset = (32).toString(16).padStart(64, '0');
  const len = symbol.length.toString(16).padStart(64, '0');
  const str = Buffer.from(symbol, 'utf8').toString('hex').padEnd(64, '0');
  const data = '0x' + sel + offset + len + str;
  
  const res = await rpcCall('eth_call', [{ to: CONTRACTS.Oracle, data }, 'latest']);
  if (!res || res === '0x') return BigInt(0);
  return BigInt(res);
}

// Add the injection function for AYR transfers
function encodeTransfer(recipient, amountHex) {
  const sel  = 'a9059cbb'; // transfer(address,uint256)
  const addr = recipient.replace(/^0x/, '').toLowerCase().padStart(64, '0');
  const amt  = amountHex.replace(/^0x/, '').padStart(64, '0');
  return '0x' + sel + addr + amt;
}

// EVM wrapped tokens — ETH/BSC/etc bridges use these
// Note: BTC is intentionally NOT in this map — Bitcoin UTXOs
// are activated natively via utxo_native.js, not minted as tokens.
const WRAPPED = Object.freeze({
  ETH:    CONTRACTS.wETH,
  BSC:    CONTRACTS.wBNB,
  MATIC:  CONTRACTS.wMATIC,
  ARB:    CONTRACTS.wARB,
  OP:     CONTRACTS.wETH,
  BASE:   CONTRACTS.wETH,
  AVAX:   CONTRACTS.wETH,
  FTM:    CONTRACTS.wETH,
  CELO:   CONTRACTS.wETH,
  CRO:    CONTRACTS.wETH,
  BLAST:  CONTRACTS.wETH,
  LINEA:  CONTRACTS.wETH,
  MANTLE: CONTRACTS.wETH,
  SCROLL: CONTRACTS.wETH,
  ZKSYNC: CONTRACTS.wETH,
  SOL:    CONTRACTS.wSOL,
  // BTC: handled by utxo_native.js — not a wrapped token
});

// ── Persistent mint queue ─────────────────────────────────────────
const mintQueue = [];
let   mintQueueRunning = false;
const QUEUE_FILE = require('path').join(require('./config').BASE_DIR, 'mint-queue.json');
const fs = require('fs');

function saveQueue() {
  try { fs.writeFileSync(QUEUE_FILE, JSON.stringify(mintQueue, null, 2)); } catch {}
}

function loadQueue() {
  try {
    if (!fs.existsSync(QUEUE_FILE)) return;
    const saved = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf8'));
    if (!Array.isArray(saved)) return;
    const now = Date.now();
    let resumed = 0;
    for (const item of saved) {
      if (!item.contract || !item.recipient || !item.amountWei || !item.label) continue;
      if (item.executeAt < now) item.executeAt = now + 10_000;
      mintQueue.push(item);
      resumed++;
    }
    if (resumed > 0) console.log(`[RELAYER] Resumed ${resumed} pending mints ✅`);
  } catch {}
}

async function processMintQueue() {
  if (mintQueueRunning) return;
  mintQueueRunning = true;
  while (mintQueue.length) {
    const item = mintQueue[0];
    if (Date.now() < item.executeAt) break;
    
    // 1. Attempt the injection FIRST
    let hash;
    if (item.type === 'ayr_transfer') {
      hash = await injectAyrTransfer(item.recipient, item.amountWei, item.label);
    } else {
      hash = await injectMint(item.contract, item.recipient, item.amountWei, item.label, item.txHash);
    }
    
    if (hash) {
      // 2. Only remove from queue if successful (or if it was a duplicate)
      mintQueue.shift();
      saveQueue();
    } else {
      // 3. If it failed (RPC down, nonce issue), stop processing and try again next tick
      break;
    }
  }
  mintQueueRunning = false;
}
setInterval(processMintQueue, 5000);

// Dedup guard
const completedMints = new Set();

async function injectMint(toContract, recipient, amountWei, label, txHash) {
  // Use txHash for deduplication. Fallback to timestamp if missing to prevent accidental drops.
  const mintKey = txHash ? `mint-${txHash}` : `${toContract}-${recipient}-${amountWei}-${Date.now()}`;
  
  if (completedMints.has(mintKey)) {
    _record(`[RELAYER] ⚠️ Skipping duplicate: ${label}`);
    return 'duplicate'; // Return truthy so it gets removed from the queue
  }
  
  try {
    if (localNonce === null) await syncNonce();
    const nonce    = '0x' + localNonce.toString(16);
    localNonce++;
    const gasPrice = await rpcCall('eth_gasPrice');
    const data     = encodeMint(recipient, '0x' + BigInt(amountWei).toString(16));
    const tx = {
      from: AUTHORITY, to: toContract, value: '0x0',
      gas: '0x30d40', gasPrice: gasPrice || '0x3B9ACA00', nonce, data,
    };
    const hash = await rpcCall('eth_sendTransaction', [tx]);
    if (!hash) throw new Error('null hash');
    
    _record(`[RELAYER] ✅ ${label} tx=${hash.slice(0, 14)}`);
    _tgNow(`✅ *Mint*\n${label}\nTx: \`${hash.slice(0, 22)}...\``);
    
    completedMints.add(mintKey);
    audit('MINT', `label=${label} tx=${hash.slice(0, 14)}`);
    return hash;
  } catch (e) {
    _record(`[RELAYER] ❌ ${e.message}`);
    _tgBuffer(`[RELAYER] ❌ ${e.message.slice(0, 120)}`);
    if (e.message.includes('nonce')) localNonce = null;
    return null; // Return null on failure so the queue doesn't shift
  }
}

async function injectAyrTransfer(recipient, amountWei, label) {
  const mintKey = `ayr-${recipient}-${amountWei}`;
  if (completedMints.has(mintKey)) {
    _record(`[RELAYER] ⚠️ Skipping duplicate: ${label}`);
    return null;
  }
  try {
    if (localNonce === null) await syncNonce();
    const nonce    = '0x' + localNonce.toString(16);
    localNonce++;
    const gasPrice = await rpcCall('eth_gasPrice');
    const data     = encodeTransfer(recipient, '0x' + BigInt(amountWei).toString(16));
    const tx = {
      from: AUTHORITY, to: CONTRACTS.AYR, value: '0x0',
      gas: '0x30d40', gasPrice: gasPrice || '0x3B9ACA00', nonce, data,
    };
    const hash = await rpcCall('eth_sendTransaction', [tx]);
    if (!hash) throw new Error('null hash');
    _record(`[RELAYER] ✅ ${label} tx=${hash.slice(0, 14)}`);
    _tgNow(`✅ *AYR Transfer*\n${label}\nTx: \`${hash.slice(0, 22)}...\``);
    completedMints.add(mintKey);
    audit('AYR_TRANSFER', `label=${label} tx=${hash.slice(0, 14)}`);
    return hash;
  } catch (e) {
    _record(`[RELAYER] ❌ ${e.message}`);
    _tgBuffer(`[RELAYER] ❌ ${e.message.slice(0, 120)}`);
    if (e.message.includes('nonce')) localNonce = null;
    return null;
  }
}

function queueMint(contract, recipient, amountWei, label, txHash) {
  mintQueue.push({ type: 'mint', contract, recipient, amountWei, label, txHash, executeAt: Date.now() + 300_000 });
  _record(`[RELAYER] Queued mint in 5min: ${label}`);
  saveQueue();
}

function queueAyrTransfer(recipient, amountWei, label) {
  mintQueue.push({ type: 'ayr_transfer', recipient, amountWei, label, executeAt: Date.now() + 300_000 });
  _record(`[RELAYER] Queued AYR transfer in 5min: ${label}`);
  saveQueue();
}

// EVM bridge relay — ETH/BSC/MATIC/etc (NOT Bitcoin)
async function relayMint(evt, chain) {
  if (chain === 'ETH') {
    try {
      const ethPrice = await getOraclePrice('ETH');
      const ayrPrice = await getOraclePrice('AYR');
      if (ethPrice === 0n || ayrPrice === 0n) {
        _record(`[RELAYER] Oracle prices not ready for ETH->AYR swap`);
        return;
      }
      
      const amountEth = BigInt(evt.amount);
      const amountAyr = (amountEth * ethPrice) / ayrPrice;
      
      queueAyrTransfer(evt.sender, amountAyr.toString(), `ETH->AYR swap #${evt.block}`);
    } catch (e) {
      _record(`[RELAYER] Failed to process ETH->AYR swap: ${e.message}`);
    }
    return;
  }

  const c = WRAPPED[chain];
  if (!c) {
    // Bitcoin chain events are handled by utxo_native.js, not here
    if (chain === 'BTC') {
      _record(`[RELAYER] BTC event routed to utxo_native.js — not minting wBTC`);
      return;
    }
    return;
  }
  queueMint(c, evt.sender, evt.amount, `${chain} lock #${evt.block}`, evt.txHash);
}

// ── Fee Engine ────────────────────────────────────────────────────
let feeEngineActive    = false;
let totalFeesCollected = BigInt(0);
let totalAyrBought     = BigInt(0);

async function processFees(blockNum) {
  try {
    const blk = await rpcCall('eth_getBlockByNumber', ['0x' + blockNum.toString(16), true]);
    if (!blk?.transactions?.length) return;
    let totalFeeWei = BigInt(0);
    for (const tx of blk.transactions) {
      const receipt = await rpcCall('eth_getTransactionReceipt', [tx.hash]);
      if (!receipt) continue;
      totalFeeWei += BigInt(parseInt(receipt.gasUsed, 16)) * BigInt(parseInt(tx.gasPrice || '0x0', 16));
    }
    if (totalFeeWei === BigInt(0)) return;
    totalFeesCollected += totalFeeWei;
    const halfFee = totalFeeWei / BigInt(2);
    if (localNonce === null) await syncNonce();
    const gasPrice = await rpcCall('eth_gasPrice');

    // 50% burn
    await rpcCall('eth_sendTransaction', [{
      from: AUTHORITY, to: ZERO_ADDR, value: '0x' + halfFee.toString(16),
      gas: '0x5208', gasPrice: gasPrice || '0x3B9ACA00', nonce: '0x' + (localNonce++).toString(16),
    }]);

    // 50% buyback AYR
    const routerAddr = CONTRACTS.ROUTER || CONTRACTS.SwapRouter;
    if (routerAddr) {
      const buyData = '0xb6f9de95' +
        '0'.repeat(64) +
        '00000000000000000000000000000000000000000000000000000000000000800000000000000000000000' +
        VAULT.COLD_ADDR.replace(/^0x/, '').padStart(40, '0') +
        'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' +
        '0000000000000000000000000000000000000000000000000000000000000002' +
        '000000000000000000000000c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2' +
        '000000000000000000000000' + CONTRACTS.AYR.replace(/^0x/, '');

      const buyHash = await rpcCall('eth_sendTransaction', [{
        from: AUTHORITY, to: routerAddr, value: '0x' + halfFee.toString(16),
        gas: '0x493E0', gasPrice: gasPrice || '0x3B9ACA00', nonce: '0x' + (localNonce++).toString(16),
        data: buyData,
      }]);
      if (buyHash) {
        totalAyrBought += halfFee;
        _record(`[FEE] #${blockNum} fee=${totalFeeWei} buyAYR=${buyHash.slice(0, 14)}`);
        audit('FEE_BUYBACK', `block=${blockNum} fee=${totalFeeWei}`);
      }
    }
  } catch (e) {
    if (!e.message.includes('no transactions') && !e.message.includes('null')) {
      _record(`[FEE] ${e.message.slice(0, 80)}`);
    }
  }
}

function getFeeStats() {
  return { feeEngineActive, totalFeesCollected, totalAyrBought, mintQueueLen: mintQueue.length, localNonce };
}
function setFeeEngine(v) { feeEngineActive = v; }

module.exports = {
  init, syncNonce, getNonce, resetNonce,
  relayMint, queueMint, injectMint,
  processFees, getFeeStats, setFeeEngine,
};
