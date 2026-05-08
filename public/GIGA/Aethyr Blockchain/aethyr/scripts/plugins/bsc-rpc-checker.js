'use strict';
// Plugin: bsc-rpc-checker.js
// Monitors BSC RPC health every 5 minutes
// Uses chainState which is already updated by observer.js

module.exports = {
  async init({ tgNow, record, chainState }) {
    let lastStatus = true;

    setInterval(() => {
      const bsc = chainState['BSC'];
      if (!bsc) return;

      if (!bsc.online && lastStatus) {
        // Just went offline
        tgNow('⚠️ BSC RPC: OFFLINE — block stuck at #' + bsc.block + ' errors:' + bsc.errors);
        record('[BSC-PLUGIN] BSC went offline');
        lastStatus = false;
      } else if (bsc.online && !lastStatus) {
        // Just came back online
        tgNow('✅ BSC RPC: Back online — #' + bsc.block + ' latency:' + bsc.latency + 'ms');
        record('[BSC-PLUGIN] BSC back online');
        lastStatus = true;
      }
    }, 300_000);

    console.log('[PLUGIN] bsc-rpc-checker ready');
  }
};
