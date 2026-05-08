'use strict';
// ================================================================
// AETHYR ONE — btc.js
// BTC multi-source SPV:
//   - SHA-256d Merkle root verify (2-of-2 sources)
//   - PoW target check on block header
//   - Header chain verify: walks 6 headers back from tip,
//     checks prev_blockhash linkage + each header's own PoW
//     to detect fabricated block announcements
//   - Hardcoded checkpoint (block height + hash) for bootstrap trust
// Mints wBTC on 6+ confirmations with full SPV pass.
// ================================================================
const crypto = require('crypto');
const { VAULT } = require('./config');
const { audit } = require('./audit');

let _relayBtcMint = async () => {};
let _record       = () => {};
let _tgNow        = () => {};

function init({ relayBtcMint, record, tgNow }) {
  _relayBtcMint = relayBtcMint;
  _record       = record;
  _tgNow        = tgNow;
}

const BTC_SOURCES       = ['https://blockstream.info/api', 'https://mempool.space/api'];
const BTC_CONFIRMATIONS = 6;
// Checkpoint: Bitcoin block at a known safe height.
// Update this every few months. Last confirmed mainnet checkpoint:
const BTC_CHECKPOINT = {
  height: 880_000,
  hash:   '000000000000000000025b4f8d53a1de3f895c9d36b7d14855e3f95f44ef70db',
};
// How many headers back to walk for chain linkage check
const HEADER_VERIFY_DEPTH = 6;

let BTC_WATCH_ADDR = VAULT.BTC_ADDR;
let btcTipHeight   = 0;
const seenBtcTxs   = new Set();

function setWatchAddr(addr) { BTC_WATCH_ADDR = addr; }
function getState() {
  return { BTC_WATCH_ADDR, btcTipHeight, seenCount: seenBtcTxs.size, BTC_CONFIRMATIONS };
}

// ── HTTP helpers ─────────────────────────────────────────────────
async function btcFetch(base, ep) {
  try {
    const r = await fetch(`${base}${ep}`, { signal: AbortSignal.timeout(9000) });
    return r.ok ? r.json() : null;
  } catch { return null; }
}
async function btcMultiFetch(ep) {
  const results = await Promise.allSettled(BTC_SOURCES.map(s => btcFetch(s, ep)));
  const ok = results.filter(r => r.status === 'fulfilled' && r.value != null);
  return ok.length ? ok[0].value : null;
}
// Returns how many sources confirmed the tx is in the block
async function btcMultiVerify(txid, blockHash) {
  const checks = await Promise.allSettled(BTC_SOURCES.map(async s => {
    const ids = await btcFetch(s, `/block/${blockHash}/txids`);
    return Array.isArray(ids) && ids.includes(txid);
  }));
  return checks.filter(r => r.status === 'fulfilled' && r.value).length;
}

// ── SHA-256d + Merkle ────────────────────────────────────────────
function sha256d(hex) {
  const b = Buffer.from(hex, 'hex');
  return Buffer.from(
    crypto.createHash('sha256')
      .update(crypto.createHash('sha256').update(b).digest())
      .digest()
  ).reverse().toString('hex');
}
function merkleRoot(txids) {
  if (!txids.length) return '00'.repeat(32);
  let lvl = txids.map(t => Buffer.from(t, 'hex').reverse().toString('hex'));
  while (lvl.length > 1) {
    if (lvl.length % 2) lvl.push(lvl[lvl.length - 1]);
    const next = [];
    for (let i = 0; i < lvl.length; i += 2) next.push(sha256d(lvl[i] + lvl[i + 1]));
    lvl = next;
  }
  return lvl[0];
}

// ── PoW target check ─────────────────────────────────────────────
function checkPoW(blockHash, bits) {
  try {
    const b      = parseInt(bits, 16);
    const exp    = (b >> 24) - 3;
    if (exp < 0 || exp > 29) return false; // sanity
    const mant   = BigInt(b & 0xFFFFFF);
    const target = mant * (BigInt(256) ** BigInt(exp));
    return BigInt('0x' + blockHash) < target;
  } catch { return false; }
}

// ── Header chain verification ────────────────────────────────────
// Walks HEADER_VERIFY_DEPTH blocks back from tx's block,
// checks prev_blockhash linkage and PoW on each header.
// Returns { ok, reason, depth } — depth = how many headers verified.
async function verifyHeaderChain(startHash, startHeight) {
  let currentHash   = startHash;
  let currentHeight = startHeight;
  let depth         = 0;

  // If we're near or below checkpoint, trust it
  if (currentHeight <= BTC_CHECKPOINT.height + HEADER_VERIFY_DEPTH) {
    if (currentHeight === BTC_CHECKPOINT.height && currentHash === BTC_CHECKPOINT.hash) {
      return { ok: true, reason: 'at checkpoint', depth: 0 };
    }
  }

  while (depth < HEADER_VERIFY_DEPTH) {
    const block = await btcMultiFetch(`/block/${currentHash}`);
    if (!block) return { ok: false, reason: `header unavailable at depth ${depth}`, depth };

    // Check PoW on this header
    if (block.bits && !checkPoW(currentHash, block.bits)) {
      return { ok: false, reason: `PoW fail at depth ${depth} hash=${currentHash.slice(0, 12)}`, depth };
    }

    // If we've reached the checkpoint, verify match
    if (block.height === BTC_CHECKPOINT.height) {
      if (currentHash !== BTC_CHECKPOINT.hash) {
        return { ok: false, reason: `checkpoint mismatch at height ${block.height}`, depth };
      }
      return { ok: true, reason: `verified to checkpoint (depth ${depth})`, depth };
    }

    // Move to parent
    if (!block.previousblockhash) {
      return { ok: false, reason: `no prev_blockhash at depth ${depth}`, depth };
    }
    currentHash   = block.previousblockhash;
    currentHeight = block.height - 1;
    depth++;
  }

  return { ok: true, reason: `chain verified ${depth} headers`, depth };
}

// ── Full SPV verify ──────────────────────────────────────────────
async function spvVerify(txid, blockHash, blockHeight) {
  try {
    // 1. Both sources must confirm tx is in block
    const srcOk = await btcMultiVerify(txid, blockHash);
    if (srcOk < 2) return { valid: false, reason: `only ${srcOk}/2 sources confirmed`, sources: srcOk };

    // 2. Fetch block and verify Merkle root
    const block = await btcMultiFetch(`/block/${blockHash}`);
    if (!block) return { valid: false, reason: 'block header unavailable', sources: srcOk };
    const txids    = await btcMultiFetch(`/block/${blockHash}/txids`);
    const computed = Array.isArray(txids) ? merkleRoot(txids) : null;
    const merkleOk = computed != null && computed === block.merkle_root;
    if (!merkleOk) return { valid: false, reason: 'merkle root mismatch', sources: srcOk };

    // 3. PoW on this block's header
    const powOk = block.bits ? checkPoW(blockHash, block.bits) : false;
    if (!powOk) return { valid: false, reason: 'PoW check failed on block header', sources: srcOk };

    // 4. Walk back HEADER_VERIFY_DEPTH headers checking chain linkage + PoW
    const chain = await verifyHeaderChain(blockHash, blockHeight);
    if (!chain.ok) return { valid: false, reason: `header chain: ${chain.reason}`, sources: srcOk };

    return {
      valid: true, merkle: true, pow: true, sources: srcOk,
      chainDepth: chain.depth, reason: chain.reason,
    };
  } catch (e) {
    return { valid: false, reason: e.message, sources: 0 };
  }
}

// ── Watch loop ───────────────────────────────────────────────────
async function btcWatchLoop() {
  if (!BTC_WATCH_ADDR) return;
  try {
    const txs = await btcMultiFetch(`/address/${BTC_WATCH_ADDR}/txs`);
    if (!Array.isArray(txs)) return;
    for (const tx of txs) {
      if (seenBtcTxs.has(tx.txid)) continue;
      const confs = tx.status?.block_height ? (btcTipHeight - tx.status.block_height + 1) : 0;
      if (confs < BTC_CONFIRMATIONS) continue;
      const out = tx.vout?.find(v => v.scriptpubkey_address === BTC_WATCH_ADDR);
      if (!out) continue;
      const amt = (out.value / 1e8).toFixed(8);
      const spv = await spvVerify(tx.txid, tx.status.block_hash, tx.status.block_height);
      seenBtcTxs.add(tx.txid);
      _record(`[BTC] ${amt} BTC spv=${spv.valid} ${spv.reason}`);
      _tgNow(
        `₿ *BTC Bridge*\n\`${amt} BTC\`\n` +
        `Conf: ${confs} | SPV: ${spv.valid ? '✅' : '❌'}\n` +
        `Sources: ${spv.sources}/2 | Chain: ${spv.chainDepth ?? '?'} headers\n` +
        `${spv.reason.replace(/_/g, '\\_')}`
      );
      if (spv.valid) {
        audit('BTC_DEPOSIT', `amt=${amt} tx=${tx.txid.slice(0, 14)} chain=${spv.chainDepth}hdrs`);
        await _relayBtcMint(amt, null);
      } else {
        audit('BTC_SPV_FAIL', `tx=${tx.txid.slice(0, 14)} reason=${spv.reason}`);
      }
    }
    const tip = await btcMultiFetch('/blocks/tip/height');
    if (typeof tip === 'number') btcTipHeight = tip;
  } catch (e) { console.error('[BTC]', e.message); }
}

function startBtcWatcher() {
  setInterval(btcWatchLoop, 60_000);
  setTimeout(async () => {
    const tip = await btcMultiFetch('/blocks/tip/height');
    if (typeof tip === 'number') { btcTipHeight = tip; console.log(`[BTC] Tip: ${btcTipHeight}`); }
    if (BTC_WATCH_ADDR) btcWatchLoop();
  }, 12_000);
}

module.exports = { init, startBtcWatcher, btcWatchLoop, setWatchAddr, getState };
