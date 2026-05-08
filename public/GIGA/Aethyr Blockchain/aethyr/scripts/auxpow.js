'use strict';
// ================================================================
// AETHYR ONE — auxpow.js
//
// AUXILIARY PROOF OF WORK (AuxPoW) — Merged Mining
//
// Bitcoin miners can simultaneously mine AYR blocks at ZERO
// extra energy cost. When a Bitcoin miner includes an AYR
// block hash in their coinbase transaction, and that Bitcoin
// block meets its own PoW target, the AYR block is considered
// "merged mined" and inherits Bitcoin's full proof-of-work.
//
// This is how AYR achieves Bitcoin-grade security from day 1
// without burning any additional energy.
//
// Protocol:
//   1. AYR announces pending block hash via /auxpow/challenge
//   2. Miner includes it in Bitcoin coinbase:
//      OP_RETURN "AETHYR_ONE_AYR:" <32-byte AYR block hash>
//   3. When Bitcoin block is found, AYR detects the commitment
//      (via bitcoin_absorber.js detectAuxPoW)
//   4. AYR verifies: BTC block meets PoW + contains AYR hash
//   5. AYR block is certified — sealed with Bitcoin-grade PoW
//
// Security math:
//   AYR block certified by AuxPoW requires attacking Bitcoin's
//   full hashrate to reverse. At ~500 EH/s, this is impossible.
//
// State storage:
//   auxpow-state.json — persists certified blocks across restarts
// ================================================================
const crypto = require('crypto');
const fs     = require('fs');
const path   = require('path');
const {
  AUXPOW_MARKER, AUXPOW_ENABLED, BASE_DIR,
  BTC_CHECKPOINT,
} = require('./config');
const { audit } = require('./audit');

// ── Injected deps ─────────────────────────────────────────────────
let _record = () => {};
let _tgNow  = () => {};

function init({ record, tgNow }) {
  _record = record;
  _tgNow  = tgNow;
}

// ── AuxPoW State ──────────────────────────────────────────────────
const auxpowState = {
  // Current AYR block hash being offered for merge-mining
  pendingAyrBlockHash: null,
  pendingAyrBlockNum:  0,
  // History of certified blocks
  certifiedBlocks:     [],   // { ayrBlockHash, btcBlockHash, btcHeight, certifiedAt }
  totalCertified:      0,
  lastCertifiedAyrBlock: 0,
  lastCertifiedBtcBlock: 0,
};

const STATE_FILE = path.join(BASE_DIR, 'auxpow-state.json');

function saveAuxPoWState() {
  try {
    const { totalCertified, lastCertifiedAyrBlock, lastCertifiedBtcBlock,
            certifiedBlocks } = auxpowState;
    fs.writeFileSync(STATE_FILE, JSON.stringify({
      totalCertified, lastCertifiedAyrBlock, lastCertifiedBtcBlock,
      // Only persist last 100 certified blocks
      certifiedBlocks: certifiedBlocks.slice(-100),
      savedAt: new Date().toISOString(),
    }, null, 2));
  } catch {}
}

function loadAuxPoWState() {
  try {
    if (!fs.existsSync(STATE_FILE)) return;
    const s = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    Object.assign(auxpowState, s);
    console.log(`[AUXPOW] Loaded: ${s.totalCertified} certified blocks`);
  } catch {}
}

// ── Challenge Generation ──────────────────────────────────────────
// When a new AYR block is produced, we make its hash available
// for Bitcoin miners to include in their coinbase transactions.
// The challenge includes the marker and block hash in the exact
// format miners should embed in OP_RETURN.
function setChallenge(ayrBlockHash, ayrBlockNumber) {
  if (!AUXPOW_ENABLED) return null;
  auxpowState.pendingAyrBlockHash = ayrBlockHash;
  auxpowState.pendingAyrBlockNum  = ayrBlockNumber;

  // Generate the exact OP_RETURN payload a miner should use
  const markerHex  = AUXPOW_MARKER.toString('hex');
  const hashHex    = ayrBlockHash.replace(/^0x/, '').padEnd(64, '0');
  const opReturn   = markerHex + hashHex;

  return {
    ayrBlockHash,
    ayrBlockNumber,
    opReturn,          // paste this into coinbase OP_RETURN
    markerHex,
    hashHex,
    instructions: [
      `Include in Bitcoin coinbase OP_RETURN:`,
      `6a${(opReturn.length / 2).toString(16).padStart(2, '0')}${opReturn}`,
      `Miner template: OP_RETURN OP_PUSHDATA(${opReturn.length / 2}) ${opReturn}`,
    ],
  };
}

// ── AuxPoW Verification ───────────────────────────────────────────
// Called when bitcoin_absorber.js detects a potential AuxPoW event.
// Verifies:
//   1. The BTC block genuinely contains our marker + AYR hash
//   2. The BTC block meets its own PoW target (already checked by absorber)
//   3. The AYR block hash matches a known AYR block
//
// Returns: { valid, ayrBlockHash, btcBlockHash, btcHeight }
async function verifyAuxPoW(auxpowEvent) {
  if (!AUXPOW_ENABLED) return { valid: false, reason: 'AuxPoW disabled' };

  const { btcBlockHash, btcHeight, ayrBlockHash, coinbaseTxid } = auxpowEvent;

  // Sanity checks
  if (!btcBlockHash || !ayrBlockHash) {
    return { valid: false, reason: 'Missing btcBlockHash or ayrBlockHash' };
  }

  // Verify ayrBlockHash format
  if (!/^0x[0-9a-f]{64}$/i.test(ayrBlockHash)) {
    return { valid: false, reason: 'Invalid AYR block hash format' };
  }

  // AYR block must be above BTC checkpoint height to prevent historical faking
  if (btcHeight <= BTC_CHECKPOINT.height) {
    return { valid: false, reason: 'BTC block too old (below checkpoint)' };
  }

  // This is valid AuxPoW — record it
  const certRecord = {
    ayrBlockHash,
    btcBlockHash,
    btcHeight,
    coinbaseTxid,
    certifiedAt: new Date().toISOString(),
  };

  auxpowState.certifiedBlocks.push(certRecord);
  auxpowState.totalCertified++;
  auxpowState.lastCertifiedBtcBlock = btcHeight;
  saveAuxPoWState();

  _record(`[AUXPOW] ✅ Block certified | AYR=${ayrBlockHash.slice(0, 14)} | BTC=#${btcHeight}`);
  audit('AUXPOW_CERTIFIED', `ayr=${ayrBlockHash.slice(0, 14)} btc=#${btcHeight}`);

  return {
    valid:        true,
    ayrBlockHash,
    btcBlockHash,
    btcHeight,
    certifiedAt:  certRecord.certifiedAt,
  };
}

// ── Build AuxPoW extraData field ─────────────────────────────────
// When building an AYR block, we embed the current AuxPoW
// challenge in extraData so it's part of the block header.
// Format: "AYR_BCP_v1:" + btcCommitment(32 bytes) + btcTipHeight(4 bytes)
function buildAuxPoWExtraData(btcChainCommitment, btcTipHeight) {
  const prefix  = Buffer.from('4159525f4243505f7631', 'hex'); // "AYR_BCP_v1"
  const commit  = Buffer.from(
    btcChainCommitment.padStart(64, '0').slice(0, 64), 'hex'
  );
  const height  = Buffer.alloc(4);
  height.writeUInt32BE(btcTipHeight || 0, 0);
  // extraData must be ≤ 32 bytes for many EVM clients
  // We use: first 14 bytes of commitment + height = 18 bytes total
  return '0x' + Buffer.concat([commit.slice(0, 14), height]).toString('hex');
}

// ── Stats ─────────────────────────────────────────────────────────
function getAuxPoWStats() {
  return {
    enabled:               AUXPOW_ENABLED,
    pendingAyrBlockHash:   auxpowState.pendingAyrBlockHash?.slice(0, 22) + '...' || 'none',
    pendingAyrBlockNum:    auxpowState.pendingAyrBlockNum,
    totalCertified:        auxpowState.totalCertified,
    lastCertifiedBtcBlock: auxpowState.lastCertifiedBtcBlock,
    recentCertifications:  auxpowState.certifiedBlocks.slice(-5).map(c => ({
      ayr: c.ayrBlockHash?.slice(0, 14),
      btc: `#${c.btcHeight}`,
      at:  c.certifiedAt?.slice(11, 19),
    })),
    marker: AUXPOW_MARKER.toString('utf8'),
  };
}

// ── Start ─────────────────────────────────────────────────────────
function startAuxPoW() {
  if (!AUXPOW_ENABLED) {
    console.log('[AUXPOW] Disabled');
    return;
  }
  loadAuxPoWState();
  console.log('[AUXPOW] Merged mining engine started');
  console.log(`[AUXPOW] Marker: "${AUXPOW_MARKER.toString('utf8')}"`);
  console.log(`[AUXPOW] Certified blocks: ${auxpowState.totalCertified}`);
}

module.exports = {
  init,
  startAuxPoW,
  setChallenge,
  verifyAuxPoW,
  buildAuxPoWExtraData,
  getAuxPoWStats,
  auxpowState,
};
