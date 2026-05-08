'use strict';
// ================================================================
// AETHYR ONE — node.js  CORTEX v4 — Bitcoin Containment Protocol
// Chain 210078 · PoS+PoA · BCP · Self-Evolving
//
// ┌─────────────────────────────────────────────────────────────┐
// │  config.js          — VAULT seal, constants                 │
// │  audit.js           — tamper-evident log + ring buffer      │
// │  rpc.js             — multi-chain RPC pools + Engine API    │
// │  bitcoin_absorber.js— full BTC chain absorption (BCP core)  │
// │  auxpow.js          — merged mining (Bitcoin PoW → AYR)     │
// │  utxo_native.js     — native Bitcoin UTXO bridge (no wrap)  │
// │  relayer.js         — EVM mint queue + fee engine           │
// │  observer.js        — EVM chain lock observers              │
// │  consensus.js       — PoS+PoA + BTC commitment in blocks    │
// │  cortex.js          — evolution engine + sandbox            │
// │  watchdog.js        — autonomous self-repair                │
// │  telegram.js        — bot auth + all /commands              │
// └─────────────────────────────────────────────────────────────┘
//
// Bitcoin Containment Protocol (BCP):
//   Bitcoin's full chain state is absorbed and committed into
//   every AYR block. Bitcoin UTXOs are native AYR objects.
//   Bitcoin miners can merge-mine AYR via AuxPoW at zero cost.
//   AYR contains Bitcoin — Bitcoin is a feature of AYR.
// ================================================================

const fs = require('fs');

const cfg            = require('./scripts/config');
const { record, appendBtorLog } = require('./scripts/audit');
const rpc            = require('./scripts/rpc');
const relayer        = require('./scripts/relayer');
const bitcoinAbsorber= require('./scripts/bitcoin_absorber');
const auxpow         = require('./scripts/auxpow');
const utxoNative     = require('./scripts/utxo_native');
const observer       = require('./scripts/observer');
const consensus      = require('./scripts/consensus');
const cortex         = require('./scripts/cortex');
const watchdog       = require('./scripts/watchdog');
const tg             = require('./scripts/telegram');

// ── Boot banner ──────────────────────────────────────────────────
console.log('');
console.log('  ╔═══════════════════════════════════════════════╗');
console.log('  ║  AETHYR ONE  ·  CORTEX v4                     ║');
console.log('  ║  Chain 210078  ·  Bitcoin Containment Protocol ║');
console.log('  ╚═══════════════════════════════════════════════╝');
console.log(`  Binary    : ${cfg.CLIENT_BIN}`);
console.log(`  Data      : ${cfg.DATA_DIR}`);
console.log(`  RPC       : http://127.0.0.1:8545 (nginx)`);
console.log(`  Engine    : http://127.0.0.1:8551`);
console.log(`  Authority : ${cfg.AUTHORITY}`);
console.log(`  Observers : ${Object.keys(rpc.RPC_POOLS).join(' ')}`);
console.log(`  BCP       : Bitcoin chain absorption ACTIVE`);
console.log(`  AuxPoW    : Merged mining ${cfg.AUXPOW_ENABLED ? 'ENABLED' : 'DISABLED'}`);
console.log(`  UTXOs     : Native Bitcoin UTXO bridge ACTIVE`);
console.log(`  Vault     : ${cfg.VAULT.SIGNER_PRIV ? 'SEALED ✓' : 'no SIGNER_PRIV'}`);
console.log('  ────────────────────────────────────────────────');
console.log('');
try { fs.chmodSync(cfg.ENV_FILE, 0o600); } catch {}

// ── Wire dependencies ─────────────────────────────────────────────
// 1. Relayer (EVM bridge mints)
relayer.init({ tgNow: tg.tgNow, tgBuffer: tg.tgBuffer, record });

// 2. Bitcoin Absorber — wires into consensus for commitment updates
//    and into utxo_native for UTXO verification
bitcoinAbsorber.init({
  onChainCommitmentUpdate: consensus.onChainCommitmentUpdate,
  onAuxPoWFound:           consensus.onAuxPoWFound,
  onUTXOActivation:        async (evt) => { /* handled by utxo_native */ },
  record,
  tgNow: tg.tgNow,
});

// 3. AuxPoW
auxpow.init({ record, tgNow: tg.tgNow });

// 4. UTXO Native bridge
utxoNative.init({ record, tgNow: tg.tgNow });

// 5. EVM observer
observer.init({ relayMint: relayer.relayMint, record, tgNow: tg.tgNow });

// 6. Consensus — now includes BTC commitment in every block
consensus.init({
  tg:          tg.tg,
  tgNow:       tg.tgNow,
  tgBuffer:    tg.tgBuffer,
  record,
  appendBtorLog,
  processFees: relayer.processFees,
  syncNonce:   relayer.syncNonce,
  getNonce:    relayer.getNonce,
});

// 7. Cortex (evolution engine)
cortex.init({ tgNow: tg.tgNow });

// 8. Watchdog
watchdog.init({
  consensusState: consensus.state,
  ipfsPin:        consensus.ipfsPin,
  syncNonce:      relayer.syncNonce,
  tgNow:          tg.tgNow,
  record,
  sandboxExec:    cortex.sandboxExec,
  spawnNode:      consensus.spawnNode,
});

// 9. Telegram bot — includes BCP commands
tg.init({
  consensusState:  consensus.state,
  validators:      consensus.validators,
  blockSigs:       consensus.blockSigs,
  spawnNode:       consensus.spawnNode,
  syncNonce:       relayer.syncNonce,
  getNonce:        relayer.getNonce,
  getFeeStats:     relayer.getFeeStats,
  setFeeEngine:    relayer.setFeeEngine,
  // BCP modules
  btcAbsorber:     bitcoinAbsorber,
  utxoNative:      utxoNative,
  auxpow:          auxpow,
  // Evolution + plugins
  stageEvolution:  cortex.stageEvolution,
  applyEvolution:  cortex.applyEvolution,
  integrateChain:  cortex.integrateChain,
  sandboxExec:     cortex.sandboxExec,
  createPlugin:    cortex.createPlugin,
  deletePlugin:    cortex.deletePlugin,
  listPlugins:     cortex.listPlugins,
  rpcCall:         rpc.rpcCall,
  writeEnvKey:     tg.writeEnvKey,
});

// ── Plugin auto-loader ────────────────────────────────────────────
const PLUGINS_DIR = require('path').join(__dirname, 'scripts', 'plugins');
if (fs.existsSync(PLUGINS_DIR)) {
  const plugins = fs.readdirSync(PLUGINS_DIR).filter(f => f.endsWith('.js'));
  for (const p of plugins) {
    try {
      const plugin = require(require('path').join(PLUGINS_DIR, p));
      if (typeof plugin.init === 'function') {
        plugin.init({
          tg: tg.tg, tgNow: tg.tgNow, tgBuffer: tg.tgBuffer,
          record, rpcCall: rpc.rpcCall,
          chainState: rpc.chainState,
          CONTRACTS:  cfg.CONTRACTS,
          CHAIN_ID:   cfg.CHAIN_ID,
          AUTHORITY:  cfg.AUTHORITY,
          // BCP context available to plugins
          getBtcState:         bitcoinAbsorber.getAbsorptionState,
          getChainCommitment:  bitcoinAbsorber.getChainCommitment,
          getUTXOStats:        utxoNative.getUTXOStats,
          getAuxPoWStats:      auxpow.getAuxPoWStats,
        });
      }
      console.log(`[PLUGIN] Loaded: ${p}`);
    } catch (e) {
      console.error(`[PLUGIN] Failed to load ${p}: ${e.message}`);
    }
  }
}

// ── Start subsystems ──────────────────────────────────────────────
// Order matters: consensus needs BTC state before first block
consensus.startConsensus();
bitcoinAbsorber.startAbsorber();    // BCP: absorb Bitcoin chain
auxpow.startAuxPoW();               // BCP: merged mining
utxoNative.startUTXONative();       // BCP: native UTXO bridge
observer.startObservers();          // EVM chain observers
watchdog.startWatchdog();           // Autonomous self-repair

// ── Graceful shutdown ─────────────────────────────────────────────
process.on('SIGTERM', () => consensus.gracefulShutdown('SIGTERM', tg.tgNow));
process.on('SIGINT',  () => consensus.gracefulShutdown('SIGINT',  tg.tgNow));
process.on('SIGHUP',  () => consensus.gracefulShutdown('SIGHUP',  tg.tgNow));
