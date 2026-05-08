
'use strict';
module.exports = {
  async init({ tgNow, rpcCall }) {
    const res = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=aethyr&vs_currencies=usd');
    const data = await res.json();
    tgNow('AYR Price: $' + data?.aethyr?.usd);
  }
};
