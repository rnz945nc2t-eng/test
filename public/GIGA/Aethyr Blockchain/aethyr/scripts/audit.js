'use strict';
// ================================================================
// AETHYR ONE — audit.js
// Tamper-evident audit log (HMAC stamp via signer.js) +
// in-memory ring buffer for /logs command.
// ================================================================
const fs = require('fs');
const { AUDIT_FILE, LOG_FILE, sanitize } = require('./config');

// Lazy import avoids circular dep (signer→config, audit→config — fine)
function _stamp(body) {
  try { return require('./signer').auditStamp(body); }
  catch { return '????????????????'; }
}

const recentLogs = [];

function audit(action, detail = '') {
  const ts   = new Date().toISOString();
  const body = `${ts} | ${action} | ${sanitize(String(detail))}`;
  const line = `${body} | ${_stamp(body)}\n`;
  try { fs.appendFileSync(AUDIT_FILE, line); } catch {}
  console.log(`[AUDIT] ${body}`);
}

function record(line) {
  const safe = sanitize(line);
  recentLogs.push(`${new Date().toISOString().slice(11, 23)} ${safe}`);
  if (recentLogs.length > 500) recentLogs.shift();
}

function appendBtorLog(entry) {
  try { fs.appendFileSync(LOG_FILE, `${entry.length}:${entry}`); } catch {}
}

module.exports = { audit, record, recentLogs, appendBtorLog };
