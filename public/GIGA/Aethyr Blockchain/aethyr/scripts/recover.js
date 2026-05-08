#!/usr/bin/env node
// ============================================================
// AETHYR CHAIN RECOVERY
// Bootstraps the chain from a magnet link or IPFS CID
//
// Usage:
//   node recover.js --ipfs  QmXXXX...
//   node recover.js --magnet "magnet:?xt=urn:btih:XXXX..."
//   node recover.js --auto        (reads utorrent.cid from disk)
//   node recover.js --verify-only (just verify history, no reinit)
// ============================================================

require('dotenv').config();
const fs       = require('fs');
const path     = require('path');
const { execSync, spawn } = require('child_process');

const BASE_DIR    = '/home/87CF3011/2777-87';
const DATA_DIR    = path.join(BASE_DIR, 'chaindata');
const GENESIS     = path.join(BASE_DIR, 'genesis.json');
const LOG_FILE    = path.join(BASE_DIR, 'utorrent.dat');
const CID_FILE    = path.join(BASE_DIR, 'utorrent.cid');
const META_FILE   = path.join(BASE_DIR, 'utorrent.meta');
const ADDR_FILE   = path.join(BASE_DIR, 'deployed-addresses.json');
const IPFS_BIN    = '/usr/local/bin/ipfs';
const NODE_BIN    = process.env.NODE_BIN || './ayrnode';
const CHAIN_ID    = '210078';

const args        = process.argv.slice(2);
const mode        = args[0];
const input       = args[1];

// ── Logging ────────────────────────────────────────────────
function log(msg)  { console.log(`[RECOVER] ${msg}`); }
function ok(msg)   { console.log(`[RECOVER] ✅ ${msg}`); }
function warn(msg) { console.log(`[RECOVER] ⚠  ${msg}`); }
function err(msg)  { console.error(`[RECOVER] ✗  ${msg}`); }
function die(msg)  { err(msg); process.exit(1); }

// ── Bencode parser ─────────────────────────────────────────
function parseBencode(content) {
    return (content.match(/\d+:[^]*?(?=\d+:|e$)/g) || [])
        .map(m => {
            const colon = m.indexOf(':');
            const len   = parseInt(m.slice(0, colon));
            return m.slice(colon + 1, colon + 1 + len);
        })
        .filter(Boolean);
}

// ── Step 1: Fetch utorrent.dat ─────────────────────────────
async function fetchFromIPFS(cid) {
    log(`Fetching from IPFS: ${cid}`);
    try {
        execSync(`${IPFS_BIN} get -o "${LOG_FILE}" "${cid}"`, { stdio: 'inherit' });
        ok(`Downloaded utorrent.dat from IPFS`);
        return true;
    } catch (e) {
        warn(`IPFS fetch failed: ${e.message}`);
        return false;
    }
}

async function fetchFromMagnet(magnet) {
    log(`Fetching from magnet link...`);
    // Try webtorrent-cli if available
    try {
        execSync('which webtorrent', { stdio: 'ignore' });
        execSync(`webtorrent download "${magnet}" --out "${BASE_DIR}" --select utorrent.dat`, {
            stdio: 'inherit', timeout: 120000
        });
        ok(`Downloaded utorrent.dat via BitTorrent`);
        return true;
    } catch {
        // Fallback: try aria2c
        try {
            execSync('which aria2c', { stdio: 'ignore' });
            execSync(`aria2c "${magnet}" --dir="${BASE_DIR}"`, {
                stdio: 'inherit', timeout: 120000
            });
            ok(`Downloaded via aria2c`);
            return true;
        } catch {
            warn(`BitTorrent download failed — install webtorrent-cli or aria2c`);
            warn(`npm install -g webtorrent-cli`);
            return false;
        }
    }
}

// ── Step 2: Parse and verify utorrent.dat ─────────────────
function verifyLog() {
    if (!fs.existsSync(LOG_FILE)) {
        warn('utorrent.dat not found — fresh chain will be initialized');
        return { blocks: [], valid: false };
    }

    const content = fs.readFileSync(LOG_FILE, 'utf8');
    const entries = parseBencode(content);

    const blockEntries = entries.filter(e => e.includes('BLOCK #'));
    const lastBlock    = blockEntries[blockEntries.length - 1] || null;

    log(`Log entries: ${entries.length}`);
    log(`Block records: ${blockEntries.length}`);

    if (lastBlock) {
        const numMatch  = lastBlock.match(/BLOCK #(\d+)/);
        const hashMatch = lastBlock.match(/0x[a-f0-9]+/);
        const num  = numMatch?.[1]  || '?';
        const hash = hashMatch?.[0] || '?';
        ok(`Last recorded block: #${num} | ${hash}`);
    }

    // Print last 5 entries
    log('Last 5 log entries:');
    entries.slice(-5).forEach(e => console.log(`  → ${e}`));

    return { blocks: blockEntries, valid: blockEntries.length > 0, lastBlock };
}

// ── Step 3: Check chaindata state ─────────────────────────
function checkChaindata() {
    const exists = fs.existsSync(path.join(DATA_DIR, 'geth/chaindata'));
    const jwt    = fs.existsSync(path.join(DATA_DIR, 'geth/jwtsecret'));

    if (!exists) {
        warn('chaindata missing — will reinitialize from genesis');
        return { exists: false, jwt };
    }

    // Check head block via geth
    try {
        const result = execSync(
            `${NODE_BIN} --datadir "${DATA_DIR}" ` +
            `--networkid ${CHAIN_ID} ` +
            `console --exec "eth.blockNumber" 2>/dev/null || true`,
            { encoding: 'utf8', timeout: 10000 }
        ).trim();
        const blockNum = parseInt(result);
        if (!isNaN(blockNum)) {
            ok(`chaindata head block: #${blockNum}`);
            return { exists: true, jwt, headBlock: blockNum };
        }
    } catch { /* geth console might not work without running node */ }

    ok(`chaindata directory exists`);
    return { exists: true, jwt };
}

// ── Step 4: Reinitialize from genesis ─────────────────────
function reinitGenesis() {
    if (!fs.existsSync(GENESIS)) {
        die(`genesis.json not found at ${GENESIS}`);
    }

    log('Removing old chaindata...');
    try {
        fs.rmSync(DATA_DIR, { recursive: true, force: true });
        ok('Old chaindata removed');
    } catch (e) {
        die(`Failed to remove chaindata: ${e.message}`);
    }

    log('Reinitializing from genesis.json...');
    try {
        execSync(
            `${NODE_BIN} init --datadir "${DATA_DIR}" "${GENESIS}"`,
            { stdio: 'inherit' }
        );
        ok('Genesis initialized');
    } catch (e) {
        die(`Genesis init failed: ${e.message}`);
    }
}

// ── Step 5: Import signer account ─────────────────────────
function checkSigner() {
    const signerAddr = (process.env.SIGNER || '').toLowerCase();
    if (!signerAddr) { warn('SIGNER not set in .env — skipping account check'); return; }

    try {
        const keystoreDir = path.join(DATA_DIR, 'keystore');
        if (!fs.existsSync(keystoreDir)) { warn('keystore missing — run geth account import'); return; }

        const files = fs.readdirSync(keystoreDir);
        const found = files.some(f => f.toLowerCase().includes(signerAddr.replace('0x','')));

        if (found) { ok(`Signer account found in keystore`); }
        else { warn(`Signer ${signerAddr} NOT in keystore — import before starting`); }
    } catch (e) {
        warn(`Could not check keystore: ${e.message}`);
    }
}

// ── Step 6: Print recovery summary ───────────────────────
function printSummary(logInfo, chaindataInfo) {
    console.log('\n' + '═'.repeat(60));
    console.log('  AETHYR CHAIN — RECOVERY SUMMARY');
    console.log('═'.repeat(60));
    console.log(`  Chain ID     : ${CHAIN_ID}`);
    console.log(`  Base dir     : ${BASE_DIR}`);
    console.log(`  Genesis      : ${fs.existsSync(GENESIS) ? '✅ Found' : '❌ Missing'}`);
    console.log(`  Chaindata    : ${chaindataInfo.exists ? '✅ Present' : '⚠  Reinitialized'}`);
    console.log(`  JWT secret   : ${chaindataInfo.jwt ? '✅ Found' : '❌ Missing'}`);
    console.log(`  utorrent.dat : ${fs.existsSync(LOG_FILE) ? '✅ Found' : '⚠  Missing'}`);
    console.log(`  Block log    : ${logInfo.blocks.length} entries`);

    if (fs.existsSync(ADDR_FILE)) {
        const addrs = JSON.parse(fs.readFileSync(ADDR_FILE, 'utf8'));
        console.log(`  Contracts    : ${Object.keys(addrs).length} addresses on file`);
    }

    if (logInfo.lastBlock) console.log(`  Last block   : ${logInfo.lastBlock}`);

    console.log('═'.repeat(60));

    console.log('\n  NEXT STEPS:');

    if (!chaindataInfo.exists || !chaindataInfo.jwt) {
        console.log('  1. node node.js          ← starts fresh from genesis');
        console.log('  2. npx hardhat run scripts/deploy.js --network ayr');
        console.log('                           ← redeploy 10 contracts');
    } else if (chaindataInfo.headBlock === 2) {
        console.log('  ⚠  Chain rewound to #2 — contracts still deployed');
        console.log('  1. node node.js          ← chain will continue from #2');
        console.log('  2. Blocks will resume — no redeploy needed');
    } else {
        console.log('  1. node node.js          ← chain continues normally');
    }

    console.log('\n  BOOTSTRAP COMMAND (share this to join the network):');
    if (fs.existsSync(CID_FILE)) {
        const cid = fs.readFileSync(CID_FILE, 'utf8').trim();
        console.log(`  node recover.js --ipfs ${cid}`);
    }
    if (fs.existsSync(META_FILE)) {
        const meta = JSON.parse(fs.readFileSync(META_FILE, 'utf8'));
        if (meta.magnet) console.log(`  node recover.js --magnet "${meta.magnet}"`);
    }
    console.log('');
}

// ── MAIN ──────────────────────────────────────────────────
async function main() {
    console.log('\n⬡ AETHYR CHAIN RECOVERY');
    console.log(`  Mode: ${mode || '--verify-only'}\n`);

    let fetched = false;

    // Fetch utorrent.dat if requested
    if (mode === '--ipfs') {
        if (!input) die('Provide IPFS CID: node recover.js --ipfs <CID>');
        fetched = await fetchFromIPFS(input);

    } else if (mode === '--magnet') {
        if (!input) die('Provide magnet link: node recover.js --magnet "<magnet:?...>"');
        fetched = await fetchFromMagnet(input);

    } else if (mode === '--auto') {
        // Try CID file first, then meta file
        if (fs.existsSync(CID_FILE)) {
            const cid = fs.readFileSync(CID_FILE, 'utf8').trim();
            log(`Found saved CID: ${cid}`);
            fetched = await fetchFromIPFS(cid);
        }
        if (!fetched && fs.existsSync(META_FILE)) {
            const meta = JSON.parse(fs.readFileSync(META_FILE, 'utf8'));
            if (meta.magnet) fetched = await fetchFromMagnet(meta.magnet);
        }
        if (!fetched) warn('No CID or magnet found — using existing utorrent.dat');

    } else if (mode === '--reinit') {
        // Full reinit from genesis (nuclear option)
        warn('FULL REINIT — this wipes chaindata and restarts from genesis');
        reinitGenesis();
        checkSigner();
        const logInfo       = verifyLog();
        const chaindataInfo = checkChaindata();
        printSummary(logInfo, chaindataInfo);
        return;

    } else if (!mode || mode === '--verify-only') {
        log('Verify-only mode — checking existing state...');
    } else {
        console.log('Usage:');
        console.log('  node recover.js --ipfs  <CID>         fetch log from IPFS');
        console.log('  node recover.js --magnet "<magnet:?>" fetch log via torrent');
        console.log('  node recover.js --auto                use saved CID/magnet');
        console.log('  node recover.js --reinit              wipe + reinit from genesis');
        console.log('  node recover.js --verify-only         check state only (default)');
        process.exit(0);
    }

    // Always verify log and chaindata
    const logInfo       = verifyLog();
    const chaindataInfo = checkChaindata();
    checkSigner();
    printSummary(logInfo, chaindataInfo);
}

main().catch(e => { err(e.message); process.exit(1); });
