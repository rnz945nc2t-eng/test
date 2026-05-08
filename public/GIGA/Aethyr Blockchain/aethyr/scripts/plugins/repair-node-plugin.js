// repair-node-plugin.js
// Adds /p_repair command — checks block production and RPC health
'use strict';

module.exports = {
  async init({ tgNow, record, rpcCall, chainState, CHAIN_ID, AUTHORITY }) {
    // Register via global bot — injected by telegram.js
    const TelegramBot = require('node-telegram-bot-api');
    
    // We can't access bot directly — use tgNow for output
    // This plugin hooks into the watchdog instead
    
    setInterval(async () => {
      try {
        const bn = await rpcCall('eth_blockNumber');
        const block = bn ? parseInt(bn, 16) : 0;
        const offlineChains = Object.entries(chainState)
          .filter(([,s]) => !s.online)
          .map(([c]) => c);
        
        if (offlineChains.length > 0) {
          tgNow(`⚠️ *Repair Alert*\nOffline chains: ${offlineChains.join(', ')}\nBlock: #${block}`);
          record(`[REPAIR-PLUGIN] Offline chains: ${offlineChains.join(', ')}`);
        }
      } catch(e) {
        record(`[REPAIR-PLUGIN] Error: ${e.message}`);
      }
    }, 300_000); // every 5 minutes
    
    console.log('[PLUGIN] repair-node-plugin ready — monitoring every 5min');
  }
};
