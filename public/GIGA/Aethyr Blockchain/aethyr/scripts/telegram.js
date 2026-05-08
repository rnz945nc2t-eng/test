'use strict';
// ================================================================
// AETHYR ONE — telegram.js
// Bot auth, rate-limited message queue, all /commands.
//
// NEW COMMANDS (Bitcoin Containment Protocol):
//   /btc        — Bitcoin absorption state + commitment
//   /absorption — Full BCP absorption metrics
//   /utxos      — Native UTXO registry stats
//   /auxpow     — Merged mining stats
//   /containment— Full containment proof
//   /activate   — Activate a Bitcoin UTXO on AYR
// ================================================================
const fs = require('fs');
const TelegramBot = require('node-telegram-bot-api');
const {
  VAULT, AUTHORITY, CHAIN_ID,
  BASE_DIR, AUDIT_FILE, CID_FILE, CID_HIST, ENV_FILE,
  ENV_WRITABLE_KEYS, sanitize,
} = require('./config');
const rpc = require('./rpc');
const { audit, recentLogs } = require('./audit');
const {
  RPC_POOLS, rpcState, chainState,
  BRIDGE_CONTRACTS, saveCursors, saveChainRegistry,
} = require('./rpc');

if (!VAULT.TKN) { console.error('[BOOT] TKN missing in .env'); process.exit(1); }
const bot = new TelegramBot(VAULT.TKN, { polling: true });

let activeChatId = VAULT.MY_CHAT_ID || null;

// Injected deps
let _cs             = null;
let _validators     = null;
let _blockSigs      = null;
let _spawnNode      = null;
let _syncNonce      = null;
let _getNonce       = null;
let _getFeeStats    = null;
let _setFeeEngine   = null;
let _btcAbsorber    = null; // bitcoin_absorber.js
let _utxoNative     = null; // utxo_native.js
let _auxpow         = null; // auxpow.js
let _stageEvolution = null;
let _applyEvolution = null;
let _integrateChain = null;
let _sandboxExec    = null;
let _rpcCall        = null;
let _createPlugin   = null;
let _deletePlugin   = null;
let _listPlugins    = null;

function init(deps) {
  _cs             = deps.consensusState;
  _validators     = deps.validators;
  _blockSigs      = deps.blockSigs;
  _spawnNode      = deps.spawnNode;
  _syncNonce      = deps.syncNonce;
  _getNonce       = deps.getNonce;
  _getFeeStats    = deps.getFeeStats;
  _setFeeEngine   = deps.setFeeEngine;
  _btcAbsorber    = deps.btcAbsorber;
  _utxoNative     = deps.utxoNative;
  _auxpow         = deps.auxpow;
  _stageEvolution = deps.stageEvolution;
  _applyEvolution = deps.applyEvolution;
  _integrateChain = deps.integrateChain;
  _sandboxExec    = deps.sandboxExec;
  _rpcCall        = deps.rpcCall;
  _createPlugin   = deps.createPlugin;
  _deletePlugin   = deps.deletePlugin;
  _listPlugins    = deps.listPlugins;
}

// ── ENV writer ────────────────────────────────────────────────────
function writeEnvKey(key, value) {
  if (!ENV_WRITABLE_KEYS.has(key)) { audit('ENV_BLOCKED', `key=${key}`); return false; }
  try {
    let env = fs.existsSync(ENV_FILE) ? fs.readFileSync(ENV_FILE, 'utf8') : '';
    env = env.includes(`${key}=`)
      ? env.replace(new RegExp(`${key}=.*`), `${key}=${value}`)
      : env + `\n${key}=${value}\n`;
    fs.writeFileSync(ENV_FILE, env);
    audit('ENV_WRITE', `key=${key}`);
    return true;
  } catch (e) { console.error('[ENV]', e.message); return false; }
}

// ── Rate-limited message queue ────────────────────────────────────
const tgQueue     = [];
let tgSending     = false;
let tgSentCount   = 0;
let tgWindowStart = Date.now();
const TG_RATE_LIMIT     = 20;
const TG_RATE_WINDOW_MS = 60_000;

function _rateLimitOk() {
  const now = Date.now();
  if (now - tgWindowStart >= TG_RATE_WINDOW_MS) { tgWindowStart = now; tgSentCount = 0; }
  return tgSentCount < TG_RATE_LIMIT;
}

function tgFlush() {
  if (tgSending || !tgQueue.length || !activeChatId) return;
  if (!_rateLimitOk()) {
    setTimeout(tgFlush, TG_RATE_WINDOW_MS - (Date.now() - tgWindowStart) + 100);
    return;
  }
  tgSending = true;
  const msg = sanitize(tgQueue.shift());
  tgSentCount++;
  bot.sendMessage(activeChatId, msg, { parse_mode: 'Markdown' })
    .catch(e => console.error('[TG]', e.message))
    .finally(() => { tgSending = false; setTimeout(tgFlush, 350); });
}

function tg(msg)    { tgQueue.push(msg);    tgFlush(); }
function tgNow(msg) { tgQueue.unshift(msg); tgFlush(); }

const logBuffer = [];
const logSeen   = new Set();
function tgBuffer(line) {
  const safe = sanitize(line);
  if (logSeen.has(safe)) return;
  logSeen.add(safe);
  logBuffer.push(safe);
  if (logBuffer.length > 50) logBuffer.splice(10, logBuffer.length - 30);
}
setInterval(() => {
  logSeen.clear();
  if (!logBuffer.length || !activeChatId) return;
  tg('```\n' + logBuffer.splice(0, 10).join('\n') + '\n```');
}, 8000);

// ── Auth ──────────────────────────────────────────────────────────
function saveChatId(id) {
  if (activeChatId) return;
  activeChatId = String(id);
  writeEnvKey('MY_CHAT_ID', activeChatId);
  console.log(`[AUTH] Owner chat ID locked: ${activeChatId}`);
  audit('OWNER_LOCKED', `chatId=${activeChatId}`);
}

bot.on('message', msg => {
  const incomingId = String(msg.chat.id);
  if (!activeChatId) { saveChatId(incomingId); return; }
  if (incomingId !== String(activeChatId)) {
    audit('AUTH_REJECT', `chat=${incomingId} user=${msg.from?.username || '?'}`);
  }
});

const _origOnText = bot.onText.bind(bot);
bot.onText = function(regexp, cb) {
  _origOnText(regexp, (msg, match) => {
    if (!activeChatId || String(msg.chat.id) !== String(activeChatId)) {
      audit('CMD_BLOCKED', `chat=${msg.chat.id} cmd=${msg.text?.slice(0, 40)}`);
      return;
    }
    cb(msg, match);
  });
};
function isOwner(msg) { return String(msg.chat.id) === String(activeChatId); }

// ── Help ──────────────────────────────────────────────────────────
bot.onText(/\/start|\/help/, msg => {
  if (!activeChatId) saveChatId(msg.chat.id);
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id,
    `*AETHYR ONE — Bitcoin Containment Protocol*\nChain ${CHAIN_ID}\n\n` +
    `*Chain* /status · /block · /logs · /chains · /validators\n` +
    `*Bitcoin* /btc · /absorption · /containment · /auxpow\n` +
    `*UTXOs* /utxos · /activate\n` +
    `*Bridge* /setbridge · /cid · /cidlog\n` +
    `*Economy* /fees · /feeon · /feeoff · /economy\n` +
    `*Evolution* /evolve · /confirm · /rollback · /audit\n` +
    `*Network* /integrate · /repair · /rpcstatus · /rpcrefresh\n` +
    `*Security* /vault · /auth · /disk · /memory\n` +
    `*AI* /ask · /diagnose · /report · /expand`,
    { parse_mode: 'Markdown' }
  );
});

// ── Status ────────────────────────────────────────────────────────
bot.onText(/\/status/, msg => {
  if (!isOwner(msg)) return;
  const h = Math.floor(process.uptime() / 3600), m = Math.floor((process.uptime() % 3600) / 60);
  const fees    = _getFeeStats?.() || {};
  const btcS    = _btcAbsorber?.absorptionState || {};
  const { isAvailable } = require('./signer');
  bot.sendMessage(msg.chat.id,
    `*AETHYR Status — BCP*\n` +
    `Node: ${_cs?.nodeProc && !_cs.nodeProc.killed ? '✅' : '❌'}\n` +
    `Block: #${_cs?.latestBlock || 0} (${_cs?.blockCount || 0} sealed)\n` +
    `Engine: ${_cs?.engineFcuVer || '?'} | IPFS: ${_cs?.ipfsOnline ? '✅' : '❌'}\n` +
    `Signer: ${isAvailable() ? '✅ ecdsa-secp256k1' : '⚠ unsigned'}\n` +
    `Fee: ${fees.feeEngineActive ? '✅' : '⭕'}\n` +
    `━━ Bitcoin Containment ━━\n` +
    `BTC Tip: #${btcS.btcTipHeight || 0}\n` +
    `Absorbed: ${btcS.absorbedCount || 0} blocks\n` +
    `Commitment: \`${(btcS.chainCommitment || '').slice(0, 12)}...\`\n` +
    `Chains: ${Object.keys(RPC_POOLS).length} | Uptime: ${h}h ${m}m\n` +
    `Authority: \`${AUTHORITY.slice(0, 16)}...\``,
    { parse_mode: 'Markdown' }
  );
});

// ── Block ─────────────────────────────────────────────────────────
bot.onText(/\/block/, async msg => {
  if (!isOwner(msg)) return;
  const bn  = await _rpcCall('eth_blockNumber');
  const num = bn ? parseInt(bn, 16) : (_cs?.latestBlock || 0);
  const blk = bn ? await _rpcCall('eth_getBlockByNumber', [bn, false]) : null;
  const sig = blk?.hash ? _blockSigs?.get(blk.hash) : null;
  const btcS = _btcAbsorber?.absorptionState || {};
  bot.sendMessage(msg.chat.id,
    `*Block #${num}*\nHash: \`${(blk?.hash || _cs?.headHash || '0x0').slice(0, 22)}...\`\n` +
    `Txs: ${blk?.transactions?.length || 0} | Gas: ${blk ? parseInt(blk.gasUsed, 16).toLocaleString() : 0}\n` +
    `Sig: ${sig?.sig ? sig.method : 'unsigned'}\n` +
    `BTC Sealed: #${btcS.btcTipHeight || '?'} | Commit: \`${(btcS.chainCommitment || '').slice(0, 10)}...\``,
    { parse_mode: 'Markdown' }
  );
});

// ── Bitcoin Absorption Status ─────────────────────────────────────
bot.onText(/\/btc/, msg => {
  if (!isOwner(msg)) return;
  const s = _btcAbsorber?.absorptionState || {};
  bot.sendMessage(msg.chat.id,
    `*Bitcoin Absorption State*\n` +
    `Tip Height: #${s.btcTipHeight || 0}\n` +
    `Tip Hash: \`${(s.btcTipHash || 'none').slice(0, 18)}...\`\n` +
    `Absorbed Blocks: ${s.absorbedCount || 0}\n` +
    `Failed: ${s.failedCount || 0}\n` +
    `Verified Depth: ${s.verifiedDepth || 0} headers\n` +
    `Sources Online: ${s.sourcesOnline || 0}/2\n` +
    `Chain Commitment:\n\`${s.chainCommitment || 'pending'}\`\n` +
    `Last AuxPoW BTC: ${s.lastAuxPoWBtcBlock ? `#${s.lastAuxPoWBtcBlock}` : 'none'}`,
    { parse_mode: 'Markdown' }
  );
});

// ── Full absorption metrics ───────────────────────────────────────
bot.onText(/\/absorption/, msg => {
  if (!isOwner(msg)) return;
  const s = _btcAbsorber?.absorptionState || {};
  const lastAbsorb = s.lastAbsorb ? new Date(s.lastAbsorb).toISOString().slice(11, 19) + ' UTC' : 'never';
  bot.sendMessage(msg.chat.id,
    `*BCP Absorption Metrics*\n` +
    `━━ Chain Coverage ━━\n` +
    `Checkpoint: #${require('./config').BTC_CHECKPOINT.height}\n` +
    `Current Tip: #${s.btcTipHeight || 0}\n` +
    `Coverage: ${s.btcTipHeight ? (s.btcTipHeight - require('./config').BTC_CHECKPOINT.height).toLocaleString() : 0} blocks above checkpoint\n` +
    `━━ Verification ━━\n` +
    `Absorbed: ${s.absorbedCount || 0}\n` +
    `Failed: ${s.failedCount || 0}\n` +
    `Verified Depth: ${s.verifiedDepth || 0} consecutive headers\n` +
    `Sources: ${s.sourcesOnline || 0}/2 online\n` +
    `Last Absorb: ${lastAbsorb}\n` +
    `━━ Commitment ━━\n` +
    `\`${s.chainCommitment || 'pending'}\`\n` +
    `Sealed in AYR block: #${_cs?.latestBlock || 0}`,
    { parse_mode: 'Markdown' }
  );
});

// ── Containment Proof ─────────────────────────────────────────────
bot.onText(/\/containment/, async msg => {
  if (!isOwner(msg)) return;
  const proof = _btcAbsorber
    ? require('./bitcoin_absorber').generateContainmentProof(
        _cs?.latestBlock || 0,
        _cs?.headHash || '0x0'
      )
    : null;

  if (!proof) {
    bot.sendMessage(msg.chat.id, '⏳ Containment proof not ready — BTC absorber still syncing');
    return;
  }

  bot.sendMessage(msg.chat.id,
    `*Containment Proof*\n` +
    `━━━━━━━━━━━━━━━━━━\n` +
    `AYR Chain: \`${proof.ayrChainId}\`\n` +
    `AYR Block: #${proof.ayrBlock}\n` +
    `BTC Tip: #${proof.btcTipHeight}\n` +
    `BTC Hash: \`${(proof.btcTipHash || 'none').slice(0, 18)}...\`\n` +
    `Checkpoint: #${proof.btcCheckpoint.height}\n` +
    `Absorbed: ${proof.absorbedCount} blocks\n` +
    `Verified Depth: ${proof.verifiedDepth}\n` +
    `━━ Proof Hash ━━\n` +
    `\`${proof.proofHash}\`\n` +
    `━━ Claim ━━\n` +
    `_"${proof.claim}"_`,
    { parse_mode: 'Markdown' }
  );
});

// ── AuxPoW stats ──────────────────────────────────────────────────
bot.onText(/\/auxpow/, msg => {
  if (!isOwner(msg)) return;
  const s = _auxpow?.getAuxPoWStats?.() || {};
  bot.sendMessage(msg.chat.id,
    `*AuxPoW — Merged Mining*\n` +
    `Status: ${s.enabled ? '✅ Enabled' : '⭕ Disabled'}\n` +
    `Certified Blocks: ${s.totalCertified || 0}\n` +
    `Last BTC Block: ${s.lastCertifiedBtcBlock ? `#${s.lastCertifiedBtcBlock}` : 'none'}\n` +
    `Pending Challenge: \`${s.pendingAyrBlockHash || 'none'}\`\n` +
    `Marker: \`${s.marker || ''}\`\n` +
    `━━ Recent ━━\n` +
    (s.recentCertifications?.length
      ? s.recentCertifications.map(c => `AYR \`${c.ayr}\` ← BTC ${c.btc} @ ${c.at}`).join('\n')
      : 'No certifications yet — mine to earn!'),
    { parse_mode: 'Markdown' }
  );
});

// ── UTXO Registry ─────────────────────────────────────────────────
bot.onText(/\/utxos/, msg => {
  if (!isOwner(msg)) return;
  const stats = _utxoNative?.getUTXOStats?.() || {};
  const list  = (stats.activatedUTXOs || []).slice(-5)
    .map(u => `\`${u.id}\` ${u.btc} BTC → ${u.owner}`)
    .join('\n');
  bot.sendMessage(msg.chat.id,
    `*Native UTXO Registry*\n` +
    `Active UTXOs: ${stats.currentlyActive || 0}\n` +
    `Total BTC Active: ${stats.totalBtcActive || '0.00000000'} BTC\n` +
    `Deactivated: ${stats.deactivated || 0}\n` +
    `Force Deactivated: ${stats.forceDeactivated || 0}\n` +
    `━━ Recent Active ━━\n` +
    (list || 'No UTXOs activated yet'),
    { parse_mode: 'Markdown' }
  );
});

// ── UTXO Activation ───────────────────────────────────────────────
// Usage: /activate <txid> <vout> <ayr_address> [bitcoin_sig] [bitcoin_address]
bot.onText(/\/activate (\S+) (\d+) (0x[a-fA-F0-9]{40})(?:\s+(\S+))?(?:\s+(\S+))?/,
  async (msg, match) => {
    if (!isOwner(msg)) return;
    const txid      = match[1].trim();
    const vout      = parseInt(match[2]);
    const ayrAddr   = match[3].trim();
    const btcSig    = match[4]?.trim() || '';
    const btcAddr   = match[5]?.trim() || '';

    bot.sendMessage(msg.chat.id, `🔍 Verifying UTXO \`${txid.slice(0, 16)}...:${vout}\`...`, { parse_mode: 'Markdown' });

    if (!_utxoNative) {
      bot.sendMessage(msg.chat.id, '❌ UTXO native bridge not initialized');
      return;
    }

    const result = await _utxoNative.activateUTXO(txid, vout, ayrAddr, btcSig, btcAddr);
    if (!result.ok) {
      bot.sendMessage(msg.chat.id, `❌ Activation failed\n${result.error}`);
      return;
    }

    bot.sendMessage(msg.chat.id,
      `✅ *UTXO Activated*\n` +
      `ID: \`${txid.slice(0, 20)}...:${vout}\`\n` +
      `Value: \`${result.valueBtc} BTC\`\n` +
      `Owner: \`${ayrAddr.slice(0, 16)}...\`\n` +
      `Tx: \`${result.txHash?.slice(0, 22)}...\`\n` +
      `Native AYR object — no wrapping ✅`,
      { parse_mode: 'Markdown' }
    );
  }
);

// ── Logs, chains, validators ──────────────────────────────────────
bot.onText(/\/logs/, msg => {
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id, '```\n' + (recentLogs.slice(-20).join('\n') || 'No logs.') + '\n```', { parse_mode: 'Markdown' });
});

bot.onText(/\/chains/, msg => {
  if (!isOwner(msg)) return;
  const lines = Object.entries(chainState).map(([c, s]) => {
    const healthy = (RPC_POOLS[c] || []).filter(u => !rpcState[c]?.failures[u] || rpcState[c].failures[u] < Date.now()).length;
    return `${c}: ${s.online ? `#${s.block.toLocaleString()} ${s.latency}ms` : 'offline'} ${healthy}/${(RPC_POOLS[c] || []).length} ${BRIDGE_CONTRACTS[c] ? '🔒' : '⭕'} ev:${s.events}`;
  }).join('\n');
  bot.sendMessage(msg.chat.id, '```\n' + lines + '\n```\nAETHYR: #' + (_cs?.latestBlock || 0), { parse_mode: 'Markdown' });
});

bot.onText(/\/validators/, msg => {
  if (!isOwner(msg)) return;
  const list = _validators?.size
    ? [..._validators.entries()].map(([a, v]) => `\`${a.slice(0, 14)}...\` ${v.stake} AYR`).join('\n')
    : `\`${AUTHORITY.slice(0, 16)}...\` AUTHORITY\nSlots: 0/21`;
  bot.sendMessage(msg.chat.id, `*Validators*\n${list}`, { parse_mode: 'Markdown' });
});

// ── Bridge, CID ───────────────────────────────────────────────────
bot.onText(/\/setbridge (\w+) (0x[a-fA-F0-9]{40})/, (msg, match) => {
  if (!isOwner(msg)) return;
  const chain = match[1].toUpperCase(), addr = match[2];
  BRIDGE_CONTRACTS[chain] = addr;
  if (rpcState[chain]) rpcState[chain].lastBlock = '0x0';
  const key = `BRIDGE_${chain}`; if (ENV_WRITABLE_KEYS.has(key)) writeEnvKey(key, addr);
  audit('SET_BRIDGE', `chain=${chain} addr=${addr}`);
  bot.sendMessage(msg.chat.id, `✅ ${chain} bridge: \`${addr}\``, { parse_mode: 'Markdown' });
});

bot.onText(/\/cid/, msg => {
  if (!isOwner(msg)) return;
  const cid = fs.existsSync(CID_FILE) ? fs.readFileSync(CID_FILE, 'utf8').trim() : 'none';
  bot.sendMessage(msg.chat.id, `CID: \`${cid}\``, { parse_mode: 'Markdown' });
});

bot.onText(/\/cidlog/, msg => {
  if (!isOwner(msg)) return;
  if (!fs.existsSync(CID_HIST)) { bot.sendMessage(msg.chat.id, 'No CID history.'); return; }
  const lines = fs.readFileSync(CID_HIST, 'utf8').trim().split('\n').slice(-10).join('\n');
  bot.sendMessage(msg.chat.id, '```\n' + lines + '\n```', { parse_mode: 'Markdown' });
});

// ── Economy ───────────────────────────────────────────────────────
bot.onText(/\/fees/, msg => {
  if (!isOwner(msg)) return;
  const f = _getFeeStats?.() || {};
  bot.sendMessage(msg.chat.id,
    `*Fee Engine*\nStatus: ${f.feeEngineActive ? '✅ ON' : '⭕ OFF'}\n` +
    `Collected: ${(Number(f.totalFeesCollected || 0) / 1e18).toFixed(6)} AYR\n` +
    `Buybacks: ${(Number(f.totalAyrBought || 0) / 1e18).toFixed(6)} AYR equiv\n` +
    `Logic: 50% burn → 0xdead | 50% buyback AYR via ROUTER`,
    { parse_mode: 'Markdown' }
  );
});
bot.onText(/\/feeon/,  msg => { if (!isOwner(msg)) return; _setFeeEngine?.(true);  audit('FEE', 'enabled');  bot.sendMessage(msg.chat.id, '✅ Fee engine ON'); });
bot.onText(/\/feeoff/, msg => { if (!isOwner(msg)) return; _setFeeEngine?.(false); audit('FEE', 'disabled'); bot.sendMessage(msg.chat.id, '⭕ Fee engine OFF'); });

bot.onText(/\/economy/, msg => {
  if (!isOwner(msg)) return;
  const f    = _getFeeStats?.() || {};
  const utxo = _utxoNative?.getUTXOStats?.() || {};
  bot.sendMessage(msg.chat.id,
    `*Economy — BCP*\n` +
    `AYR Supply: 21,000,000\n` +
    `Mint queue: ${f.mintQueueLen || 0}\n` +
    `Nonce: ${f.localNonce ?? 'unsynced'}\n` +
    `━━ Bitcoin Containment ━━\n` +
    `Active UTXOs: ${utxo.currentlyActive || 0}\n` +
    `BTC Contained: ${utxo.totalBtcActive || '0.00000000'} BTC\n` +
    `━━ Fees ━━\n` +
    `Collected: ${(Number(f.totalFeesCollected || 0) / 1e18).toFixed(6)}\n` +
    `Bought back: ${(Number(f.totalAyrBought || 0) / 1e18).toFixed(6)}`,
    { parse_mode: 'Markdown' }
  );
});

// ── Evolution ─────────────────────────────────────────────────────
bot.onText(/\/evolve (\S+)\n([\s\S]+)/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const fileName = match[1].trim(), code = match[2];
  bot.sendMessage(msg.chat.id, `⚙️ Staging \`${fileName}\`...`, { parse_mode: 'Markdown' });
  const result = await _stageEvolution(fileName, code);
  if (!result.ok) { bot.sendMessage(msg.chat.id, `❌ *Rejected*\n${result.reason}`, { parse_mode: 'Markdown' }); return; }
  bot.sendMessage(msg.chat.id,
    `🔬 *Staged*\nFile: \`${fileName}\`\nSHA-256: \`${result.hash}\`\n\nConfirm:\n\`/confirm ${result.token}\`\n\nExpires in 10 min.`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/confirm ([a-f0-9]{12})/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const result = await _applyEvolution(match[1]);
  if (!result.ok) { bot.sendMessage(msg.chat.id, `❌ ${result.reason}`); return; }
  bot.sendMessage(msg.chat.id, `✅ *Applied*\nFile: \`${result.file}\`\n${result.restart ? '🔄 Restarting...' : 'Active now.'}`, { parse_mode: 'Markdown' });
});

bot.onText(/\/rollback/, async msg => {
  if (!isOwner(msg)) return;
  try {
    const baks = fs.readdirSync(BASE_DIR).filter(f => f.includes('.bak.')).sort().reverse();
    if (!baks.length) { bot.sendMessage(msg.chat.id, 'No backup found.'); return; }
    fs.copyFileSync(require('path').join(BASE_DIR, baks[0]), require('path').join(BASE_DIR, 'node.js'));
    audit('ROLLBACK', baks[0]);
    bot.sendMessage(msg.chat.id, `✅ Rolled back: \`${baks[0]}\`\nRestarting...`, { parse_mode: 'Markdown' });
    setTimeout(() => _sandboxExec('/bin/systemctl', ['restart', 'aethyr']).catch(() => {}), 2000);
  } catch (e) { bot.sendMessage(msg.chat.id, `❌ ${e.message}`); }
});

bot.onText(/\/audit/, msg => {
  if (!isOwner(msg)) return;
  try {
    const lines = fs.existsSync(AUDIT_FILE)
      ? fs.readFileSync(AUDIT_FILE, 'utf8').split('\n').filter(Boolean).slice(-15).join('\n')
      : 'No audit log.';
    bot.sendMessage(msg.chat.id, '```\n' + lines + '\n```', { parse_mode: 'Markdown' });
  } catch (e) { bot.sendMessage(msg.chat.id, `Error: ${e.message}`); }
});

// ── Network ───────────────────────────────────────────────────────
bot.onText(/\/integrate (\w+) (https?:\/\/\S+)(?:\s+(0x[a-fA-F0-9]{40}))?/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const chainName = match[1].toUpperCase(), rpcUrl = match[2], bridgeAddr = match[3] || '';
  bot.sendMessage(msg.chat.id, `🔍 Probing ${chainName}...`);
  const result = await _integrateChain(chainName, rpcUrl, bridgeAddr);
  if (!result.ok) { bot.sendMessage(msg.chat.id, `❌ ${result.reason}`); return; }
  bot.sendMessage(msg.chat.id,
    `🔗 *${chainName} Integrated*\nChain ID: ${result.chainId}\nBlock: #${result.block.toLocaleString()}\n${bridgeAddr ? `Bridge: \`${bridgeAddr}\`` : 'Use /setbridge to watch bridge'}`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/repair/, async msg => {
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id, '🛠 Running diagnostics...');
  const lines = [];
  if (!_cs?.nodeProc || _cs.nodeProc.killed) { _cs.nodeProc = _spawnNode(); lines.push('Node: ↩ respawned'); } else lines.push('Node: ✅');
  try { await _syncNonce(); lines.push(`Nonce: ✅ ${_getNonce()}`); } catch (e) { lines.push(`Nonce: ❌ ${e.message.slice(0, 40)}`); }
  lines.push(`Engine: ${_cs?.engineLocked ? '✅ ' + _cs.engineFcuVer : '⚠ unlocked'}`);
  const { isAvailable } = require('./signer');
  lines.push(`Signer: ${isAvailable() ? '✅ ecdsa-secp256k1' : '⚠ unsigned'}`);
  try { const r = await fetch('http://127.0.0.1:5001/api/v0/id', { method: 'POST', signal: AbortSignal.timeout(3000) }); lines.push(`IPFS: ${r.ok ? '✅' : '❌'}`); } catch { lines.push('IPFS: ❌'); }
  const btcS = _btcAbsorber?.absorptionState || {};
  lines.push(`BTC Absorber: ${btcS.absorbedCount > 0 ? `✅ #${btcS.btcTipHeight}` : '⏳ syncing'}`);
  audit('REPAIR', lines.join('|'));
  bot.sendMessage(msg.chat.id, '```\n' + lines.join('\n') + '\n```', { parse_mode: 'Markdown' });
});

bot.onText(/\/rpcstatus/, msg => {
  if (!isOwner(msg)) return;
  const now = Date.now();
  const lines = Object.entries(RPC_POOLS).map(([chain, pool]) => {
    const h = pool.filter(u => !rpcState[chain]?.failures[u] || rpcState[chain].failures[u] < now).length;
    return `${chain}: ✅${h} 🔴${pool.length - h}`;
  }).join('\n');
  bot.sendMessage(msg.chat.id, '```\n' + lines + '\n```', { parse_mode: 'Markdown' });
});

bot.onText(/\/rpcrefresh/, async msg => {
  if (!isOwner(msg)) return;
  const cleared = [];
  for (const chain of Object.keys(RPC_POOLS)) {
    if (rpcState[chain]) {
      const hadDead = Object.values(rpcState[chain].failures || {}).some(t => t > Date.now());
      rpcState[chain].failures = {}; rpcState[chain].idx = 0;
      if (hadDead) cleared.push(chain);
    }
  }
  audit('RPC_REFRESH', `cleared=${cleared.join(',')}`);
  bot.sendMessage(msg.chat.id,
    cleared.length ? `✅ *RPC backoffs cleared*\nChains reset: ${cleared.join(', ')}` : `ℹ️ No active backoffs.`,
    { parse_mode: 'Markdown' }
  );
});

// ── Security ──────────────────────────────────────────────────────
bot.onText(/\/disk/, msg => {
  if (!isOwner(msg)) return;
  try {
    const { execSync } = require('child_process');
    const df = execSync(`df -h "${BASE_DIR}" 2>/dev/null | tail -1`, { timeout: 3000 }).toString().trim();
    const du = execSync(`du -sh "${BASE_DIR}" 2>/dev/null | cut -f1`, { timeout: 5000 }).toString().trim();
    bot.sendMessage(msg.chat.id, `*Disk*\n\`${df}\`\nChaindata total: ${du}`, { parse_mode: 'Markdown' });
  } catch (e) { bot.sendMessage(msg.chat.id, `❌ ${e.message}`); }
});

bot.onText(/\/memory/, msg => {
  if (!isOwner(msg)) return;
  const m = process.memoryUsage();
  const mb = v => Math.round(v / 1024 / 1024);
  bot.sendMessage(msg.chat.id,
    `*Memory*\nHeap used: ${mb(m.heapUsed)} MB / ${mb(m.heapTotal)} MB\nRSS: ${mb(m.rss)} MB\nExternal: ${mb(m.external)} MB`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/vault/, msg => {
  if (!isOwner(msg)) return;
  const { isAvailable, getPublicKey } = require('./signer');
  bot.sendMessage(msg.chat.id,
    `*Vault Status*\n` +
    `TKN: ${VAULT.TKN ? '✅' : '❌'}\n` +
    `SIGNER\\_ADDR: \`${VAULT.SIGNER_ADDR.slice(0, 16)}...\`\n` +
    `SIGNER\\_PRIV: ${VAULT.SIGNER_PRIV ? '✅ sealed' : '⚠ not set'}\n` +
    `Signer method: ${isAvailable() ? 'ecdsa-secp256k1' : 'unsigned'}\n` +
    `Pubkey: ${getPublicKey() ? `\`${getPublicKey().slice(0, 20)}...\`` : 'n/a'}\n` +
    `Evolution guards: 4-pass scan active`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/auth/, msg => {
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id, `*Auth*\nOwner chat ID: \`${activeChatId}\`\nAll others silently rejected + audited.`, { parse_mode: 'Markdown' });
});

// ── Plugins ───────────────────────────────────────────────────────
bot.onText(/\/plugins/, msg => {
  if (!isOwner(msg)) return;
  const list = _listPlugins?.() || [];
  if (!list.length) { bot.sendMessage(msg.chat.id, 'No plugins installed.'); return; }
  bot.sendMessage(msg.chat.id, `*Installed Plugins* (${list.length})\n\`\`\`\n${list.join('\n')}\n\`\`\``, { parse_mode: 'Markdown' });
});

bot.onText(/\/delplugin (\S+)/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const result = await _deletePlugin?.(match[1].trim());
  bot.sendMessage(msg.chat.id, result?.ok ? `✅ Deleted: ${match[1]}` : `❌ ${result?.reason}`);
  if (result?.ok) audit('PLUGIN_DELETE_CMD', match[1]);
});

// ── AI ────────────────────────────────────────────────────────────
async function askAI(question, context) {
  if (!VAULT.AI_KEY) return '❌ AI not configured — set AI= in .env';
  try {
    const btcS = _btcAbsorber?.absorptionState || {};
    const systemPrompt = `You are CORTEX, the AI brain of AETHYR ONE blockchain.
ARCHITECTURE: Bitcoin Containment Protocol (BCP).
AYR does not wrap Bitcoin. AYR contains Bitcoin's full chain state.
Every AYR block commits to Bitcoin's rolling chain commitment.
Bitcoin UTXOs are native AYR objects — no wrapping needed.

Current state:
- Chain ID: ${CHAIN_ID}, Authority: ${AUTHORITY}
- AYR Block: ${context.block}, Sealed: ${context.blockCount}
- Node: ${context.nodeOk}, Signer: ${context.signerOk}
- BTC Tip: #${btcS.btcTipHeight}, Absorbed: ${btcS.absorbedCount}
- BTC Commitment: ${btcS.chainCommitment?.slice(0, 16)}...
- Active UTXOs: ${context.utxoCount}
- Uptime: ${context.uptime}
- Chains: ${context.chains}
${context.logs}`;

    const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${VAULT.AI_KEY}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://aethyr.one',
        'X-Title': 'AETHYR ONE',
      },
      body: JSON.stringify({
        model: VAULT.AI_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user',   content: question },
        ],
        max_tokens: 500,
      }),
    });
    const data = await res.json();
    if (data.error) return `❌ AI error: ${data.error.message?.slice(0, 100)}`;
    return data.choices?.[0]?.message?.content || '❌ No response';
  } catch (e) { return `❌ AI error: ${e.message.slice(0, 100)}`; }
}

function buildContext() {
  const { isAvailable } = require('./signer');
  const fees   = _getFeeStats?.() || {};
  const utxo   = _utxoNative?.getUTXOStats?.() || {};
  const h = Math.floor(process.uptime() / 3600);
  const m = Math.floor((process.uptime() % 3600) / 60);
  return {
    block:      _cs?.latestBlock || 0,
    blockCount: _cs?.blockCount  || 0,
    nodeOk:     _cs?.nodeProc && !_cs.nodeProc.killed ? 'YES' : 'NO',
    signerOk:   isAvailable() ? 'YES' : 'NO',
    ipfsOk:     _cs?.ipfsOnline ? 'YES' : 'NO',
    feeActive:  fees.feeEngineActive ? 'ON' : 'OFF',
    utxoCount:  utxo.currentlyActive || 0,
    uptime:     `${h}h ${m}m`,
    chains:     Object.entries(chainState || {})
      .map(([c, s]) => `${c}:${s.online ? '#' + s.block : 'OFFLINE'}`).join(' ') || 'none',
    logs: recentLogs?.slice(-15).join('\n') || 'no logs',
  };
}

bot.onText(/\/ask (.+)/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const question = match[1].trim();
  bot.sendMessage(msg.chat.id, '🤖 _Thinking..._', { parse_mode: 'Markdown' });
  const answer = await askAI(question, buildContext());
  bot.sendMessage(msg.chat.id, `🤖 *CORTEX*\n\n${answer}`, { parse_mode: 'Markdown' });
  audit('AI_QUERY', `q=${question.slice(0, 60)}`);
});

bot.onText(/\/diagnose/, async msg => {
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id, '🔍 _Running AI diagnostics..._', { parse_mode: 'Markdown' });
  const answer = await askAI(
    'Analyze current node state, BCP absorption health, and logs. Identify problems. Be specific.',
    buildContext()
  );
  bot.sendMessage(msg.chat.id, `🔍 *AI Diagnostics*\n\n${answer}`, { parse_mode: 'Markdown' });
});

bot.onText(/\/report/, async msg => {
  if (!isOwner(msg)) return;
  bot.sendMessage(msg.chat.id, '📊 _Generating report..._', { parse_mode: 'Markdown' });
  const answer = await askAI(
    'Give a brief operational report: blocks sealed, Bitcoin containment state, chain health, issues.',
    buildContext()
  );
  bot.sendMessage(msg.chat.id, `📊 *Node Report*\n\n${answer}`, { parse_mode: 'Markdown' });
});

bot.onText(/\/expand(?:\s+(\S+))?/, async (msg, match) => {
  if (!isOwner(msg)) return;
  const idea = match[1]?.trim() || 'decide what would be most valuable to add';
  bot.sendMessage(msg.chat.id, `🧬 *CORTEX expanding...* \`${idea}\``, { parse_mode: 'Markdown' });
  if (!VAULT.AI_KEY) { bot.sendMessage(msg.chat.id, '❌ AI_KEY not set'); return; }
  try {
    const ctx = buildContext();
    const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${VAULT.AI_KEY}`, 'Content-Type': 'application/json', 'HTTP-Referer': 'https://aethyr.one', 'X-Title': 'AETHYR ONE' },
      body: JSON.stringify({
        model: VAULT.AI_MODEL,
        messages: [
          { role: 'system', content: `You are CORTEX, the self-evolving AI of AETHYR ONE. Write REAL production Node.js plugins. Export init({tg,tgNow,tgBuffer,record,rpcCall,chainState,CONTRACTS,CHAIN_ID,AUTHORITY}). Use fetch, path, crypto only. NEVER access VAULT, process.env, child_process, eval. Start with FILENAME: plugin-name.js. No markdown, no backticks. Real working code only.` },
          { role: 'user', content: `Create a plugin to: ${idea}` },
        ],
        max_tokens: 3000,
      }),
    });
    const data = await res.json();
    if (data.error) { bot.sendMessage(msg.chat.id, `❌ AI error: ${data.error.message?.slice(0, 100)}`); return; }
    const raw   = data.choices?.[0]?.message?.content || '';
    const lines = raw.replace(/^```javascript\n?/, '').replace(/^```js\n?/, '').replace(/```$/, '').trim().split('\n');
    let fileName = 'plugin-' + Date.now() + '.js', codeStart = 0;
    if (lines[0].startsWith('FILENAME:')) { fileName = lines[0].replace('FILENAME:', '').trim(); codeStart = 1; }
    const code = lines.slice(codeStart).join('\n').trim();
    const result = await _createPlugin?.(fileName, code);
    if (!result?.ok) { bot.sendMessage(msg.chat.id, `🧬 Plugin rejected\n${result?.reason}\n\n${code.slice(0, 300)}`); return; }
    bot.sendMessage(msg.chat.id, `🧬 Plugin Installed\nFile: ${fileName}\nSize: ${code.length} bytes\nRestart to activate.`);
    audit('EXPAND', `file=${fileName} idea=${idea.slice(0, 60)}`);
  } catch (e) { bot.sendMessage(msg.chat.id, `❌ Expand error: ${e.message.slice(0, 100)}`); }
});

// Hourly heartbeat
setInterval(() => {
  if (!activeChatId) return;
  const btcS   = _btcAbsorber?.absorptionState || {};
  const utxo   = _utxoNative?.getUTXOStats?.() || {};
  const auxS   = _auxpow?.getAuxPoWStats?.() || {};
  const chains = Object.entries(chainState).map(([c, s]) => `${c}:${s.online ? '#' + s.block.toLocaleString() : 'off'}`).join(' ');
  tg(
    `*Hourly*\nAYR:#${_cs?.latestBlock || 0} | BTC:#${btcS.btcTipHeight || 0}\n` +
    `Absorbed:${btcS.absorbedCount || 0} | UTXOs:${utxo.currentlyActive || 0} | AuxPoW:${auxS.totalCertified || 0}\n` +
    `${chains}`
  );
}, 3_600_000);

module.exports = { tg, tgNow, tgBuffer, writeEnvKey, init };
