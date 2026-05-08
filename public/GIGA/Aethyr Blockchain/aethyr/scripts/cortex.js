'use strict';
// ================================================================
// AETHYR ONE — cortex.js
// Staged code evolution (hash → confirm → apply),
// sandboxed exec allowlist, dynamic chain integration.
//
// Security hardening vs previous version:
//   - npm install removed from allowlist (supply-chain risk)
//   - Multi-pass scanner: regex + token-level obfuscation detection
//   - Bracket/string-concat access patterns blocked
//   - File extension whitelist for evolution targets
//   - Staged file verified by hash at apply time
// ================================================================
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');
const { RPC_POOLS, BRIDGE_CONTRACTS, initChainState, saveChainRegistry } = require('./rpc');
const { audit } = require('./audit');
const { BASE_DIR: _BD, STAGE_FILE: _SF } = require('./config');

let _tgNow = () => {};
function init({ tgNow }) { _tgNow = tgNow; }

// ── Sandbox exec ─────────────────────────────────────────────────
// npm install deliberately removed — dependency changes must go
// through a manual deploy, not the evolution engine.
const EXEC_ALLOWLIST = [
  { bin: 'node',        argRe: /^--check\s/ },
  { bin: 'systemctl',   argRe: /^(restart|status)\s+(aethyr|ipfs|ipfs-daemon|kubo)$/ },
  { bin: 'ipfs',        argRe: /^(version|pin|add|daemon)/ },
  { bin: 'timedatectl', argRe: /^set-ntp\s+(true|false)$/ },
];

function sandboxExec(bin, args, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const basename = path.basename(bin);
    const rule = EXEC_ALLOWLIST.find(r => r.bin === basename);
    if (!rule) { reject(new Error(`SANDBOX: binary not allowed: ${basename}`)); return; }
    const argStr = args.join(' ');
    if (!rule.argRe.test(argStr)) { reject(new Error(`SANDBOX: args rejected for ${basename}: ${argStr}`)); return; }
    audit('EXEC', `${basename} ${argStr}`);
    execFile(bin, args, { timeout, cwd: _BD }, (err, stdout, stderr) => {
      err ? reject(err) : resolve((stdout || stderr || '').trim());
    });
  });
}

// ── Security scan — multi-pass ───────────────────────────────────
// Pass 1: literal pattern matching
const FORBIDDEN_LITERAL = [
  /VAULT\s*[\.\[]/,                         // VAULT access
  /SIGNER_PRIV/i,                           // key name
  /process\s*\.\s*env\s*[\.\[]/,           // env access
  /readFileSync\s*\(.*\.env/,              // reading .env
  /require\s*\(\s*['"`]dotenv['"`]\s*\)/,  // loading dotenv
  /eval\s*\(/,                              // eval
  /new\s+Function\s*\(/,                   // Function constructor
  /child_process/,                          // process spawning
  /process\s*\.\s*exit/,                   // forced exit
  /process\s*\.\s*kill/,                   // kill signals
  /require\s*\(\s*['"`]fs['"`]\s*\)/,      // raw fs (use injected refs only)
  /require\s*\(\s*['"`]child_process['"`]\s*\)/, // child_process
  /require\s*\(\s*['"`]net['"`]\s*\)/,     // raw network
  /require\s*\(\s*['"`]http['"`]\s*\)/,    // raw http server
  /require\s*\(\s*['"`]https['"`]\s*\)/,   // raw https server
  /require\s*\(\s*['"`]cluster['"`]\s*\)/, // cluster
  /require\s*\(\s*['"`]vm['"`]\s*\)/,      // vm (sandbox escape)
  /require\s*\(\s*['"`]repl['"`]\s*\)/,    // REPL
];

// Pass 2: obfuscation patterns — bracket access & string concat tricks
// e.g. process['env'], process["en"+"v"], global['process']
const FORBIDDEN_OBFUSCATED = [
  /\[\s*['"`]env['"`]\s*\]/,                         // ['env']
  /\[\s*['"`]SIGNER|PRIV|VAULT|TKN['"`]/i,           // ['SIGNER...']
  /\[\s*['"`]exit['"`]\s*\]/,                         // ['exit']
  /\[\s*['"`]kill['"`]\s*\]/,                         // ['kill']
  /\[\s*['"`]child_process['"`]\s*\]/,               // ['child_process']
  /global\s*[\.\[]/,                                  // global object access
  /globalThis\s*[\.\[]/,                              // globalThis access
  /\bBuffer\s*\.\s*from\s*\(.*base64/i,              // base64 decoding (payload hiding)
  /atob\s*\(/,                                        // atob decode
  /String\s*\.\s*fromCharCode/,                       // char-by-char string build
  /\\x[0-9a-f]{2}/i,                                 // hex escapes (obfuscated strings)
];

// Pass 3: high-value contract addresses must not appear (prevents address injection)
// Any 40-char hex string that isn't surrounded by test/comment context
const FORBIDDEN_ADDR = /0x[0-9a-fA-F]{40}/;

function securityScan(code) {
  // Pass 1
  for (const p of FORBIDDEN_LITERAL) {
    if (p.test(code)) return { ok: false, reason: `Forbidden pattern: ${p.source.slice(0, 60)}` };
  }
  // Pass 2
  for (const p of FORBIDDEN_OBFUSCATED) {
    if (p.test(code)) return { ok: false, reason: `Obfuscation detected: ${p.source.slice(0, 60)}` };
  }
  // Pass 3 — block injected addresses
  if (FORBIDDEN_ADDR.test(code)) {
    return { ok: false, reason: 'Raw 0x addresses not allowed in evolved code — use CONTRACTS.* refs' };
  }
  // Pass 4 — total size limit (prevent giant payload injection)
  if (code.length > 50_000) {
    return { ok: false, reason: `Code too large: ${code.length} bytes (max 50,000)` };
  }
  return { ok: true };
}

// ── Allowed evolution targets ────────────────────────────────────
// Only these specific filenames may be overwritten via /evolve.
// node.js itself is allowed (triggers service restart).
// config.js and signer.js are NEVER allowed — key material lives there.
const EVOLUTION_ALLOWED_FILES = new Set([
  'node.js', 'consensus.js', 'cortex.js', 'watchdog.js',
  'relayer.js', 'btc.js', 'observer.js', 'telegram.js',
  'audit.js', 'rpc.js',
]);

// ── Staged evolution ─────────────────────────────────────────────
const pendingEvolutions = new Map();

async function stageEvolution(fileName, code) {
  // Filename validation
  if (!/^[\w.-]+\.js$/.test(fileName) || fileName.includes('..') || fileName.includes('/')) {
    return { ok: false, reason: 'Invalid filename format' };
  }
  if (!EVOLUTION_ALLOWED_FILES.has(fileName)) {
    return { ok: false, reason: `File not in evolution allowlist: ${fileName}` };
  }
  // Security scan
  const scan = securityScan(code);
  if (!scan.ok) {
    audit('EVOLUTION_BLOCKED', `file=${fileName} reason=${scan.reason}`);
    return { ok: false, reason: scan.reason };
  }
  // Write to stage file and syntax-check with Node
  fs.writeFileSync(_SF, code, 'utf8');
  try {
    await sandboxExec(process.execPath, ['--check', _SF]);
  } catch (e) {
    try { fs.unlinkSync(_SF); } catch {}
    return { ok: false, reason: `Syntax error: ${e.message.slice(0, 200)}` };
  }
  const hash  = crypto.createHash('sha256').update(code).digest('hex');
  const token = hash.slice(0, 12);
  pendingEvolutions.set(token, { fileName, hash, ts: Date.now() });
  // Auto-expire after 10 minutes
  setTimeout(() => {
    pendingEvolutions.delete(token);
    try { if (fs.existsSync(_SF)) fs.unlinkSync(_SF); } catch {}
  }, 600_000);
  audit('EVOLUTION_STAGED', `file=${fileName} hash=${hash.slice(0, 16)} token=${token}`);
  return { ok: true, token, hash: hash.slice(0, 16) };
}

async function applyEvolution(token) {
  const ev = pendingEvolutions.get(token);
  if (!ev) return { ok: false, reason: 'Invalid or expired token' };
  if (!fs.existsSync(_SF)) return { ok: false, reason: 'Staged file missing — re-stage it' };
  // Re-verify hash before applying (tamper check)
  const code = fs.readFileSync(_SF, 'utf8');
  if (crypto.createHash('sha256').update(code).digest('hex') !== ev.hash) {
    audit('EVOLUTION_TAMPER', `file=${ev.fileName} token=${token}`);
    return { ok: false, reason: 'Hash mismatch — staged file was tampered with' };
  }
  const target = path.join(_BD, ev.fileName);
  // Always backup existing file before overwrite
  if (fs.existsSync(target)) {
    fs.copyFileSync(target, `${target}.bak.${Date.now()}`);
  }
  fs.renameSync(_SF, target);
  pendingEvolutions.delete(token);
  audit('EVOLUTION_APPLIED', `file=${ev.fileName} hash=${ev.hash.slice(0, 16)}`);
  const isMain = ev.fileName === 'node.js' || ev.fileName === 'consensus.js';
  if (isMain) {
    _tgNow(`🔄 *${ev.fileName} updated — restarting aethyr...*`);
    setTimeout(() => sandboxExec('/bin/systemctl', ['restart', 'aethyr']).catch(() => {}), 2000);
  }
  return { ok: true, file: ev.fileName, restart: isMain };
}

// ── Dynamic chain integration ────────────────────────────────────
async function probeChain(rpcUrl) {
  // Basic URL validation — no local/private ranges
  try {
    const u = new URL(rpcUrl);
    if (!['http:', 'https:'].includes(u.protocol)) return { ok: false, reason: 'Only http/https allowed' };
    const host = u.hostname;
    if (['127.0.0.1','localhost','0.0.0.0','::1'].includes(host)) {
      return { ok: false, reason: 'Local RPC addresses not allowed for external chains' };
    }
  } catch { return { ok: false, reason: 'Invalid URL' }; }

  try {
    const r1 = await fetch(rpcUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] }),
      signal: AbortSignal.timeout(8000),
    });
    const d1 = await r1.json();
    if (!d1.result) return { ok: false, reason: 'No eth_chainId response' };
    const r2 = await fetch(rpcUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_blockNumber', params: [] }),
      signal: AbortSignal.timeout(5000),
    });
    const d2 = await r2.json();
    return { ok: true, chainId: parseInt(d1.result, 16), block: parseInt(d2.result || '0x0', 16) };
  } catch (e) { return { ok: false, reason: e.message }; }
}

async function integrateChain(chainName, rpcUrl, bridgeAddr = '') {
  const probe = await probeChain(rpcUrl);
  if (!probe.ok) return probe;
  if (!RPC_POOLS[chainName]) { RPC_POOLS[chainName] = []; initChainState(chainName); }
  if (!RPC_POOLS[chainName].includes(rpcUrl)) RPC_POOLS[chainName].push(rpcUrl);
  if (bridgeAddr) BRIDGE_CONTRACTS[chainName] = bridgeAddr;
  saveChainRegistry();
  audit('CHAIN_INTEGRATED', `chain=${chainName} chainId=${probe.chainId} rpc=${rpcUrl}`);
  return { ok: true, chainId: probe.chainId, block: probe.block };
}


// ── Plugin creation (AI expansion) ──────────────────────────────
// Plugins live in scripts/plugins/ — separate from core files.
// Looser rules: can use fetch, require('path'), require('crypto').
// Still blocked: VAULT, keys, process.env, child_process, eval.
const PLUGIN_FORBIDDEN = [
  /VAULT\s*[\.\[]/,
  /SIGNER_PRIV/i,
  /SIGNER_PASS/i,
  /process\s*\.\s*env\s*[\.\[]/,
  /require\s*\(\s*['"`]dotenv['"`]\s*\)/,
  /eval\s*\(/,
  /new\s+Function\s*\(/,
  /child_process/,
  /process\s*\.\s*exit/,
  /process\s*\.\s*kill/,
  /require\s*\(\s*['"`]child_process['"`]\s*\)/,
  /require\s*\(\s*['"`]vm['"`]\s*\)/,
  /require\s*\(\s*['"`]cluster['"`]\s*\)/,
  /require\s*\(\s*['"`]repl['"`]\s*\)/,
  /\[\s*['"`]env['"`]\s*\]/,
  /globalThis\s*[\.\[]/,
  /global\s*[\.\[]/,
];

async function createPlugin(fileName, code) {
  // Validate filename
  if (!/^[\w-]+\.js$/.test(fileName) || fileName.includes('..')) {
    return { ok: false, reason: 'Invalid plugin filename' };
  }

  // Security scan — plugin-level rules
  for (const p of PLUGIN_FORBIDDEN) {
    if (p.test(code)) {
      audit('PLUGIN_BLOCKED', `file=${fileName} reason=${p.source.slice(0,60)}`);
      return { ok: false, reason: `Forbidden pattern: ${p.source.slice(0,60)}` };
    }
  }

  // Size limit
  if (code.length > 100_000) {
    return { ok: false, reason: `Plugin too large: ${code.length} bytes (max 100,000)` };
  }

  // Syntax check
  const tmpFile = require('path').join(_BD, 'node.staged.plugin.js');
  require('fs').writeFileSync(tmpFile, code, 'utf8');
  try {
    await sandboxExec(process.execPath, ['--check', tmpFile]);
  } catch(e) {
    try { require('fs').unlinkSync(tmpFile); } catch {}
    return { ok: false, reason: `Syntax error: ${e.message.slice(0, 200)}` };
  }

  // Write to plugins directory
  const pluginsDir = require('path').join(_BD, 'scripts', 'plugins');
  if (!require('fs').existsSync(pluginsDir)) {
    require('fs').mkdirSync(pluginsDir, { recursive: true });
  }
  const pluginPath = require('path').join(pluginsDir, fileName);

  // Backup if exists
  if (require('fs').existsSync(pluginPath)) {
    require('fs').copyFileSync(pluginPath, `${pluginPath}.bak.${Date.now()}`);
  }

  require('fs').renameSync(tmpFile, pluginPath);
  audit('PLUGIN_CREATED', `file=${fileName} size=${code.length}`);
  return { ok: true, path: pluginPath };
}

async function deletePlugin(fileName) {
  if (!/^[\w-]+\.js$/.test(fileName)) return { ok: false, reason: 'Invalid filename' };
  const pluginPath = require('path').join(_BD, 'scripts', 'plugins', fileName);
  if (!require('fs').existsSync(pluginPath)) return { ok: false, reason: 'Plugin not found' };
  require('fs').unlinkSync(pluginPath);
  audit('PLUGIN_DELETED', `file=${fileName}`);
  return { ok: true };
}

function listPlugins() {
  const pluginsDir = require('path').join(_BD, 'scripts', 'plugins');
  if (!require('fs').existsSync(pluginsDir)) return [];
  return require('fs').readdirSync(pluginsDir).filter(f => f.endsWith('.js'));
}
module.exports = { init, sandboxExec, stageEvolution, applyEvolution, probeChain, integrateChain, createPlugin, deletePlugin, listPlugins };
