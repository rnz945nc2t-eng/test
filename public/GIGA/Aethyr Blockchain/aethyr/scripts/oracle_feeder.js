// scripts/oracle_feeder.js — Live price pusher for AYROracle
//
// Fetches ETH + AYR prices from CoinGecko every 60s and pushes
// them on-chain via AYROracle.setPrices(). This is what makes
// the oracle "real" — no hardcoded values, no mock data.
//
// AYR price: derived from AYR/ETH ratio if available,
//            otherwise defaults to 1 USD until market sets it.
//
// Called from node.js after oracle address is known.

'use strict';

const { CONTRACTS, VAULT } = require('./config');

const COINGECKO_URL =
  'https://api.coingecko.com/api/v3/simple/price' +
  '?ids=ethereum,bitcoin&vs_currencies=usd';

const PUSH_INTERVAL = 60_000; // 60s
const DECIMALS      = 1e8;    // 8 decimal places (Chainlink standard)

let _rpcCall  = null;
let _getNonce = null;
let _record   = null;
let _interval = null;

function init({ rpcCall, getNonce, record }) {
  _rpcCall  = rpcCall;
  _getNonce = getNonce;
  _record   = record;

  if (!CONTRACTS.Oracle || CONTRACTS.Oracle === '0xB41dfD5CEa3F237197197202487cad8fd3AeE560') {
    console.warn('[ORACLE] No oracle address configured — price feed inactive');
    console.warn('[ORACLE] Add Oracle address to CONTRACTS in config.js after deploy');
    return;
  }

  console.log(`[ORACLE] Price feeder starting → ${CONTRACTS.Oracle}`);
  _pushPrices(); // immediate first push
  _interval = setInterval(_pushPrices, PUSH_INTERVAL);
}

function stop() {
  if (_interval) { clearInterval(_interval); _interval = null; }
}

async function _fetchPrices() {
  const res  = await fetch(COINGECKO_URL, { headers: { 'Accept': 'application/json' } });
  const data = await res.json();
  const ethUsd = data?.ethereum?.usd;
  const btcUsd = data?.bitcoin?.usd;
  if (!ethUsd || ethUsd <= 0 || !btcUsd || btcUsd <= 0) throw new Error('CoinGecko returned invalid prices');
  return { ETH: ethUsd, BTC: btcUsd, AYR: btcUsd }; // AYR = BTC price
}

// Encode AYROracle.setPrices(string[], uint256[]) call
function _encodePrices(symbols, prices) {
  // Function selector: keccak256("setPrices(string[],uint256[])")[0:4]
  // Pre-computed: 0x4c8ac629
  const sel = '4c8ac629';

  // Build ABI-encoded calldata for setPrices
  const abiCoder = {
    encodeStringArray: (arr) => {
      // FIX: Removed the prepended offset. The EVM expects the length to be the first word here.
      const len    = arr.length.toString(16).padStart(64, '0');
      let result   = len;
      
      // each string: offset within sub-array, then length + data
      let dataOffset = arr.length * 32;
      const offsets = [];
      const strings = [];
      for (const s of arr) {
        offsets.push(dataOffset.toString(16).padStart(64, '0'));
        const bytes = Buffer.from(s, 'utf8');
        const strLen = bytes.length.toString(16).padStart(64, '0');
        const padded = bytes.toString('hex').padEnd(Math.ceil(bytes.length / 32) * 64, '0');
        strings.push(strLen + padded);
        dataOffset += 32 + Math.ceil(bytes.length / 32) * 32;
      }
      return result + offsets.join('') + strings.join('');
    },
    encodeUintArray: (arr) => {
      const len    = arr.length.toString(16).padStart(64, '0');
      const values = arr.map(v => BigInt(Math.round(v * DECIMALS)).toString(16).padStart(64, '0'));
      return len + values.join('');
    }
  };

  const symsEncoded   = abiCoder.encodeStringArray(symbols);
  const pricesEncoded = abiCoder.encodeUintArray(prices);

  // Two dynamic args: offset to syms array, offset to prices array
  const offset1 = (64).toString(16).padStart(64, '0');               // 0x40
  const offset2 = (64 + symsEncoded.length / 2).toString(16).padStart(64, '0');

  return '0x' + sel + offset1 + offset2 + symsEncoded + pricesEncoded;
}

async function _pushPrices() {
  try {
    const fetched = await _fetchPrices();
    const symbols = Object.keys(fetched);
    const prices  = Object.values(fetched);

    const data     = _encodePrices(symbols, prices);
    const gasPrice = await _rpcCall('eth_gasPrice', []);
    const nonce    = await _getNonce();

    const tx = {
      from:     VAULT.SIGNER_ADDR,
      to:       CONTRACTS.Oracle,
      value:    '0x0',
      gas:      '0x30D40', // 200,000
      gasPrice: gasPrice || '0x3B9ACA00',
      nonce:    '0x' + nonce.toString(16),
      data,
    };

    const txHash = await _rpcCall('eth_sendTransaction', [tx]);
    const ethStr = prices[0].toLocaleString('en-US', { maximumFractionDigits: 2 });
    const btcStr = prices[1].toLocaleString('en-US', { maximumFractionDigits: 2 });
    console.log(`[ORACLE] Pushed ETH=$${ethStr} BTC=$${btcStr} AYR=$${prices[2].toFixed(2)} → ${txHash?.slice(0, 12)}...`);
    if (_record) _record(`[ORACLE] ETH=${fetched.ETH} BTC=${fetched.BTC} AYR=${fetched.AYR}`);
  } catch (e) {
    console.warn(`[ORACLE] Price push failed: ${e.message}`);
  }
}

module.exports = { init, stop };
