'use strict';
// ================================================================
// AETHYR ONE — signer.js
// Key loaded from ENCRYPTED KEYSTORE — raw key never in .env.
// VAULT.SIGNER_PRIV kept as fallback if keystore not configured.
// ================================================================
const crypto = require('crypto');
const fs     = require('fs');
const { VAULT, CHAIN_ID } = require('./config');

const DOMAIN_PREFIX = Buffer.from(`\x19AETHYR-${CHAIN_ID} Block:\n`, 'utf8');

function buildPkcs8Der(rawHex) {
  const raw = Buffer.from(rawHex.replace(/^0x/, ''), 'hex');
  if (raw.length !== 32) throw new Error(`[SIGNER] Key must be 32 bytes, got ${raw.length}`);
  const ecVersion  = Buffer.from([0x02, 0x01, 0x01]);
  const ecPrivOctet= Buffer.concat([Buffer.from([0x04, 0x20]), raw]);
  const secp256k1  = Buffer.from([0xa0, 0x07, 0x06, 0x05, 0x2b, 0x81, 0x04, 0x00, 0x0a]);
  const ecBody     = Buffer.concat([ecVersion, ecPrivOctet, secp256k1]);
  const ecSeq      = Buffer.concat([Buffer.from([0x30, ecBody.length]), ecBody]);
  const algBody    = Buffer.from([
    0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01,
    0x06, 0x05, 0x2b, 0x81, 0x04, 0x00, 0x0a,
  ]);
  const algSeq     = Buffer.concat([Buffer.from([0x30, algBody.length]), algBody]);
  const pkcs8Ver   = Buffer.from([0x02, 0x01, 0x00]);
  const privKeyOs  = Buffer.concat([Buffer.from([0x04, ecSeq.length]), ecSeq]);
  const pkcs8Body  = Buffer.concat([pkcs8Ver, algSeq, privKeyOs]);
  return Buffer.concat([Buffer.from([0x30, pkcs8Body.length]), pkcs8Body]);
}

let _privateKey   = null;
let _publicKeyHex = null;
let _rawKeyHex    = null;
let _available    = false;

async function _loadKey() {
  try {
    let rawHex = null;

    // ── Priority 1: Encrypted keystore ──────────────────────────
    if (VAULT.KEYSTORE_PATH && VAULT.SIGNER_PASS) {
      const ksJson = fs.readFileSync(VAULT.KEYSTORE_PATH, 'utf8');
      const { ethers } = require('ethers');
      const wallet = await ethers.Wallet.fromEncryptedJson(ksJson, VAULT.SIGNER_PASS);
      rawHex = wallet.privateKey;
      console.log('[SIGNER] Key loaded from encrypted keystore ✅');

    // ── Priority 2: Raw key fallback (legacy) ────────────────────
    } else if (VAULT.SIGNER_PRIV) {
      rawHex = VAULT.SIGNER_PRIV;
      console.warn('[SIGNER] ⚠️  Using raw key from .env — migrate to keystore!');
    } else {
      console.error('[SIGNER] No key source configured.');
      return;
    }

    const der  = buildPkcs8Der(rawHex);
    _privateKey = crypto.createPrivateKey({ key: der, format: 'der', type: 'pkcs8' });
    _rawKeyHex  = rawHex; // kept in memory only, never written anywhere
    const pubDer = crypto.createPublicKey(_privateKey).export({ format: 'der', type: 'spki' });
    const uncompressed = pubDer.slice(-65);
    const x = uncompressed.slice(1, 33);
    const y = uncompressed.slice(33, 65);
    const prefix = (y[31] & 1) ? 0x03 : 0x02;
    _publicKeyHex = '0x' + Buffer.concat([Buffer.from([prefix]), x]).toString('hex');
    _available = true;
    console.log(`[SIGNER] secp256k1 key ready — pubkey: ${_publicKeyHex.slice(0, 18)}...`);
  } catch (e) {
    console.error(`[SIGNER] Key load failed: ${e.message}`);
  }
}

// Load key at startup (async — signing unavailable for ~100ms during decrypt)
_loadKey();

function signBlock(blockHash) {
  if (!_available || !_privateKey) {
    return { sig: null, method: 'unsigned', pubkey: null };
  }
  try {
    const hashBytes = Buffer.from(blockHash.replace(/^0x/, ''), 'hex');
    const message   = Buffer.concat([DOMAIN_PREFIX, hashBytes]);
    const sigDer = crypto.sign('sha256', message, _privateKey);
    return {
      sig:    '0x' + sigDer.toString('hex'),
      method: 'ecdsa-secp256k1',
      pubkey: _publicKeyHex,
    };
  } catch (e) {
    console.error(`[SIGNER] Sign failed: ${e.message}`);
    return { sig: null, method: 'unsigned', pubkey: null };
  }
}

function verifyBlock(blockHash, sigHex, pubkeyHex) {
  try {
    const sigDer    = Buffer.from(sigHex.replace(/^0x/, ''), 'hex');
    const hashBytes = Buffer.from(blockHash.replace(/^0x/, ''), 'hex');
    const message   = Buffer.concat([DOMAIN_PREFIX, hashBytes]);
    const compressed = Buffer.from(pubkeyHex.replace(/^0x/, ''), 'hex');
    const spkiAlg = Buffer.from([
      0x30, 0x10,
      0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01,
      0x06, 0x05, 0x2b, 0x81, 0x04, 0x00, 0x0a,
    ]);
    const bitString = Buffer.concat([Buffer.from([0x03, compressed.length + 1, 0x00]), compressed]);
    const spkiBody  = Buffer.concat([spkiAlg, bitString]);
    const spki      = Buffer.concat([Buffer.from([0x30, spkiBody.length]), spkiBody]);
    const pubKey    = crypto.createPublicKey({ key: spki, format: 'der', type: 'spki' });
    return crypto.verify('sha256', message, pubKey, sigDer);
  } catch { return false; }
}

function auditStamp(body) {
  const key = _rawKeyHex
    ? Buffer.from(_rawKeyHex.replace(/^0x/, ''), 'hex')
    : 'aethyr-audit';
  return crypto.createHmac('sha256', key).update(body).digest('hex').slice(0, 16);
}

function getPublicKey() { return _publicKeyHex; }
function isAvailable()  { return _available; }

module.exports = { signBlock, verifyBlock, auditStamp, getPublicKey, isAvailable };
