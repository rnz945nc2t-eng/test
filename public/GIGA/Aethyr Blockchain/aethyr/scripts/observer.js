'use strict';
// ================================================================
// AETHYR ONE — observer.js
// EOA Vault Observer for Native Assets (ETH/BSC/MATIC/etc.)
//
// ARCHITECTURE CHANGE:
// Instead of watching a Smart Contract for BridgeLock events,
// this observer scans full blocks for direct native transfers
// sent to the Authority's Vault Address (EOA).
//
// Polls every 60s, processes up to 50 blocks per tick to avoid
// RPC rate limits, and emits relayMint for confirmed deposits.
// ================================================================
const {
  RPC_POOLS, BRIDGE_CONTRACTS, SAFE_DEPTH,
  rpcState, chainState, chainRpc,
} = require('./rpc');
const { audit } = require('./audit');

let _relayMint = async () => {};
let _record    = () => {};
let _tgNow     = () => {};

function init({ relayMint, record, tgNow }) {
  _relayMint = relayMint;
  _record    = record;
  _tgNow     = tgNow;
}

async function observeChain(chain) {
  const t0 = Date.now();
  try {
    const blockHex = await chainRpc(chain, 'eth_blockNumber');
    const head     = parseInt(blockHex, 16);
    chainState[chain].block   = head;
    chainState[chain].latency = Date.now() - t0;
    chainState[chain].online  = true;

    // In this architecture, BRIDGE_CONTRACTS holds your EOA Vault Address
    const watchAddr = BRIDGE_CONTRACTS[chain]; 
    
    if (watchAddr) {
      const depth     = SAFE_DEPTH[chain] || 32;
      const safeBlock = Math.max(0, head - depth);
      const fromBlock = parseInt(rpcState[chain].lastBlock || '0x0', 16);

      if (fromBlock > 0 && safeBlock > fromBlock) {
        // Limit to 50 blocks per tick to prevent RPC timeouts if node falls behind
        const targetBlock = Math.min(safeBlock, fromBlock + 50);

        for (let b = fromBlock + 1; b <= targetBlock; b++) {
          const blkHex = '0x' + b.toString(16);
          // Fetch full block with transaction objects (true)
          const blk = await chainRpc(chain, 'eth_getBlockByNumber', [blkHex, true]);

          if (blk && blk.transactions) {
            for (const tx of blk.transactions) {
              // Check if transaction is a direct native transfer to the Vault Address
              if (tx.to && tx.to.toLowerCase() === watchAddr.toLowerCase() && tx.value !== '0x0') {
                const evt = {
                  chain,
                  block: b,
                  txHash: tx.hash,
                  sender: tx.from,
                  amount: BigInt(tx.value).toString()
                };
                
                chainState[chain].events++;
                _record(`[VAULT] ${chain} deposit tx=${evt.txHash.slice(0, 14)} amt=${evt.amount}`);
                _tgNow(`🏦 *Vault Deposit — ${chain}*\nFrom: \`${evt.sender.slice(0, 16)}...\`\nAmt: \`${evt.amount} wei\`\nBlock: #${evt.block}`);
                audit('VAULT_DEPOSIT', `chain=${chain} block=${evt.block} amt=${evt.amount}`);
                
                await _relayMint(evt, chain);
              }
            }
          }
        }
        // Update cursor
        rpcState[chain].lastBlock = '0x' + targetBlock.toString(16);
      } else if (fromBlock === 0) {
        // Initialize cursor on first run to avoid scanning from genesis
        rpcState[chain].lastBlock = '0x' + safeBlock.toString(16);
      }
    }
    _record(`[OBS] ${chain} #${head} (${Date.now() - t0}ms)`);
  } catch (err) {
    chainState[chain].errors++;
    chainState[chain].online = false;
    if (!err.message.includes('unavailable')) console.error(`[OBS] ${chain}: ${err.message}`);
  }
}

const { initSolanaObserver, stopSolanaObserver } = require('./solana');

function startObservers() {
  setInterval(() => Object.keys(RPC_POOLS).forEach(observeChain), 60_000);
  setTimeout(() => {
    console.log('[OBS] EOA Vault observers starting...');
    Object.keys(RPC_POOLS).forEach(observeChain);
    initSolanaObserver();
  }, 20_000);
}

module.exports = { init, startObservers, observeChain, stopSolanaObserver };
