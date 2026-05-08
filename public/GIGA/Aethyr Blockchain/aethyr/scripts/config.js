'use strict';
// ================================================================
// AETHYR ONE — config.js
// VAULT SEAL: .env read ONCE at boot, frozen forever.
//
// ARCHITECTURE: Bitcoin Containment Protocol (BCP)
//   AYR does not wrap Bitcoin. AYR CONTAINS Bitcoin.
//   Bitcoin's full chain state is a native subset of AYR's state.
//   Every AYR block commits to Bitcoin's chain head.
//   Bitcoin UTXOs are first-class AYR objects — no wrapping needed.
// ================================================================
require('dotenv').config();
const path = require('path');

const VAULT = Object.freeze({
  TKN:           process.env.TKN?.trim()             || '',
  SIGNER_ADDR:   (process.env.SIGNER_ADDR?.trim()    || '0xe36E1ac26e81F50442B6b66acfD0B575B9936d3b').toLowerCase(),
  SIGNER_PRIV:   process.env.SIGNER_PRIVKEY?.trim()  || '',
  SIGNER_PASS:   process.env.SIGNER_PASS?.trim()     || '',
  AI_KEY:        process.env.AI?.trim()               || '',
  AI_MODEL:      process.env.MODEL?.trim()            || '',
  MY_CHAT_ID:    process.env.MY_CHAT_ID?.trim()       || '',
  BASE_DIR:      process.env.BASE_DIR?.trim()         || '/home/87CF3011/2777-87',
  NODE_BIN:      process.env.NODE_BIN?.trim()         || '',
  BRIDGE_ETH:    process.env.BRIDGE_ETH?.trim()       || '',
  BRIDGE_BSC:    process.env.BRIDGE_BSC?.trim()       || '',
  BRIDGE_MATIC:  process.env.BRIDGE_MATIC?.trim()     || '',
  BRIDGE_ARB:    process.env.BRIDGE_ARB?.trim()       || '',
  BRIDGE_OP:     process.env.BRIDGE_OP?.trim()        || '',
  BRIDGE_BASE:   process.env.BRIDGE_BASE?.trim()      || '',
  BRIDGE_AVAX:   process.env.BRIDGE_AVAX?.trim()      || '',
  BRIDGE_FTM:    process.env.BRIDGE_FTM?.trim()       || '',
  BRIDGE_CELO:   process.env.BRIDGE_CELO?.trim()      || '',
  BRIDGE_CRO:    process.env.BRIDGE_CRO?.trim()       || '',
  BRIDGE_BLAST:  process.env.BRIDGE_BLAST?.trim()     || '',
  BRIDGE_LINEA:  process.env.BRIDGE_LINEA?.trim()     || '',
  BRIDGE_MANTLE: process.env.BRIDGE_MANTLE?.trim()    || '',
  BRIDGE_SCROLL: process.env.BRIDGE_SCROLL?.trim()    || '',
  BRIDGE_ZKSYNC: process.env.BRIDGE_ZKSYNC?.trim()    || '',
  BRIDGE_SOL:    process.env.BRIDGE_SOL?.trim()       || '',
  COLD_ADDR:     process.env.COLD_ADDR?.trim()        || '',
  KEYSTORE_PATH: process.env.KEYSTORE_PATH?.trim()    || '',
});

const CONTRACTS = Object.freeze({
  AYR:          '0x6c35781d6D1B99C5B0e3071E98312245f49Fc91B',
  wETH:         '0xAAC00BcD1668d93E4A24a5B04fde2cF2bdae1582',
  Oracle:       '0xB41dfD5CEa3F237197197202487cad8fd3AeE560',
  SwapRouter:   '0x51B56bd0be45675A42d9C43480fF4cfC4546F3B8',
  AYRStaking:   '0x1aFf0F585A017F0D0c6461Ab9eA604d218DbFA35',
  // BTC is NOT a wrapped ERC-20 — Bitcoin UTXOs are native AYR objects.
  // UTXO_REGISTRY tracks activated Bitcoin UTXOs on-chain.
  UTXO_REGISTRY: '0xfe6C558e05AFD0F23c5744C7000A33d464812DDE',
});

const BASE_DIR    = VAULT.BASE_DIR;
const DATA_DIR    = path.join(BASE_DIR, 'chaindata');
const JWT_FILE    = path.join(DATA_DIR, 'jwtsecret');
const CID_FILE    = path.join(BASE_DIR, 'utorrent.cid');
const CID_HIST    = path.join(BASE_DIR, 'cid-history.txt');
const LOG_FILE    = path.join(BASE_DIR, 'utorrent.dat');
const ENV_FILE    = path.join(BASE_DIR, '.env');
const AUDIT_FILE  = path.join(BASE_DIR, 'audit.log');
const CURSOR_FILE = path.join(BASE_DIR, 'chain-cursors.json');
const CHAIN_REG   = path.join(BASE_DIR, 'chain-registry.json');
const STAGE_FILE  = path.join(BASE_DIR, 'node.staged.js');
const CLIENT_BIN  = VAULT.NODE_BIN || path.join(BASE_DIR, 'ayrnode');

// ── Bitcoin Containment Protocol Constants ───────────────────────
// AYR absorbs Bitcoin's full chain state. These are the anchors.
const BTC_GENESIS_HASH = '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f';
const BTC_CHECKPOINT = Object.freeze({
  height: 880_000,
  hash:   '000000000000000000025b4f8d53a1de3f895c9d36b7d14855e3f95f44ef70db',
});

// How many Bitcoin headers to walk back per verification pass
// Full chain absorption depth — builds trust back to checkpoint
const BTC_ABSORB_HEADER_DEPTH  = 6;
// How often to absorb a new Bitcoin block (~Bitcoin block time)
const BTC_ABSORB_INTERVAL      = 65_000;  // 65s
// Sources for Bitcoin data (2-of-N required for any claim)
const BTC_SOURCES = Object.freeze([
  'https://blockstream.info/api',
  'https://mempool.space/api',
]);
const BTC_SOURCE_THRESHOLD = 2; // Require this many sources to agree

// AuxPoW: Bitcoin miners can merge-mine AYR by including
// AYR block hash in their coinbase transaction.
const AUXPOW_MARKER = Buffer.from('AETHYR_ONE_AYR:', 'utf8');
const AUXPOW_ENABLED = true;

// UTXO activation: how many Bitcoin confirmations before a UTXO
// can be activated on AYR (prevents reorg attacks)
const UTXO_ACTIVATION_CONFIRMATIONS = 6;

// ── Chain constants ───────────────────────────────────────────────
const CHAIN_ID    = '210078';
const BLOCK_TIME  = 30_000;
const AUTHORITY   = VAULT.SIGNER_ADDR;
const ENGINE_URL  = 'http://127.0.0.1:8551/';
const RPC_URL     = 'http://127.0.0.1:8545';
const ZERO_ADDR   = '0x000000000000000000000000000000000000dEaD';

const _PRIV_FRAG = VAULT.SIGNER_PRIV ? VAULT.SIGNER_PRIV.slice(2, 10) : null;
function sanitize(str) {
  if (!str || !_PRIV_FRAG) return str;
  return String(str).includes(_PRIV_FRAG) ? '[REDACTED-KEY]' : str;
}

const ENV_WRITABLE_KEYS = new Set([
  'MY_CHAT_ID',
  'BRIDGE_ETH',  'BRIDGE_BSC',  'BRIDGE_MATIC', 'BRIDGE_ARB', 'BRIDGE_OP',
  'BRIDGE_BASE', 'BRIDGE_AVAX', 'BRIDGE_FTM',   'BRIDGE_CELO','BRIDGE_CRO',
  'BRIDGE_BLAST','BRIDGE_LINEA','BRIDGE_MANTLE', 'BRIDGE_SCROLL','BRIDGE_ZKSYNC','BRIDGE_SOL',
]);

module.exports = {
  VAULT, CONTRACTS,
  BASE_DIR, DATA_DIR, JWT_FILE, CID_FILE, CID_HIST, LOG_FILE,
  ENV_FILE, AUDIT_FILE, CURSOR_FILE, CHAIN_REG, STAGE_FILE, CLIENT_BIN,
  CHAIN_ID, BLOCK_TIME, AUTHORITY, ENGINE_URL, RPC_URL, ZERO_ADDR,
  // Bitcoin Containment
  BTC_GENESIS_HASH, BTC_CHECKPOINT,
  BTC_ABSORB_HEADER_DEPTH, BTC_ABSORB_INTERVAL,
  BTC_SOURCES, BTC_SOURCE_THRESHOLD,
  AUXPOW_MARKER, AUXPOW_ENABLED,
  UTXO_ACTIVATION_CONFIRMATIONS,
  sanitize, ENV_WRITABLE_KEYS,
};
